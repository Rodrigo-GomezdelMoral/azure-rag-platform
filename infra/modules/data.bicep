@description('Region of the storage and Cosmos accounts.')
param location string
@description('Tags applied to every taggable resource.')
param tags object
@description('Name suffix shared by the resources of this workload.')
param suffix string
@description('Log Analytics workspace that receives diagnostics.')
param logAnalyticsWorkspaceId string
@description('Principal of the API identity, which reads and writes conversation history and feedback.')
param apiPrincipalId string
@description('Principal of the jobs identity, which uploads the corpus.')
param jobsPrincipalId string
@description('Principal of the shared search service, which reads the corpus for indexing.')
param searchPrincipalId string

var storageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageBlobDataReader = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
var ninetyDays = 90 * 24 * 60 * 60
var corpusGrants = [{ principalId: jobsPrincipalId, role: storageBlobDataContributor }, { principalId: searchPrincipalId, role: storageBlobDataReader }]
var containers = [{ name: 'history', partitionKey: '/session_id' }, { name: 'feedback', partitionKey: '/trace_id' }]
var diagnostics = { workspaceId: logAnalyticsWorkspaceId, logs: [{ categoryGroup: 'allLogs', enabled: true }] }

resource storage 'Microsoft.Storage/storageAccounts@2026-06-01' = {
  name: 'st${replace(suffix, '-', '')}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: { allowSharedKeyAccess: false, allowBlobPublicAccess: false, minimumTlsVersion: 'TLS1_2', supportsHttpsTrafficOnly: true }
  resource blobs 'blobServices' = {
    name: 'default'
    resource corpus 'containers' = { name: 'corpus', properties: { publicAccess: 'None' } }
  }
}

resource corpusAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for grant in corpusGrants: {
  name: guid(storage::blobs::corpus.id, grant.principalId, grant.role)
  scope: storage::blobs::corpus
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', grant.role), principalId: grant.principalId, principalType: 'ServicePrincipal' }
}]

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2026-03-15' = {
  name: 'cosmos-${suffix}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard', disableLocalAuth: true, minimalTlsVersion: 'Tls12', consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [{ locationName: location, failoverPriority: 0 }], capabilities: [{ name: 'EnableServerless' }]
  }
  resource database 'sqlDatabases' = {
    name: 'rag'
    properties: { resource: { id: 'rag' } }
    resource container 'containers' = [for item in containers: {
      name: item.name
      properties: { resource: { id: item.name, partitionKey: { paths: [item.partitionKey], kind: 'Hash' }, defaultTtl: ninetyDays } }
    }]
  }
  resource apiDataAccess 'sqlRoleAssignments' = {
    name: guid(cosmos.id, apiPrincipalId, 'data-contributor')
    properties: { roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002', principalId: apiPrincipalId, scope: '${cosmos.id}/dbs/rag' }
  }
}

resource storageDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-shared-workspace'
  scope: storage::blobs
  properties: union(diagnostics, { metrics: [{ category: 'Transaction', enabled: true }] })
}

resource cosmosDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-shared-workspace'
  scope: cosmos
  properties: union(diagnostics, { metrics: [{ category: 'Requests', enabled: true }] })
}

@description('Cosmos DB endpoint.')
output cosmosEndpoint string = cosmos.properties.documentEndpoint
@description('Storage account name.')
output storageAccountName string = storage.name
@description('Storage account resource id, the keyless connection string of the search data source.')
output storageAccountId string = storage.id
@description('URL of the corpus container.')
output corpusContainerUrl string = '${storage.properties.primaryEndpoints.blob}corpus'

targetScope = 'resourceGroup'

@export()
@description('The landing zone outputs this workload consumes, copied verbatim from azd env get-values of azure-ai-landing-zone.')
type landingZoneOutputs = {
  sharedResourceGroupName: string, foundryAccountName: string, foundryProjectName: string, foundryProjectEndpoint: string
  chatDeploymentName: string, smallChatDeploymentName: string, embeddingDeploymentName: string
  searchServiceName: string, searchEndpoint: string, searchPrincipalId: string, registryName: string, registryLoginServer: string
  logAnalyticsWorkspaceId: string, actionGroupId: string
}

@description('Region of every resource; defaults to the location of the existing resource group.')
param location string = resourceGroup().location
@description('Environment name recorded in the env tag.')
param environmentName string = 'prod'
@description('Landing zone outputs; the shared resources are referenced as existing, never created here.')
param landingZone landingZoneOutputs
@description('Client id of the API app registration that defines the Rag.Query app role; created by the bootstrap in the README.')
param apiAppClientId string
@description('Image of the API and of both jobs; azd replaces it after the first build.')
param apiImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
@description('Image of the web frontend.')
param webImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
@description('Monthly budget of this resource group in the billing currency.')
param budgetAmount int = 40
@description('First day of the month the budget starts.')
param budgetStartDate string = utcNow('yyyy-MM-01')

var workload = 'ragplatform'
var suffix = '${workload}-${environmentName}-swc'
var tags = { workload: workload, env: environmentName, owner: 'portfolio', managedBy: 'bicep', repo: 'azure-rag-platform' }
var identityNames = ['id-ragapi', 'id-ragweb', 'id-ragjobs']

resource identities 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = [for name in identityNames: {
  name: name
  location: location
  tags: tags
}]

module data 'modules/data.bicep' = {
  name: 'data'
  params: {
    location: location, tags: tags, suffix: suffix, logAnalyticsWorkspaceId: landingZone.logAnalyticsWorkspaceId
    apiPrincipalId: identities[0].properties.principalId, jobsPrincipalId: identities[2].properties.principalId
    searchPrincipalId: landingZone.searchPrincipalId
  }
}

module sharedAccess 'modules/shared-access.bicep' = {
  name: 'shared-access'
  scope: resourceGroup(landingZone.sharedResourceGroupName)
  params: {
    foundryAccountName: landingZone.foundryAccountName, foundryProjectName: landingZone.foundryProjectName
    searchServiceName: landingZone.searchServiceName, registryName: landingZone.registryName
    apiPrincipalId: identities[0].properties.principalId, webPrincipalId: identities[1].properties.principalId
    jobsPrincipalId: identities[2].properties.principalId
  }
}

module apps 'modules/apps.bicep' = {
  name: 'apps'
  params: {
    location: location, tags: tags, suffix: suffix, logAnalyticsWorkspaceId: landingZone.logAnalyticsWorkspaceId
    actionGroupId: landingZone.actionGroupId, registryLoginServer: landingZone.registryLoginServer
    apiImage: apiImage, webImage: webImage, apiAppClientId: apiAppClientId, budgetAmount: budgetAmount, budgetStartDate: budgetStartDate
    identities: [for i in range(0, 3): { id: identities[i].id, clientId: identities[i].properties.clientId, principalId: identities[i].properties.principalId }]
    appSettings: {
      MODEL_PROVIDER: 'foundry', FOUNDRY_PROJECT_ENDPOINT: landingZone.foundryProjectEndpoint
      CHAT_DEPLOYMENT: landingZone.chatDeploymentName, SMALL_CHAT_DEPLOYMENT: landingZone.smallChatDeploymentName
      EMBEDDING_DEPLOYMENT: landingZone.embeddingDeploymentName, SEARCH_ENDPOINT: landingZone.searchEndpoint
      COSMOS_ENDPOINT: data.outputs.cosmosEndpoint, CORPUS_CONTAINER_URL: data.outputs.corpusContainerUrl, STORAGE_ACCOUNT_RESOURCE_ID: data.outputs.storageAccountId
      ENTRA_TENANT_ID: tenant().tenantId, API_AUDIENCE: 'api://${apiAppClientId}'
    }
  }
}

@description('Registry endpoint, read by azd to push images.')
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = landingZone.registryLoginServer
@description('Public URL of the API; every request needs an Entra token carrying the Rag.Query app role.')
output apiUrl string = apps.outputs.apiUrl
@description('Public URL of the web frontend.')
output webUrl string = apps.outputs.webUrl
@description('Cosmos DB endpoint.')
output cosmosEndpoint string = data.outputs.cosmosEndpoint
@description('Storage account that holds the corpus container.')
output storageAccountName string = data.outputs.storageAccountName
@description('Principal id of the web identity, which the bootstrap grants the Rag.Query app role.')
output webPrincipalId string = identities[1].properties.principalId

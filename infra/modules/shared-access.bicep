@description('Foundry account in the shared resource group.')
param foundryAccountName string
@description('Foundry project the chat clients and evaluations use.')
param foundryProjectName string
@description('Shared search service.')
param searchServiceName string
@description('Shared container registry.')
param registryName string
@description('Principal of the API identity.')
param apiPrincipalId string
@description('Principal of the web identity.')
param webPrincipalId string
@description('Principal of the jobs identity.')
param jobsPrincipalId string

var foundryUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var searchIndexDataReader = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var searchServiceContributor = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var searchIndexDataContributor = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var projectGrants = [{ principalId: apiPrincipalId, role: foundryUser }, { principalId: jobsPrincipalId, role: foundryUser }]
var searchGrants = [
  { principalId: apiPrincipalId, role: searchIndexDataReader }
  { principalId: jobsPrincipalId, role: searchServiceContributor }, { principalId: jobsPrincipalId, role: searchIndexDataContributor }
]
var registryGrants = [{ principalId: apiPrincipalId, role: acrPull }, { principalId: webPrincipalId, role: acrPull }, { principalId: jobsPrincipalId, role: acrPull }]

resource foundry 'Microsoft.CognitiveServices/accounts@2026-07-01' existing = {
  name: foundryAccountName
  resource project 'projects' existing = { name: foundryProjectName }
}
resource search 'Microsoft.Search/searchServices@2025-05-01' existing = { name: searchServiceName }
resource registry 'Microsoft.ContainerRegistry/registries@2025-11-01' existing = { name: registryName }

resource projectAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for grant in projectGrants: {
  name: guid(foundry::project.id, grant.principalId, grant.role)
  scope: foundry::project
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', grant.role), principalId: grant.principalId, principalType: 'ServicePrincipal' }
}]

resource searchAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for grant in searchGrants: {
  name: guid(search.id, grant.principalId, grant.role)
  scope: search
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', grant.role), principalId: grant.principalId, principalType: 'ServicePrincipal' }
}]

resource registryAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for grant in registryGrants: {
  name: guid(registry.id, grant.principalId, grant.role)
  scope: registry
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', grant.role), principalId: grant.principalId, principalType: 'ServicePrincipal' }
}]

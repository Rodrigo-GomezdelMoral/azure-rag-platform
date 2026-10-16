@description('Region of the environment and the applications.')
param location string
@description('Tags applied to every taggable resource.')
param tags object
@description('Name suffix shared by the resources of this workload.')
param suffix string
@description('Log Analytics workspace that receives logs, through Azure Monitor rather than a workspace key.')
param logAnalyticsWorkspaceId string
@description('Action group that receives the alerts and the budget notifications.')
param actionGroupId string
@description('Registry the applications pull from, with AcrPull granted to each identity.')
param registryLoginServer string
@description('Image of the API and of both jobs.')
param apiImage string
@description('Image of the web frontend.')
param webImage string
@description('Client id of the API app registration; tokens must carry it as audience.')
param apiAppClientId string
@description('The api, web and jobs identities, in that order, as objects with id, clientId and principalId.')
param identities object[]
@description('Environment variables shared by the API and the jobs.')
param appSettings object
@description('Monthly budget of this resource group.')
param budgetAmount int
@description('First day of the month the budget starts.')
param budgetStartDate string

var monitoringMetricsPublisher = '3913510d-42f4-4e42-8a64-420c390055eb'
var issuer = '${environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
var telemetry = [{ name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }]
var sharedEnv = concat(map(items(appSettings), item => { name: item.key, value: item.value }), telemetry)
var registry = { server: registryLoginServer }
var jobs = [
  { name: 'caj-ragindexer', trigger: 'Manual', command: ['python', '-m', 'ops.index'] }
  { name: 'caj-rageval', trigger: 'Schedule', command: ['python', '-m', 'eval.run', '--suite', 'full'] }
]

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${suffix}'
  location: location
  tags: tags
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: logAnalyticsWorkspaceId, DisableLocalAuth: true, IngestionMode: 'LogAnalytics' }
}

resource telemetryAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for identity in identities: {
  name: guid(insights.id, identity.principalId, monitoringMetricsPublisher)
  scope: insights
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringMetricsPublisher), principalId: identity.principalId, principalType: 'ServicePrincipal' }
}]

resource env 'Microsoft.App/managedEnvironments@2026-07-01' = {
  name: 'cae-${suffix}'
  location: location
  tags: tags
  properties: { appLogsConfiguration: { destination: 'azure-monitor' } }
}

resource envDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-shared-workspace'
  scope: env
  properties: { workspaceId: logAnalyticsWorkspaceId, logs: [{ categoryGroup: 'allLogs', enabled: true }] }
}

resource api 'Microsoft.App/containerApps@2026-07-01' = {
  name: 'ca-ragapi'
  location: location
  tags: union(tags, { 'azd-service-name': 'api' })
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identities[0].id}': {} } }
  properties: {
    environmentId: env.id
    configuration: { activeRevisionsMode: 'Multiple', ingress: { external: true, targetPort: 8000, transport: 'http' }, registries: [union(registry, { identity: identities[0].id })] }
    template: {
      containers: [{ name: 'api', image: apiImage, resources: { cpu: json('0.5'), memory: '1Gi' }, env: concat(sharedEnv, [{ name: 'AZURE_CLIENT_ID', value: identities[0].clientId }]) }]
      scale: { minReplicas: 0, maxReplicas: 3 }
    }
  }
  resource auth 'authConfigs' = {
    name: 'current'
    properties: {
      platform: { enabled: true }
      globalValidation: { unauthenticatedClientAction: 'Return401', excludedPaths: ['/healthz'] }
      identityProviders: { azureActiveDirectory: { enabled: true, registration: { openIdIssuer: issuer, clientId: apiAppClientId }, validation: { allowedAudiences: ['api://${apiAppClientId}', apiAppClientId] } } }
      httpSettings: { requireHttps: true }
    }
  }
}

resource web 'Microsoft.App/containerApps@2026-07-01' = {
  name: 'ca-ragweb'
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identities[1].id}': {} } }
  properties: {
    environmentId: env.id
    configuration: { ingress: { external: true, targetPort: 8080, transport: 'http' }, registries: [union(registry, { identity: identities[1].id })] }
    template: {
      containers: [{
        name: 'web', image: webImage, resources: { cpu: json('0.25'), memory: '0.5Gi' }
        env: [
          { name: 'API_BASE_URL', value: 'https://${api.properties.configuration.ingress.fqdn}' }, { name: 'API_AUDIENCE', value: 'api://${apiAppClientId}' }
          { name: 'AZURE_CLIENT_ID', value: identities[1].clientId }, { name: 'PORT', value: '8080' }
        ]
      }]
      scale: { minReplicas: 0, maxReplicas: 2 }
    }
  }
}

resource job 'Microsoft.App/jobs@2026-07-01' = [for item in jobs: {
  name: item.name
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identities[2].id}': {} } }
  properties: {
    environmentId: env.id
    configuration: {
      triggerType: item.trigger, replicaTimeout: 7200, replicaRetryLimit: 0, registries: [union(registry, { identity: identities[2].id })]
      manualTriggerConfig: item.trigger == 'Manual' ? { parallelism: 1, replicaCompletionCount: 1 } : null
      scheduleTriggerConfig: item.trigger == 'Schedule' ? { cronExpression: '0 6 * * 1', parallelism: 1, replicaCompletionCount: 1 } : null
    }
    template: {
      containers: [{ name: 'job', image: apiImage, command: item.command, resources: { cpu: json('1'), memory: '2Gi' }, env: concat(sharedEnv, [{ name: 'AZURE_CLIENT_ID', value: identities[2].clientId }]) }]
    }
  }
}]

resource serverErrors 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-ragapi-5xx'
  location: 'global'
  tags: tags
  properties: {
    severity: 2, enabled: true, scopes: [api.id], evaluationFrequency: 'PT5M', windowSize: 'PT15M', actions: [{ actionGroupId: actionGroupId }]
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [{ name: 'server-errors', metricNamespace: 'Microsoft.App/containerApps', metricName: 'Requests', operator: 'GreaterThan', threshold: 5, timeAggregation: 'Total', dimensions: [{ name: 'statusCodeCategory', operator: 'Include', values: ['5xx'] }] }]
    }
  }
}

resource budget 'Microsoft.Consumption/budgets@2026-06-01' = {
  name: 'budget-${suffix}'
  properties: {
    category: 'Cost', amount: budgetAmount, timeGrain: 'Monthly', timePeriod: { startDate: budgetStartDate }
    notifications: {
      'actual-80-percent': { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 80, thresholdType: 'Actual', contactEmails: [], contactGroups: [actionGroupId] }
      'forecast-100-percent': { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 100, thresholdType: 'Forecasted', contactEmails: [], contactGroups: [actionGroupId] }
    }
  }
}

@description('Public URL of the API.')
output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
@description('Public URL of the web frontend.')
output webUrl string = 'https://${web.properties.configuration.ingress.fqdn}'

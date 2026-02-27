// ---------------------------------------------------------------------------
// Prior Auth MAF — Main Bicep template
// Deploys: Resource Group, Container Registry, Container Apps Environment,
//          Backend + Frontend Container Apps, Log Analytics, App Insights
// ---------------------------------------------------------------------------

targetScope = 'subscription'

// ── Parameters ──────────────────────────────────────────────────────────────

@minLength(1)
@maxLength(64)
@description('Name of the environment (e.g., dev, staging, prod)')
param environmentName string

@minLength(1)
@description('Primary location for all resources')
param location string

@description('Azure AI Foundry API key for Claude model access')
@secure()
param azureFoundryApiKey string = ''

@description('Azure AI Foundry endpoint URL')
param azureFoundryEndpoint string = ''

@description('Application Insights connection string (optional)')
param appInsightsConnectionString string = ''

// ── Variables ───────────────────────────────────────────────────────────────

var abbrs = loadJsonContent('./abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = {
  'azd-env-name': environmentName
  'solution-accelerator': 'prior-auth-maf'
}

// ── Resource Group ──────────────────────────────────────────────────────────

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: '${abbrs.resourcesResourceGroups}${environmentName}'
  location: location
  tags: tags
}

// ── Container Registry ──────────────────────────────────────────────────────

module containerRegistry './modules/container-registry.bicep' = {
  name: 'container-registry'
  scope: rg
  params: {
    name: '${abbrs.containerRegistryRegistries}${resourceToken}'
    location: location
    tags: tags
  }
}

// ── Log Analytics + Application Insights ────────────────────────────────────

module monitoring './modules/monitoring.bicep' = {
  name: 'monitoring'
  scope: rg
  params: {
    logAnalyticsName: '${abbrs.operationalInsightsWorkspaces}${resourceToken}'
    appInsightsName: '${abbrs.insightsComponents}${resourceToken}'
    location: location
    tags: tags
  }
}

// ── Container Apps Environment ──────────────────────────────────────────────

module containerAppsEnv './modules/container-apps-env.bicep' = {
  name: 'container-apps-env'
  scope: rg
  params: {
    name: '${abbrs.appManagedEnvironments}${resourceToken}'
    location: location
    tags: tags
    logAnalyticsWorkspaceId: monitoring.outputs.logAnalyticsWorkspaceId
  }
}

// ── Backend Container App ───────────────────────────────────────────────────

module backend './modules/container-app.bicep' = {
  name: 'backend'
  scope: rg
  params: {
    name: '${abbrs.appContainerApps}backend-${resourceToken}'
    location: location
    tags: union(tags, { 'azd-service-name': 'backend' })
    containerAppsEnvironmentId: containerAppsEnv.outputs.environmentId
    containerRegistryName: containerRegistry.outputs.name
    containerRegistryLoginServer: containerRegistry.outputs.loginServer
    imageName: 'backend'
    targetPort: 8000
    env: [
      { name: 'CLAUDE_CODE_USE_FOUNDRY', value: 'true' }
      { name: 'ANTHROPIC_FOUNDRY_API_KEY', secretRef: 'foundry-api-key' }
      { name: 'ANTHROPIC_FOUNDRY_BASE_URL', value: azureFoundryEndpoint }
      { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString != '' ? appInsightsConnectionString : monitoring.outputs.appInsightsConnectionString }
      { name: 'FRONTEND_ORIGIN', value: 'https://${abbrs.appContainerApps}frontend-${resourceToken}.${containerAppsEnv.outputs.defaultDomain}' }
    ]
    secrets: [
      { name: 'foundry-api-key', value: azureFoundryApiKey }
    ]
    healthCheckPath: '/health'
  }
}

// ── Frontend Container App ──────────────────────────────────────────────────

module frontend './modules/container-app.bicep' = {
  name: 'frontend'
  scope: rg
  params: {
    name: '${abbrs.appContainerApps}frontend-${resourceToken}'
    location: location
    tags: union(tags, { 'azd-service-name': 'frontend' })
    containerAppsEnvironmentId: containerAppsEnv.outputs.environmentId
    containerRegistryName: containerRegistry.outputs.name
    containerRegistryLoginServer: containerRegistry.outputs.loginServer
    imageName: 'frontend'
    targetPort: 80
    env: []
    secrets: []
    healthCheckPath: '/'
  }
}

// ── Outputs ─────────────────────────────────────────────────────────────────

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = containerRegistry.outputs.loginServer
output frontendUrl string = frontend.outputs.fqdn
output backendUrl string = backend.outputs.fqdn

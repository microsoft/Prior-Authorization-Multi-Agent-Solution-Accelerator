// ---------------------------------------------------------------------------
// Prior Auth MAF — Main Bicep template
// Deploys: Resource Group, Microsoft Foundry (Resource + Project), Container Registry,
//          Container Apps Environment, Backend + 4 Agent + Frontend Container Apps,
//          Log Analytics, App Insights, Role Assignments (Cognitive Services OpenAI User)
// ---------------------------------------------------------------------------

targetScope = 'subscription'

// ── Parameters ──────────────────────────────────────────────────────────────

@minLength(1)
@maxLength(64)
@description('Name of the environment (e.g., dev, staging, prod)')
param environmentName string

@minLength(1)
@description('Primary location for all resources. Must be East US 2 or Sweden Central for gpt-4o availability.')
@allowed([
  'eastus2'
  'swedencentral'
])
param location string

@description('Azure OpenAI deployment name to use across all agent containers (e.g., gpt-4o)')
param azureOpenAIDeploymentName string = 'gpt-4o'

@description('Whether container images have been built to ACR (set automatically by postprovision hook)')
param imagesBuilt string = ''

// ── MCP Server URL parameters (all have production defaults) ────────────────

@description('ICD-10 diagnosis code validation MCP server URL')
param mcpIcd10CodesUrl string = 'https://mcp.deepsense.ai/icd10_codes/mcp'

@description('PubMed biomedical literature search MCP server URL')
param mcpPubmedUrl string = 'https://pubmed.mcp.claude.com/mcp'

@description('ClinicalTrials.gov search MCP server URL')
param mcpClinicalTrialsUrl string = 'https://mcp.deepsense.ai/clinical_trials/mcp'

@description('NPI Registry provider verification MCP server URL')
param mcpNpiRegistryUrl string = 'https://mcp.deepsense.ai/npi_registry/mcp'

@description('CMS Coverage Medicare LCD/NCD policy lookup MCP server URL')
param mcpCmsCoverageUrl string = 'https://mcp.deepsense.ai/cms_coverage/mcp'

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

// ── Microsoft Foundry (Resource + Project) ──────────────────────────────────

module aiFoundry './modules/ai-foundry.bicep' = {
  name: 'ai-foundry'
  scope: rg
  params: {
    name: '${abbrs.aiFoundry}${resourceToken}'
    location: location
    tags: tags
    appInsightsInstrumentationKey: monitoring.outputs.appInsightsInstrumentationKey
    appInsightsResourceId: monitoring.outputs.appInsightsResourceId
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

// ── Backend Container App ────────────────────────────────────────────────────────

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
    useAcrImage: imagesBuilt == 'true'
    cpu: '1'
    memory: '2Gi'
    minReplicas: 1
    env: [
      // Hosted agent endpoints — point to the 4 agent Container Apps
      { name: 'HOSTED_AGENT_CLINICAL_URL', value: 'https://${agentClinical.outputs.fqdn}' }
      { name: 'HOSTED_AGENT_COVERAGE_URL', value: 'https://${agentCoverage.outputs.fqdn}' }
      { name: 'HOSTED_AGENT_COMPLIANCE_URL', value: 'https://${agentCompliance.outputs.fqdn}' }
      { name: 'HOSTED_AGENT_SYNTHESIS_URL', value: 'https://${agentSynthesis.outputs.fqdn}' }
      { name: 'HOSTED_AGENT_TIMEOUT_SECONDS', value: '180' }
      { name: 'APPLICATION_INSIGHTS_CONNECTION_STRING', value: monitoring.outputs.appInsightsConnectionString }
      { name: 'FRONTEND_ORIGIN', value: 'https://${abbrs.appContainerApps}frontend-${resourceToken}.${containerAppsEnv.outputs.defaultDomain}' }
    ]
    secrets: []
    healthCheckPath: '/health'
  }
}
// ── Clinical Reviewer Agent Container App ─────────────────────────────

module agentClinical './modules/container-app.bicep' = {
  name: 'agent-clinical'
  scope: rg
  params: {
    name: '${abbrs.appContainerApps}agent-clinical-${resourceToken}'
    location: location
    tags: union(tags, { 'azd-service-name': 'agent-clinical' })
    containerAppsEnvironmentId: containerAppsEnv.outputs.environmentId
    containerRegistryName: containerRegistry.outputs.name
    containerRegistryLoginServer: containerRegistry.outputs.loginServer
    imageName: 'agent-clinical'
    targetPort: 8000
    useAcrImage: imagesBuilt == 'true'
    cpu: '1'
    memory: '2Gi'
    minReplicas: 1
    env: [
      { name: 'AZURE_AI_PROJECT_ENDPOINT', value: aiFoundry.outputs.endpoint }
      { name: 'AZURE_OPENAI_DEPLOYMENT_NAME', value: azureOpenAIDeploymentName }
      { name: 'MCP_ICD10_CODES', value: mcpIcd10CodesUrl }
      { name: 'MCP_PUBMED', value: mcpPubmedUrl }
      { name: 'MCP_CLINICAL_TRIALS', value: mcpClinicalTrialsUrl }
      { name: 'APPLICATION_INSIGHTS_CONNECTION_STRING', value: monitoring.outputs.appInsightsConnectionString }
    ]
    secrets: []
    healthCheckPath: '/health'
  }
}

// ── Coverage Assessment Agent Container App ───────────────────────────

module agentCoverage './modules/container-app.bicep' = {
  name: 'agent-coverage'
  scope: rg
  params: {
    name: '${abbrs.appContainerApps}agent-coverage-${resourceToken}'
    location: location
    tags: union(tags, { 'azd-service-name': 'agent-coverage' })
    containerAppsEnvironmentId: containerAppsEnv.outputs.environmentId
    containerRegistryName: containerRegistry.outputs.name
    containerRegistryLoginServer: containerRegistry.outputs.loginServer
    imageName: 'agent-coverage'
    targetPort: 8000
    useAcrImage: imagesBuilt == 'true'
    cpu: '1'
    memory: '2Gi'
    minReplicas: 1
    env: [
      { name: 'AZURE_AI_PROJECT_ENDPOINT', value: aiFoundry.outputs.endpoint }
      { name: 'AZURE_OPENAI_DEPLOYMENT_NAME', value: azureOpenAIDeploymentName }
      { name: 'MCP_NPI_REGISTRY', value: mcpNpiRegistryUrl }
      { name: 'MCP_CMS_COVERAGE', value: mcpCmsCoverageUrl }
      { name: 'APPLICATION_INSIGHTS_CONNECTION_STRING', value: monitoring.outputs.appInsightsConnectionString }
    ]
    secrets: []
    healthCheckPath: '/health'
  }
}

// ── Compliance Validation Agent Container App ─────────────────────────

module agentCompliance './modules/container-app.bicep' = {
  name: 'agent-compliance'
  scope: rg
  params: {
    name: '${abbrs.appContainerApps}agent-compliance-${resourceToken}'
    location: location
    tags: union(tags, { 'azd-service-name': 'agent-compliance' })
    containerAppsEnvironmentId: containerAppsEnv.outputs.environmentId
    containerRegistryName: containerRegistry.outputs.name
    containerRegistryLoginServer: containerRegistry.outputs.loginServer
    imageName: 'agent-compliance'
    targetPort: 8000
    useAcrImage: imagesBuilt == 'true'
    cpu: '0.5'
    memory: '1Gi'
    minReplicas: 1
    env: [
      { name: 'AZURE_AI_PROJECT_ENDPOINT', value: aiFoundry.outputs.endpoint }
      { name: 'AZURE_OPENAI_DEPLOYMENT_NAME', value: azureOpenAIDeploymentName }
      { name: 'APPLICATION_INSIGHTS_CONNECTION_STRING', value: monitoring.outputs.appInsightsConnectionString }
    ]
    secrets: []
    healthCheckPath: '/health'
  }
}

// ── Synthesis Decision Agent Container App ───────────────────────────

module agentSynthesis './modules/container-app.bicep' = {
  name: 'agent-synthesis'
  scope: rg
  params: {
    name: '${abbrs.appContainerApps}agent-synthesis-${resourceToken}'
    location: location
    tags: union(tags, { 'azd-service-name': 'agent-synthesis' })
    containerAppsEnvironmentId: containerAppsEnv.outputs.environmentId
    containerRegistryName: containerRegistry.outputs.name
    containerRegistryLoginServer: containerRegistry.outputs.loginServer
    imageName: 'agent-synthesis'
    targetPort: 8000
    useAcrImage: imagesBuilt == 'true'
    cpu: '1'
    memory: '2Gi'
    minReplicas: 1
    env: [
      { name: 'AZURE_AI_PROJECT_ENDPOINT', value: aiFoundry.outputs.endpoint }
      { name: 'AZURE_OPENAI_DEPLOYMENT_NAME', value: azureOpenAIDeploymentName }
      { name: 'APPLICATION_INSIGHTS_CONNECTION_STRING', value: monitoring.outputs.appInsightsConnectionString }
    ]
    secrets: []
    healthCheckPath: '/health'
  }
}

// ── Role Assignments — agent identities → Foundry OpenAI access ───────────

module agentRoleAssignments './modules/role-assignments.bicep' = {
  name: 'agent-role-assignments'
  scope: rg
  params: {
    foundryAccountName: aiFoundry.outputs.accountName
    principalIds: [
      agentClinical.outputs.principalId
      agentCoverage.outputs.principalId
      agentCompliance.outputs.principalId
      agentSynthesis.outputs.principalId
    ]
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
    useAcrImage: imagesBuilt == 'true'
    minReplicas: 1
    env: [
      { name: 'BACKEND_URL', value: 'https://${abbrs.appContainerApps}backend-${resourceToken}.${containerAppsEnv.outputs.defaultDomain}' }
    ]
    secrets: []
    healthCheckPath: '/'
  }
}

// ── Outputs ─────────────────────────────────────────────────────────────────

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = containerRegistry.outputs.loginServer
output AI_FOUNDRY_ACCOUNT_NAME string = aiFoundry.outputs.accountName
output AI_FOUNDRY_PROJECT_NAME string = aiFoundry.outputs.projectName
output AI_FOUNDRY_ENDPOINT string = aiFoundry.outputs.endpoint
output AI_FOUNDRY_PORTAL_URL string = aiFoundry.outputs.portalUrl
output AGENT_CLINICAL_CONTAINER_APP_NAME string = agentClinical.outputs.name
output AGENT_COVERAGE_CONTAINER_APP_NAME string = agentCoverage.outputs.name
output AGENT_COMPLIANCE_CONTAINER_APP_NAME string = agentCompliance.outputs.name
output AGENT_SYNTHESIS_CONTAINER_APP_NAME string = agentSynthesis.outputs.name
output BACKEND_CONTAINER_APP_NAME string = backend.outputs.name
output FRONTEND_CONTAINER_APP_NAME string = frontend.outputs.name
output frontendUrl string = frontend.outputs.fqdn
output backendUrl string = backend.outputs.fqdn

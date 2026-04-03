// ---------------------------------------------------------------------------
// Microsoft Foundry — Resource + Project (new architecture)
// Creates the Foundry resource (CognitiveServices/accounts) and a project
// for deploying Azure OpenAI models (e.g., gpt-5.4) from the model catalog.
//
// Reference: https://learn.microsoft.com/en-us/azure/foundry/how-to/create-resource-template
// ---------------------------------------------------------------------------

@description('Base name for Foundry resources')
param name string

@description('Location for all resources')
param location string

@description('Tags for all resources')
param tags object = {}

@description('Application Insights instrumentation key — used to link this Foundry project to App Insights so the Foundry portal Traces view works')
@secure()
param appInsightsInstrumentationKey string

@description('Application Insights resource ID — the target resource for the AppInsights connection')
param appInsightsResourceId string

@description('Name for the model deployment (used in API calls, e.g. gpt-5.4)')
param deploymentName string = 'gpt-5.4'

@description('Model version to deploy.')
param modelVersion string = '2026-03-05'

@description('Deployment SKU: DataZoneStandard (data residency within geographic zone) or GlobalStandard (no data residency, wider region availability).')
@allowed(['DataZoneStandard', 'GlobalStandard'])
param deploymentSkuName string = 'GlobalStandard'

@description('Capacity in thousands of tokens per minute (default: 100 = 100K TPM)')
param deploymentCapacityK int = 100

// ── Microsoft Foundry Resource ──────────────────────────────────────────────

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: 'foundry-${name}'
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: 'S0'
  }
  kind: 'AIServices'
  properties: {
    allowProjectManagement: true
    customSubDomainName: 'foundry-${name}'
    disableLocalAuth: false
    publicNetworkAccess: 'Enabled'
  }
}

// ── Microsoft Foundry Project ───────────────────────────────────────────────

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  name: 'proj-${name}'
  parent: foundryAccount
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
}

// ── App Insights Connection — links Foundry Traces view to App Insights ─────
// category 'AppInsights' + authType 'ApiKey' is the connection pattern that
// the Foundry portal uses when you click "Connect" under Agents → Traces.
// Without this, the Foundry portal Traces tab shows nothing even though agent
// spans are correctly exported to App Insights by client-side instrumentation.

resource appInsightsConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-12-01' = {
  name: 'app-insights'
  parent: foundryProject
  properties: {
    category: 'AppInsights'
    target: appInsightsResourceId
    authType: 'ApiKey'
    credentials: {
      key: appInsightsInstrumentationKey
    }
  }
}
// ── gpt-5.4 Model Deployment ─────────────────────────────────────────────
// GlobalStandard  = no data residency guarantee, available in more regions.
// DataZoneStandard = data residency bounded to a geographic zone (US/EU),
//                    available in East US 2 only (NOT Sweden Central).
// Deployment SKU is selected by the user during azd up.
resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  name: deploymentName
  parent: foundryAccount
  sku: {
    name: deploymentSkuName
    capacity: deploymentCapacityK
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5.4'
      version: modelVersion
    }
    versionUpgradeOption: 'OnceCurrentVersionExpired'
  }
  dependsOn: [capabilityHost]
}
// ── Capability Host — required for Foundry Hosted Agents ─────────────────────
// Enables Foundry Agent Service to provision and manage ACA containers for
// hosted agents deployed to this Foundry account. Must be created once per
// Foundry account.
// Note: enablePublicHostingEnvironment is not supported in stable API versions.
// Using 2025-06-01 without the property provisions the capability host correctly
// for public (non-VNet) deployments.
resource capabilityHost 'Microsoft.CognitiveServices/accounts/capabilityHosts@2025-06-01' = {
  name: 'accountcaphost'
  parent: foundryAccount
  properties: {
    capabilityHostKind: 'Agents'
  }
}

// ── Outputs ─────────────────────────────────────────────────────────────────

output accountName string = foundryAccount.name
output projectName string = foundryProject.name
output accountId string = foundryAccount.id
output projectId string = foundryProject.id
output endpoint string = foundryAccount.properties.endpoint
output portalUrl string = 'https://ai.azure.com/manage/project?wsid=${foundryProject.id}'
output deploymentName string = modelDeployment.name

// Project endpoint: used by the backend orchestrator to invoke Foundry Hosted
// Agents via the Responses API with agent_reference routing.
// Format: https://<resource>.services.ai.azure.com/api/projects/<project>
output projectEndpoint string = '${foundryAccount.properties.endpoint}api/projects/${foundryProject.name}'

// Project system-assigned managed identity — needs AcrPull on ACR so Foundry
// Agent Service can pull the 4 agent container images.
output projectPrincipalId string = foundryProject.identity.principalId

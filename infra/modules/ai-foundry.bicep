// ---------------------------------------------------------------------------
// Microsoft Foundry — Resource + Project (new architecture)
// Creates the Foundry resource (CognitiveServices/accounts) and a project
// for deploying Claude models from the model catalog.
//
// Reference: https://learn.microsoft.com/en-us/azure/foundry/how-to/create-resource-template
// ---------------------------------------------------------------------------

@description('Base name for Foundry resources')
param name string

@description('Location for all resources')
param location string

@description('Tags for all resources')
param tags object = {}

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

// ── Outputs ─────────────────────────────────────────────────────────────────

output accountName string = foundryAccount.name
output projectName string = foundryProject.name
output accountId string = foundryAccount.id
output projectId string = foundryProject.id
output endpoint string = foundryAccount.properties.endpoint
output portalUrl string = 'https://ai.azure.com/manage/project?wsid=${foundryProject.id}'

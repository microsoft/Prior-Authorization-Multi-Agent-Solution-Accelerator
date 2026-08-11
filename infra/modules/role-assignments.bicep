// ---------------------------------------------------------------------------
// Role Assignments for Prior Auth MAF (Foundry Hosted Agents deployment)
//
// 1. Backend ACA identity → Cognitive Services OpenAI User on Foundry account
//    Allows the FastAPI orchestrator to call the Foundry Responses API with
//    per-agent dedicated endpoints to invoke Foundry Hosted Agents.
//
// 2. Foundry project managed identity → AcrPull on Container Registry
//    Allows Foundry Agent Service to pull the 4 agent container images from
//    ACR when provisioning Foundry Hosted Agent deployments.
//
// Note: The deployer's Foundry User and Foundry Project Manager roles
// (needed to register and deploy hosted agents) are assigned via
// `az role assignment create` in the postprovision hook instead of Bicep,
// because `az role assignment create` is idempotent and avoids
// RoleAssignmentExists conflicts when the role was previously granted manually.
// Project Manager is required by the refreshed Hosted Agents preview
// (Apr 2026) for the create_version() data action; Foundry User alone is
// not sufficient. See:
// https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent#required-permissions
//
// Roles are referenced by role definition ID throughout: the built-in roles
// were renamed (Azure AI User -> Foundry User, Azure AI Project Manager ->
// Foundry Project Manager) and display-name lookups break across the rename.
// ---------------------------------------------------------------------------

@description('Name of the existing Foundry (CognitiveServices) account')
param foundryAccountName string

@description('Principal ID of the backend Container App system-assigned managed identity')
param backendPrincipalId string

@description('Principal ID of the frontend Container App system-assigned managed identity')
param frontendPrincipalId string

@description('Name of the Azure Container Registry (for AcrPull grant to Foundry project)')
param containerRegistryName string

@description('Principal ID of the Foundry project system-assigned managed identity')
param foundryProjectPrincipalId string

@description('Principal ID of the Foundry account system-assigned managed identity')
param foundryAccountPrincipalId string

// Cognitive Services OpenAI User — allows calling Azure OpenAI + Foundry APIs
var cognitiveServicesOpenAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

// Cognitive Services OpenAI Contributor — allows hosted agents to call models
var cognitiveServicesOpenAIContributorRoleId = 'a001fd3d-188f-4b5d-821b-7da978bf7442'

// Foundry User (formerly Azure AI User) — allows hosted agents to use Foundry Agent Service data actions
var azureAIUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'

// AcrPull — allows pulling container images from Azure Container Registry
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: containerRegistryName
}

// 1. Backend → CognitiveServicesOpenAIUser on Foundry account
resource backendFoundryRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryAccount.id, backendPrincipalId, cognitiveServicesOpenAIUserRoleId)
  scope: foundryAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: backendPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// 2. Foundry project identity → AcrPull on Container Registry
resource foundryProjectAcrPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(containerRegistry.id, foundryProjectPrincipalId, acrPullRoleId)
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: foundryProjectPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// 3. Foundry project identity → Cognitive Services OpenAI Contributor on Foundry account
//    Allows hosted agent containers to call gpt-5.4 via the Responses API
resource foundryProjectOpenAIContributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryAccount.id, foundryProjectPrincipalId, cognitiveServicesOpenAIContributorRoleId)
  scope: foundryAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIContributorRoleId)
    principalId: foundryProjectPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// 4. Foundry project identity → Foundry User on Foundry account
//    Allows hosted agent containers to use Foundry Agent Service data actions
resource foundryProjectAIUserRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryAccount.id, foundryProjectPrincipalId, azureAIUserRoleId)
  scope: foundryAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIUserRoleId)
    principalId: foundryProjectPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// 5. Backend Container App identity → AcrPull on Container Registry
//    Allows the backend ACA revision to pull its image from ACR using
//    system-assigned managed identity (no admin password needed).
resource backendAcrPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(containerRegistry.id, backendPrincipalId, acrPullRoleId)
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: backendPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// 6. Frontend Container App identity → AcrPull on Container Registry
//    Same as #5 but for the frontend (Next.js / nginx) container app.
resource frontendAcrPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(containerRegistry.id, frontendPrincipalId, acrPullRoleId)
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: frontendPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// 7. Foundry ACCOUNT identity → AcrPull on Container Registry
//    The hosted agents service uses the account MI (not the project MI) to
//    validate / pull agent images at `create_version()` time. Without this
//    grant, the API returns `(server_error) 500` with no detail. Discovered
//    empirically; the project-MI AcrPull grant in #2 is necessary but not
//    sufficient.
resource foundryAccountAcrPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(containerRegistry.id, foundryAccountPrincipalId, acrPullRoleId)
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: foundryAccountPrincipalId
    principalType: 'ServicePrincipal'
  }
}

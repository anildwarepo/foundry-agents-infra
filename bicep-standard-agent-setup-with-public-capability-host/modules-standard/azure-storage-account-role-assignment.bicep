param azureStorageName string
param projectPrincipalId string

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: azureStorageName
  scope: resourceGroup()
}

// Storage Account Contributor: 17d1049b-9a84-46fb-8f53-869881c3d3ab (Phase 3)
resource storageAccountContributor 'Microsoft.Authorization/roleDefinitions@2022-05-01-preview' existing = {
  name: '17d1049b-9a84-46fb-8f53-869881c3d3ab'
  scope: resourceGroup()
}

resource storageAccountContributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storageAccount
  name: guid(projectPrincipalId, storageAccountContributor.id, storageAccount.id)
  properties: {
    principalId: projectPrincipalId
    roleDefinitionId: storageAccountContributor.id
    principalType: 'ServicePrincipal'
  }
}

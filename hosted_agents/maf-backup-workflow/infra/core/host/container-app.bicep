targetScope = 'resourceGroup'

@description('Azure region for the Container Apps resources')
param location string = resourceGroup().location

@description('Tags applied to the Container Apps resources')
param tags object = {}

@description('Name of the Container App')
param containerAppName string

@description('Name of the Container Apps managed environment')
param managedEnvironmentName string

@description('Login server of the Azure Container Registry')
param containerRegistryEndpoint string

@description('Initial image used until azd deploy publishes the MCP image')
param bootstrapImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

resource managedEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: managedEnvironmentName
  location: location
  tags: tags
}

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: managedEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        allowInsecure: false
        targetPort: 3002
        transport: 'auto'
      }
      registries: [
        {
          server: containerRegistryEndpoint
          identity: 'system'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'data-discovery-mcp'
          image: bootstrapImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 3002
                scheme: 'HTTP'
              }
              initialDelaySeconds: 10
              periodSeconds: 30
              timeoutSeconds: 5
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: 3002
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 6
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
      }
    }
  }
}

var registryName = split(containerRegistryEndpoint, '.')[0]
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource registryPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, containerApp.id, 'acr-pull')
  scope: registry
  properties: {
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7f951dda-4ed3-4680-a7ca-43fe172d538d'
    )
  }
}

output containerAppName string = containerApp.name
output managedEnvironmentName string = managedEnvironment.name
output mcpEndpoint string = 'https://${containerApp.properties.configuration.ingress.fqdn}/mcp'

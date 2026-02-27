// Container App (used for both backend and frontend)
param name string
param location string
param tags object = {}
param containerAppsEnvironmentId string
param containerRegistryName string
param containerRegistryLoginServer string
param imageName string
param targetPort int
param env array = []
param secrets array = []
param healthCheckPath string = ''

@description('CPU cores allocated to each container instance')
param cpu string = '0.5'

@description('Memory allocated to each container instance')
param memory string = '1Gi'

@description('Minimum number of replicas')
param minReplicas int = 0

@description('Maximum number of replicas')
param maxReplicas int = 3

// Get registry credentials
resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: containerRegistryName
}

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    managedEnvironmentId: containerAppsEnvironmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: targetPort
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: containerRegistryLoginServer
          username: containerRegistry.listCredentials().username
          passwordSecretRef: 'registry-password'
        }
      ]
      secrets: union(
        [
          {
            name: 'registry-password'
            value: containerRegistry.listCredentials().passwords[0].value
          }
        ],
        secrets
      )
    }
    template: {
      containers: [
        {
          name: imageName
          image: '${containerRegistryLoginServer}/${imageName}:latest'
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: env
          probes: healthCheckPath != '' ? [
            {
              type: 'Liveness'
              httpGet: {
                path: healthCheckPath
                port: targetPort
              }
              periodSeconds: 30
              failureThreshold: 3
              initialDelaySeconds: 15
            }
          ] : []
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '50'
              }
            }
          }
        ]
      }
    }
  }
}

output fqdn string = containerApp.properties.configuration.ingress.fqdn
output name string = containerApp.name
output id string = containerApp.id

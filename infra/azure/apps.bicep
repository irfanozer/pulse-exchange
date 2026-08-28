targetScope = 'resourceGroup'

metadata name = 'PulseExchange Container Apps'
metadata description = 'Warm public web entry point, internal API, single matching service, seed job, and bounded daily demo reset.'

param location string = resourceGroup().location

@minLength(3)
@maxLength(15)
param namePrefix string = 'pulseexchange'

@minLength(2)
@maxLength(7)
param environmentName string = 'prod'

@description('Name of the Container Apps environment created by foundation.bicep.')
param containerAppsEnvironmentName string = 'cae-${toLower(namePrefix)}-${toLower(environmentName)}'

@minLength(1)
@description('Immutable public GHCR frontend image tag or digest.')
param frontendImage string

@minLength(1)
@description('Immutable public GHCR backend image tag or digest.')
param backendImage string

@secure()
@minLength(1)
@description('Complete SQLAlchemy asyncpg database URL, including ssl=require.')
param databaseUrl string

@description('Optional custom hostname for the public web app. Supply it with its certificate ID.')
param webCustomDomainName string = ''

@description('Optional Azure managed-certificate resource ID for webCustomDomainName.')
param webCustomDomainCertificateId string = ''

@minValue(1)
param webMinReplicas int = 1

@minValue(1)
param webMaxReplicas int = 1

@minValue(1)
param apiMinReplicas int = 1

@minValue(1)
param apiMaxReplicas int = 1

@minValue(1)
param processorMinReplicas int = 1

@minValue(1)
param processorMaxReplicas int = 1

@minValue(100)
@description('Hard durable command ceiling between scheduled resets.')
param maxTotalCommands int = 10000

@description('UTC cron expression for resetting and reseeding the disposable public demo.')
param maintenanceCron string = '0 4 * * *'

@description('Optional additional resource tags.')
param tags object = {}

var normalizedPrefix = toLower(namePrefix)
var normalizedEnvironment = toLower(environmentName)
var webAppName = '${normalizedPrefix}-web-${normalizedEnvironment}'
var apiAppName = '${normalizedPrefix}-api-${normalizedEnvironment}'
var processorAppName = '${normalizedPrefix}-processor-${normalizedEnvironment}'
var seedJobName = '${normalizedPrefix}-seed-${normalizedEnvironment}'
var maintenanceJobName = '${normalizedPrefix}-maintenance-${normalizedEnvironment}'
var apiInternalOrigin = 'http://${apiAppName}'
var webCustomDomains = !empty(webCustomDomainName) && !empty(webCustomDomainCertificateId) ? [
  {
    name: webCustomDomainName
    bindingType: 'SniEnabled'
    certificateId: webCustomDomainCertificateId
  }
] : []
var resourceTags = union({
  application: 'PulseExchange'
  environment: normalizedEnvironment
  managedBy: 'Bicep'
  workload: 'public-demo'
}, tags)

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2026-01-01' existing = {
  name: containerAppsEnvironmentName
}

var generatedWebOrigin = 'https://${webAppName}.${containerAppsEnvironment.properties.defaultDomain}'
var browserOrigins = empty(webCustomDomainName) ? [
  generatedWebOrigin
] : [
  generatedWebOrigin
  'https://${webCustomDomainName}'
]

resource processorApp 'Microsoft.App/containerApps@2026-01-01' = {
  name: processorAppName
  location: location
  tags: resourceTags
  properties: {
    configuration: {
      activeRevisionsMode: 'Single'
      maxInactiveRevisions: 3
      secrets: [
        {
          name: 'database-url'
          value: databaseUrl
        }
      ]
    }
    environmentId: containerAppsEnvironment.id
    template: {
      containers: [
        {
          name: 'processor'
          image: backendImage
          command: [
            'python'
          ]
          args: [
            '-m'
            'pulseexchange.worker'
          ]
          env: [
            {
              name: 'PULSEEXCHANGE_ENVIRONMENT'
              value: 'production'
            }
            {
              name: 'PULSEEXCHANGE_DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'PULSEEXCHANGE_DATABASE_POOL_SIZE'
              value: '3'
            }
            {
              name: 'PULSEEXCHANGE_DATABASE_MAX_OVERFLOW'
              value: '1'
            }
            {
              name: 'PULSEEXCHANGE_PROCESSOR_ENABLED'
              value: 'true'
            }
            {
              name: 'PULSEEXCHANGE_PROCESSOR_POLL_INTERVAL_MS'
              value: '250'
            }
            {
              name: 'PULSEEXCHANGE_PROCESSOR_HEARTBEAT_INTERVAL_SECONDS'
              value: '2'
            }
            {
              name: 'PULSEEXCHANGE_PROCESSOR_HEARTBEAT_STALE_SECONDS'
              value: '15'
            }
            {
              name: 'PULSEEXCHANGE_WORKER_HEALTH_PORT'
              value: '8002'
            }
          ]
          probes: [
            {
              type: 'Startup'
              httpGet: {
                path: '/ready'
                port: 8002
                scheme: 'HTTP'
              }
              initialDelaySeconds: 1
              periodSeconds: 2
              timeoutSeconds: 2
              failureThreshold: 30
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/live'
                port: 8002
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 15
              timeoutSeconds: 3
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/ready'
                port: 8002
                scheme: 'HTTP'
              }
              initialDelaySeconds: 3
              periodSeconds: 10
              timeoutSeconds: 3
              failureThreshold: 3
            }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
      scale: {
        minReplicas: processorMinReplicas
        maxReplicas: processorMaxReplicas
      }
      terminationGracePeriodSeconds: 60
    }
    workloadProfileName: 'Consumption'
  }
}

resource apiApp 'Microsoft.App/containerApps@2026-01-01' = {
  name: apiAppName
  location: location
  tags: resourceTags
  properties: {
    configuration: {
      activeRevisionsMode: 'Single'
      maxInactiveRevisions: 3
      ingress: {
        allowInsecure: false
        external: false
        targetPort: 8000
        transport: 'auto'
      }
      secrets: [
        {
          name: 'database-url'
          value: databaseUrl
        }
      ]
    }
    environmentId: containerAppsEnvironment.id
    template: {
      containers: [
        {
          name: 'api'
          image: backendImage
          command: [
            'uvicorn'
          ]
          args: [
            'pulseexchange.main:app'
            '--host'
            '0.0.0.0'
            '--port'
            '8000'
          ]
          env: [
            {
              name: 'PULSEEXCHANGE_ENVIRONMENT'
              value: 'production'
            }
            {
              name: 'PULSEEXCHANGE_DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'PULSEEXCHANGE_DATABASE_POOL_SIZE'
              value: '3'
            }
            {
              name: 'PULSEEXCHANGE_DATABASE_MAX_OVERFLOW'
              value: '2'
            }
            {
              name: 'PULSEEXCHANGE_PROCESSOR_ENABLED'
              value: 'false'
            }
            {
              name: 'PULSEEXCHANGE_EVENT_RELAY_ENABLED'
              value: 'true'
            }
            {
              name: 'PULSEEXCHANGE_PROCESSOR_HEARTBEAT_STALE_SECONDS'
              value: '15'
            }
            {
              name: 'PULSEEXCHANGE_REQUIRE_PROCESSOR_FOR_READINESS'
              value: 'true'
            }
            {
              name: 'PULSEEXCHANGE_WEBSOCKET_HEARTBEAT_SECONDS'
              value: '20'
            }
            {
              name: 'PULSEEXCHANGE_WEBSOCKET_REPLAY_LIMIT'
              value: '100'
            }
            {
              name: 'PULSEEXCHANGE_MAX_WEBSOCKET_CONNECTIONS'
              value: '100'
            }
            {
              name: 'PULSEEXCHANGE_MUTATION_RATE_LIMIT'
              value: '120'
            }
            {
              name: 'PULSEEXCHANGE_MUTATION_RATE_WINDOW_SECONDS'
              value: '60'
            }
            {
              name: 'PULSEEXCHANGE_TRUST_PROXY_HEADERS'
              value: 'false'
            }
            {
              name: 'PULSEEXCHANGE_MAX_REQUEST_BODY_BYTES'
              value: '16384'
            }
            {
              name: 'PULSEEXCHANGE_MAX_QUEUED_COMMANDS'
              value: '500'
            }
            {
              name: 'PULSEEXCHANGE_MAX_TOTAL_COMMANDS'
              value: string(maxTotalCommands)
            }
            {
              name: 'PULSEEXCHANGE_ALLOWED_HOSTS'
              value: string([apiAppName])
            }
            {
              name: 'PULSEEXCHANGE_CORS_ORIGINS'
              value: string(browserOrigins)
            }
            {
              name: 'PULSEEXCHANGE_WEBSOCKET_ORIGINS'
              value: string(browserOrigins)
            }
          ]
          probes: [
            {
              type: 'Startup'
              httpGet: {
                path: '/health/live'
                port: 8000
                scheme: 'HTTP'
                httpHeaders: [
                  {
                    name: 'Host'
                    value: apiAppName
                  }
                ]
              }
              initialDelaySeconds: 1
              periodSeconds: 2
              timeoutSeconds: 2
              failureThreshold: 30
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/health/live'
                port: 8000
                scheme: 'HTTP'
                httpHeaders: [
                  {
                    name: 'Host'
                    value: apiAppName
                  }
                ]
              }
              initialDelaySeconds: 5
              periodSeconds: 15
              timeoutSeconds: 3
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health/ready'
                port: 8000
                scheme: 'HTTP'
                httpHeaders: [
                  {
                    name: 'Host'
                    value: apiAppName
                  }
                ]
              }
              initialDelaySeconds: 3
              periodSeconds: 10
              timeoutSeconds: 3
              failureThreshold: 3
            }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]
      scale: {
        minReplicas: apiMinReplicas
        maxReplicas: apiMaxReplicas
        rules: [
          {
            name: 'api-http'
            http: {
              metadata: {
                concurrentRequests: '25'
              }
            }
          }
        ]
      }
      terminationGracePeriodSeconds: 30
    }
    workloadProfileName: 'Consumption'
  }
  dependsOn: [
    processorApp
  ]
}

resource webApp 'Microsoft.App/containerApps@2026-01-01' = {
  name: webAppName
  location: location
  tags: resourceTags
  properties: {
    configuration: {
      activeRevisionsMode: 'Single'
      maxInactiveRevisions: 3
      ingress: {
        allowInsecure: false
        customDomains: webCustomDomains
        external: true
        targetPort: 8080
        transport: 'auto'
      }
    }
    environmentId: containerAppsEnvironment.id
    template: {
      containers: [
        {
          name: 'web'
          image: frontendImage
          env: [
            {
              name: 'API_UPSTREAM'
              value: apiInternalOrigin
            }
          ]
          probes: [
            {
              type: 'Startup'
              httpGet: {
                path: '/healthz'
                port: 8080
                scheme: 'HTTP'
              }
              initialDelaySeconds: 1
              periodSeconds: 2
              timeoutSeconds: 2
              failureThreshold: 20
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/healthz'
                port: 8080
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 15
              timeoutSeconds: 3
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health/ready'
                port: 8080
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 3
            }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
      scale: {
        minReplicas: webMinReplicas
        maxReplicas: webMaxReplicas
        rules: [
          {
            name: 'web-http'
            http: {
              metadata: {
                concurrentRequests: '50'
              }
            }
          }
        ]
      }
      terminationGracePeriodSeconds: 30
    }
    workloadProfileName: 'Consumption'
  }
  dependsOn: [
    apiApp
  ]
}

resource seedJob 'Microsoft.App/jobs@2026-01-01' = {
  name: seedJobName
  location: location
  tags: resourceTags
  properties: {
    configuration: {
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      replicaRetryLimit: 1
      replicaTimeout: 600
      triggerType: 'Manual'
    }
    environmentId: containerAppsEnvironment.id
    template: {
      containers: [
        {
          name: 'seed'
          image: backendImage
          command: [
            'python'
          ]
          args: [
            '-m'
            'pulseexchange.seed'
          ]
          env: [
            {
              name: 'PULSEEXCHANGE_SEED_MARKET'
              value: 'true'
            }
            {
              name: 'PULSEEXCHANGE_SEED_BASE_URL'
              value: apiInternalOrigin
            }
            {
              name: 'PULSEEXCHANGE_SEED_STARTUP_TIMEOUT_SECONDS'
              value: '180'
            }
            {
              name: 'PULSEEXCHANGE_SEED_COMMAND_TIMEOUT_SECONDS'
              value: '30'
            }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
    }
    workloadProfileName: 'Consumption'
  }
  dependsOn: [
    apiApp
  ]
}

resource maintenanceJob 'Microsoft.App/jobs@2026-01-01' = {
  name: maintenanceJobName
  location: location
  tags: resourceTags
  properties: {
    configuration: {
      replicaRetryLimit: 1
      replicaTimeout: 900
      scheduleTriggerConfig: {
        cronExpression: maintenanceCron
        parallelism: 1
        replicaCompletionCount: 1
      }
      secrets: [
        {
          name: 'database-url'
          value: databaseUrl
        }
      ]
      triggerType: 'Schedule'
    }
    environmentId: containerAppsEnvironment.id
    template: {
      containers: [
        {
          name: 'maintenance'
          image: backendImage
          command: [
            'python'
          ]
          args: [
            '-m'
            'pulseexchange.maintenance'
          ]
          env: [
            {
              name: 'PULSEEXCHANGE_ENVIRONMENT'
              value: 'production'
            }
            {
              name: 'PULSEEXCHANGE_DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'PULSEEXCHANGE_MAINTENANCE_RESEED'
              value: 'true'
            }
            {
              name: 'PULSEEXCHANGE_SEED_MARKET'
              value: 'true'
            }
            {
              name: 'PULSEEXCHANGE_SEED_BASE_URL'
              value: apiInternalOrigin
            }
            {
              name: 'PULSEEXCHANGE_SEED_STARTUP_TIMEOUT_SECONDS'
              value: '180'
            }
            {
              name: 'PULSEEXCHANGE_SEED_COMMAND_TIMEOUT_SECONDS'
              value: '30'
            }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
    }
    workloadProfileName: 'Consumption'
  }
  dependsOn: [
    apiApp
  ]
}

output webAppName string = webApp.name
output webAppUrl string = 'https://${webApp.properties.configuration.ingress.fqdn}'
output apiAppName string = apiApp.name
output processorAppName string = processorApp.name
output seedJobName string = seedJob.name
output maintenanceJobName string = maintenanceJob.name

targetScope = 'resourceGroup'

metadata name = 'PulseExchange database migration job'
metadata description = 'A manually triggered Container Apps job that applies Alembic migrations before application revisions are released.'

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
@description('Immutable public GHCR backend image tag or digest.')
param backendImage string

@secure()
@minLength(1)
@description('Complete SQLAlchemy asyncpg database URL, including ssl=require.')
param databaseUrl string

@description('Optional additional resource tags.')
param tags object = {}

var normalizedPrefix = toLower(namePrefix)
var normalizedEnvironment = toLower(environmentName)
var migrationJobName = '${normalizedPrefix}-migrate-${normalizedEnvironment}'
var resourceTags = union({
  application: 'PulseExchange'
  environment: normalizedEnvironment
  managedBy: 'Bicep'
  workload: 'public-demo'
}, tags)

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2026-01-01' existing = {
  name: containerAppsEnvironmentName
}

resource migrationJob 'Microsoft.App/jobs@2026-01-01' = {
  name: migrationJobName
  location: location
  tags: resourceTags
  properties: {
    configuration: {
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      replicaRetryLimit: 0
      replicaTimeout: 600
      secrets: [
        {
          name: 'database-url'
          value: databaseUrl
        }
      ]
      triggerType: 'Manual'
    }
    environmentId: containerAppsEnvironment.id
    template: {
      containers: [
        {
          name: 'migrate'
          image: backendImage
          command: [
            'alembic'
          ]
          args: [
            '-c'
            '/app/alembic.ini'
            'upgrade'
            'head'
          ]
          env: [
            {
              name: 'PULSEEXCHANGE_DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'PULSEEXCHANGE_ENVIRONMENT'
              value: 'production'
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
}

output migrationJobName string = migrationJob.name
output migrationJobId string = migrationJob.id
output backendImage string = backendImage

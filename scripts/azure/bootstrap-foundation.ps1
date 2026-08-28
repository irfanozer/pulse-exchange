[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string] $SubscriptionId,

    [Parameter(Mandatory)]
    [string] $GitHubRepository,

    [string] $Location = "eastus2",
    [string] $ResourceGroup = "rg-pulseexchange-prod",
    [string] $NamePrefix = "pulseexchange",
    [string] $EnvironmentName = "prod",
    [string] $CustomDomain = "pulseexchange.irfanburakozer.com",
    [string] $PostgresAdministratorLogin = "pulseexchange_admin",
    [string] $PostgresDatabaseName = "pulseexchange",
    [SecureString] $PostgresAdministratorPassword,

    [Parameter(Mandatory)]
    [switch] $ConfirmCosts
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-Command {
    param([Parameter(Mandatory)][string] $Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' is not installed or is not on PATH."
    }
}

function New-DatabasePassword {
    $randomBytes = New-Object byte[] 30
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($randomBytes)
    }
    finally {
        $generator.Dispose()
    }
    $randomText = [Convert]::ToBase64String($randomBytes).TrimEnd("=").Replace("+", "A").Replace("/", "b")
    return "Px9!$randomText"
}

if (-not $ConfirmCosts) {
    throw "Review the cost boundary in docs/deployment.md, then pass -ConfirmCosts."
}

Assert-Command -Name "az"
Assert-Command -Name "gh"

gh auth status | Out-Null
$repositoryParts = $GitHubRepository.Split('/', 2)
if ($repositoryParts.Count -ne 2 -or [string]::IsNullOrWhiteSpace($repositoryParts[0])) {
    throw "-GitHubRepository must use OWNER/REPOSITORY format, for example irfanozer/pulse-exchange."
}

az account set --subscription $SubscriptionId
$account = az account show --output json | ConvertFrom-Json
if (-not $account.id) {
    throw "Azure CLI is not signed in. Run 'az login' and try again."
}

$providers = @(
    "Microsoft.App",
    "Microsoft.DBforPostgreSQL",
    "Microsoft.Network",
    "Microsoft.OperationalInsights"
)
foreach ($provider in $providers) {
    Write-Host "Registering Azure provider $provider ..."
    az provider register --namespace $provider --wait --only-show-errors | Out-Null
}

Write-Host "Creating resource group $ResourceGroup in $Location ..."
az group create `
    --name $ResourceGroup `
    --location $Location `
    --tags project=pulseexchange environment=production managed-by=bicep `
    --only-show-errors `
    --output none

$plainPassword = if ($PostgresAdministratorPassword) {
    ([System.Net.NetworkCredential]::new("", $PostgresAdministratorPassword)).Password
}
else {
    New-DatabasePassword
}

$parameterFile = Join-Path ([System.IO.Path]::GetTempPath()) "pulseexchange-$([Guid]::NewGuid().ToString('N')).parameters.json"
try {
    $parameters = @{
        '$schema' = "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#"
        contentVersion = "1.0.0.0"
        parameters = @{
            location = @{ value = $Location }
            namePrefix = @{ value = $NamePrefix }
            environmentName = @{ value = $EnvironmentName }
            postgresAdministratorLogin = @{ value = $PostgresAdministratorLogin }
            postgresAdministratorPassword = @{ value = $plainPassword }
            postgresDatabaseName = @{ value = $PostgresDatabaseName }
        }
    }
    $parameterJson = $parameters | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText(
        $parameterFile,
        $parameterJson,
        [System.Text.UTF8Encoding]::new($false)
    )

    Write-Host "Validating the foundation deployment ..."
    az deployment group validate `
        --resource-group $ResourceGroup `
        --template-file "infra/azure/foundation.bicep" `
        --parameters "@$parameterFile" `
        --only-show-errors `
        --output none

    Write-Host "Creating the Azure foundation. PostgreSQL is the main recurring cost ..."
    $outputs = az deployment group create `
        --resource-group $ResourceGroup `
        --name "foundation-$([DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))" `
        --template-file "infra/azure/foundation.bicep" `
        --parameters "@$parameterFile" `
        --only-show-errors `
        --query properties.outputs `
        --output json | ConvertFrom-Json
}
finally {
    if ([System.IO.File]::Exists($parameterFile)) {
        [System.IO.File]::Delete($parameterFile)
    }
}

$encodedUser = [Uri]::EscapeDataString($PostgresAdministratorLogin)
$encodedPassword = [Uri]::EscapeDataString($plainPassword)
$databaseUrl = "postgresql+asyncpg://${encodedUser}:${encodedPassword}@$($outputs.postgresServerFqdn.value):5432/$($outputs.postgresDatabaseName.value)?ssl=require"

Write-Host "Saving the database URL as a masked GitHub repository secret ..."
$databaseUrl | gh secret set PULSEEXCHANGE_DATABASE_URL --repo $GitHubRepository

gh variable set AZURE_RESOURCE_GROUP --repo $GitHubRepository --body $ResourceGroup
gh variable set AZURE_NAME_PREFIX --repo $GitHubRepository --body $NamePrefix
gh variable set AZURE_ENVIRONMENT_NAME --repo $GitHubRepository --body $EnvironmentName
gh variable set AZURE_CONTAINER_APPS_ENVIRONMENT `
    --repo $GitHubRepository `
    --body $outputs.containerAppsEnvironmentName.value
gh variable set PULSEEXCHANGE_CUSTOM_DOMAIN `
    --repo $GitHubRepository `
    --body $CustomDomain
gh variable set PULSEEXCHANGE_REQUIRE_CUSTOM_DOMAIN `
    --repo $GitHubRepository `
    --body "false"
gh variable set AZURE_DEPLOYMENT_ENABLED `
    --repo $GitHubRepository `
    --body "false"

$plainPassword = $null
$databaseUrl = $null

Write-Host ""
Write-Host "Foundation created successfully."
Write-Host "Resource group: $ResourceGroup"
Write-Host "Container Apps environment: $($outputs.containerAppsEnvironmentName.value)"
Write-Host "PostgreSQL server: $($outputs.postgresServerFqdn.value)"
Write-Host "Deployment remains disabled until AZURE_DEPLOYMENT_ENABLED is set to true."
Write-Host "Next: run scripts/azure/configure-github-oidc.ps1."

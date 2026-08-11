[CmdletBinding()]
param(
    [string] $AccountName,
    [string] $ResourceGroup,
    [string] $SubscriptionId
)

$ErrorActionPreference = 'Stop'
$roleDefinitionId = '00000000-0000-0000-0000-000000000002'

function Get-AzdEnvironmentValue {
    param([Parameter(Mandatory)] [string] $Name)

    if (-not (Get-Command azd -ErrorAction SilentlyContinue)) {
        return $null
    }

    $value = azd env get-value $Name 2>$null
    if ($LASTEXITCODE -eq 0 -and $value) {
        return $value.Trim()
    }

    return $null
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI (az) is required.'
}

if (-not $SubscriptionId) {
    $SubscriptionId = if ($env:AZURE_SUBSCRIPTION_ID) {
        $env:AZURE_SUBSCRIPTION_ID
    } else {
        Get-AzdEnvironmentValue -Name 'AZURE_SUBSCRIPTION_ID'
    }
}

if (-not $SubscriptionId) {
    $SubscriptionId = az account show --query id --output tsv
}

if (-not $ResourceGroup) {
    $ResourceGroup = if ($env:AZURE_RESOURCE_GROUP) {
        $env:AZURE_RESOURCE_GROUP
    } else {
        Get-AzdEnvironmentValue -Name 'AZURE_RESOURCE_GROUP'
    }
}

if (-not $ResourceGroup) {
    throw 'Resource group not found. Pass -ResourceGroup or select an azd environment.'
}

if (-not $AccountName) {
    $accounts = @(
        az cosmosdb list `
            --resource-group $ResourceGroup `
            --subscription $SubscriptionId `
            --query '[].name' `
            --output json | ConvertFrom-Json
    )

    if ($accounts.Count -ne 1) {
        throw "Expected one Cosmos DB account in '$ResourceGroup', found $($accounts.Count). Pass -AccountName explicitly."
    }

    $AccountName = $accounts[0]
}

$currentUser = az ad signed-in-user show --output json | ConvertFrom-Json
if (-not $currentUser.id) {
    throw 'The current Azure CLI identity is not an Entra user. Sign in as a user with az login.'
}

$accountId = az cosmosdb show `
    --name $AccountName `
    --resource-group $ResourceGroup `
    --subscription $SubscriptionId `
    --query id `
    --output tsv

$assignments = @(
    az cosmosdb sql role assignment list `
        --account-name $AccountName `
        --resource-group $ResourceGroup `
        --subscription $SubscriptionId `
        --output json | ConvertFrom-Json
)

$existingAssignment = $assignments | Where-Object {
    $_.principalId -eq $currentUser.id -and
    $_.roleDefinitionId.EndsWith("/$roleDefinitionId") -and
    $_.scope.TrimEnd('/') -eq $accountId.TrimEnd('/')
} | Select-Object -First 1

if ($existingAssignment) {
    Write-Host "Cosmos DB Built-in Data Contributor is already assigned to $($currentUser.userPrincipalName)."
    Write-Host "Assignment: $($existingAssignment.name)"
    exit 0
}

$assignment = az cosmosdb sql role assignment create `
    --account-name $AccountName `
    --resource-group $ResourceGroup `
    --subscription $SubscriptionId `
    --role-definition-id $roleDefinitionId `
    --principal-id $currentUser.id `
    --scope $accountId `
    --output json | ConvertFrom-Json

Write-Host "Assigned Cosmos DB Built-in Data Contributor to $($currentUser.userPrincipalName)."
Write-Host "Account: $AccountName"
Write-Host "Scope: $($assignment.scope)"
Write-Host "Assignment: $($assignment.name)"
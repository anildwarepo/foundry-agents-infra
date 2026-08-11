[CmdletBinding()]
param(
    [string] $AgentName = 'agent-framework-agent-basic-responses',
    [string] $Version,
    [string] $ProjectEndpoint,
    [string] $SubscriptionId,
    [string] $ResourceGroup,
    [string] $AccountName,
    [string] $ProjectName,
    [string] $ModelDeploymentName,
    [switch] $TestInvocation
)

$ErrorActionPreference = 'Stop'
$script:failures = 0
$script:warnings = 0

function Write-Check {
    param(
        [Parameter(Mandatory)] [ValidateSet('PASS', 'WARN', 'FAIL', 'INFO')] [string] $Status,
        [Parameter(Mandatory)] [string] $Message
    )

    switch ($Status) {
        'PASS' { Write-Host "[PASS] $Message" -ForegroundColor Green }
        'WARN' {
            $script:warnings++
            Write-Host "[WARN] $Message" -ForegroundColor Yellow
        }
        'FAIL' {
            $script:failures++
            Write-Host "[FAIL] $Message" -ForegroundColor Red
        }
        'INFO' { Write-Host "[INFO] $Message" -ForegroundColor Cyan }
    }
}

function Invoke-Native {
    param(
        [Parameter(Mandatory)] [string] $Command,
        [Parameter(Mandatory)] [string[]] $Arguments,
        [switch] $AllowFailure
    )

    $output = & $Command @Arguments 2>&1
    if ($LASTEXITCODE -ne 0 -and -not $AllowFailure) {
        throw "Command failed: $Command $($Arguments -join ' ')`n$($output -join "`n")"
    }

    return @($output)
}

function Get-AzdValue {
    param([Parameter(Mandatory)] [string] $Name)

    $output = Invoke-Native -Command 'azd' -Arguments @('env', 'get-value', $Name) -AllowFailure
    if ($LASTEXITCODE -ne 0) {
        return $null
    }

    $value = ($output | Where-Object { $_ -notmatch '^Update available:' -and $_ -notmatch '^To update,' }) -join "`n"
    return $value.Trim()
}

function Get-PropertyValue {
    param(
        [Parameter(Mandatory)] [object] $Object,
        [Parameter(Mandatory)] [string[]] $Names
    )

    foreach ($name in $Names) {
        $property = $Object.PSObject.Properties[$name]
        if ($property -and $null -ne $property.Value) {
            return $property.Value
        }
    }

    return $null
}

foreach ($command in @('az', 'azd')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        Write-Check -Status FAIL -Message "$command is not installed or is not on PATH."
    }
}

if ($script:failures -gt 0) {
    exit 1
}

$serviceKey = $AgentName.ToUpperInvariant() -replace '[^A-Z0-9]', '_'
$SubscriptionId = if ($SubscriptionId) { $SubscriptionId } else { Get-AzdValue 'AZURE_SUBSCRIPTION_ID' }
$ResourceGroup = if ($ResourceGroup) { $ResourceGroup } else { Get-AzdValue 'AZURE_RESOURCE_GROUP' }
$AccountName = if ($AccountName) { $AccountName } else { Get-AzdValue 'AZURE_AI_ACCOUNT_NAME' }
$ProjectName = if ($ProjectName) { $ProjectName } else { Get-AzdValue 'AZURE_AI_PROJECT_NAME' }
$ProjectEndpoint = if ($ProjectEndpoint) { $ProjectEndpoint } else { Get-AzdValue 'AZURE_AI_PROJECT_ENDPOINT' }
$ModelDeploymentName = if ($ModelDeploymentName) { $ModelDeploymentName } else { Get-AzdValue 'AZURE_AI_MODEL_DEPLOYMENT_NAME' }
$Version = if ($Version) { $Version } else { Get-AzdValue "AGENT_${serviceKey}_VERSION" }

$missingValues = @{
    SubscriptionId = $SubscriptionId
    ResourceGroup = $ResourceGroup
    AccountName = $AccountName
    ProjectName = $ProjectName
    ProjectEndpoint = $ProjectEndpoint
    Version = $Version
}

foreach ($entry in $missingValues.GetEnumerator()) {
    if (-not $entry.Value) {
        Write-Check -Status FAIL -Message "$($entry.Key) could not be resolved from parameters or the selected azd environment."
    }
}

if ($script:failures -gt 0) {
    exit 1
}

Write-Check -Status INFO -Message "Agent: $AgentName version $Version"
Write-Check -Status INFO -Message "Project: $ProjectEndpoint"

$account = $null
try {
    $account = (Invoke-Native -Command 'az' -Arguments @(
        'cognitiveservices', 'account', 'show',
        '--name', $AccountName,
        '--resource-group', $ResourceGroup,
        '--subscription', $SubscriptionId,
        '--output', 'json'
    ) | Out-String) | ConvertFrom-Json
    Write-Check -Status PASS -Message "Foundry account exists in resource group '$ResourceGroup'."
} catch {
    Write-Check -Status FAIL -Message "Foundry account '$AccountName' was not found in '$ResourceGroup'. The azd environment may contain stale resource IDs."
}

if ($account) {
    $azdAccountId = Get-AzdValue 'AZURE_AI_ACCOUNT_ID'
    if ($azdAccountId -and $azdAccountId.TrimEnd('/') -ne $account.id.TrimEnd('/')) {
        Write-Check -Status FAIL -Message "AZURE_AI_ACCOUNT_ID does not match the live account ID '$($account.id)'."
    } else {
        Write-Check -Status PASS -Message 'azd account metadata matches the live resource.'
    }
}

$project = $null
if ($account) {
    try {
        $project = (Invoke-Native -Command 'az' -Arguments @(
            'rest', '--method', 'GET',
            '--url', "$($account.id)/projects/$ProjectName`?api-version=2025-04-01-preview"
        ) | Out-String) | ConvertFrom-Json
        Write-Check -Status PASS -Message "Foundry project exists; principal ID is $($project.identity.principalId)."
    } catch {
        Write-Check -Status FAIL -Message "Foundry project '$ProjectName' could not be read."
    }
}

if ($ModelDeploymentName) {
    try {
        $model = (Invoke-Native -Command 'az' -Arguments @(
            'cognitiveservices', 'account', 'deployment', 'show',
            '--name', $AccountName,
            '--resource-group', $ResourceGroup,
            '--subscription', $SubscriptionId,
            '--deployment-name', $ModelDeploymentName,
            '--output', 'json'
        ) | Out-String) | ConvertFrom-Json
        if ($model.properties.provisioningState -eq 'Succeeded') {
            Write-Check -Status PASS -Message "Model deployment '$ModelDeploymentName' is ready."
        } else {
            Write-Check -Status FAIL -Message "Model deployment '$ModelDeploymentName' is '$($model.properties.provisioningState)'."
        }
    } catch {
        Write-Check -Status FAIL -Message "Model deployment '$ModelDeploymentName' was not found."
    }
} else {
    Write-Check -Status WARN -Message 'No model deployment name was resolved; model readiness was not checked.'
}

$agentVersion = $null
try {
    $token = (Invoke-Native -Command 'az' -Arguments @(
        'account', 'get-access-token', '--resource', 'https://ai.azure.com',
        '--query', 'accessToken', '--output', 'tsv'
    ) | Out-String).Trim()
    $headers = @{
        Authorization = "Bearer $token"
        'Foundry-Features' = 'HostedAgents=V1Preview'
    }
    $versionUri = "$($ProjectEndpoint.TrimEnd('/'))/agents/$AgentName/versions/$Version`?api-version=2025-11-15-preview"
    $agentVersion = Invoke-RestMethod -Method Get -Uri $versionUri -Headers $headers
    if ($agentVersion.status -eq 'active') {
        Write-Check -Status PASS -Message "Hosted agent version is active."
    } else {
        Write-Check -Status FAIL -Message "Hosted agent version status is '$($agentVersion.status)'."
    }
} catch {
    Write-Check -Status FAIL -Message "Hosted agent version could not be read: $($_.Exception.Message)"
}

$image = if ($agentVersion) { $agentVersion.definition.container_configuration.image } else { $null }
if ($image -and $image -match '^(?<registry>[^/]+)\/(?<repository>.+):(?<tag>[^:]+)$') {
    $registryHost = $Matches.registry
    $repository = $Matches.repository
    $tag = $Matches.tag
    $registryName = $registryHost -replace '\.azurecr\.io$', ''
    Write-Check -Status INFO -Message "Deployed image: $image"

    $acr = $null
    try {
        $acr = (Invoke-Native -Command 'az' -Arguments @(
            'acr', 'show', '--name', $registryName,
            '--subscription', $SubscriptionId, '--output', 'json'
        ) | Out-String) | ConvertFrom-Json
        Write-Check -Status PASS -Message "ACR '$registryName' exists in '$($acr.resourceGroup)' using '$($acr.roleAssignmentMode)'."
    } catch {
        Write-Check -Status FAIL -Message "ACR '$registryName' could not be read."
    }

    if ($acr) {
        $tags = @((Invoke-Native -Command 'az' -Arguments @(
            'acr', 'repository', 'show-tags', '--name', $registryName,
            '--repository', $repository, '--subscription', $SubscriptionId,
            '--output', 'json'
        ) | Out-String) | ConvertFrom-Json)
        if ($tags -contains $tag) {
            Write-Check -Status PASS -Message "Image tag '$repository`:$tag' exists."
        } else {
            Write-Check -Status FAIL -Message "Image tag '$repository`:$tag' does not exist."
        }

        $authAsArmOutput = Invoke-Native -Command 'az' -Arguments @(
            'acr', 'config', 'authentication-as-arm', 'show',
            '--registry', $registryName, '--subscription', $SubscriptionId,
            '--query', 'status', '--output', 'tsv'
        )
        $authAsArm = @($authAsArmOutput | Where-Object { $_ -in @('enabled', 'disabled') })[-1]
        if ($authAsArm -eq 'enabled') {
            Write-Check -Status PASS -Message 'ACR authentication-as-ARM is enabled.'
        } else {
            Write-Check -Status FAIL -Message "ACR authentication-as-ARM is '$authAsArm'."
        }

        if ($project -and $project.identity.principalId) {
            $pullAssignments = @((Invoke-Native -Command 'az' -Arguments @(
                'role', 'assignment', 'list', '--scope', $acr.id,
                '--assignee', $project.identity.principalId,
                '--subscription', $SubscriptionId, '--output', 'json'
            ) | Out-String) | ConvertFrom-Json)
            $pullRoles = @($pullAssignments | ForEach-Object { $_.roleDefinitionName })
            $hasPull = $pullRoles -contains 'AcrPull'
            if ($acr.roleAssignmentMode -eq 'LegacyRegistryPermissions' -and -not $hasPull) {
                Write-Check -Status FAIL -Message "Project identity lacks classic AcrPull, which is required by this legacy-mode registry."
            } elseif ($hasPull) {
                Write-Check -Status PASS -Message 'Project identity has AcrPull on the registry.'
            } else {
                Write-Check -Status WARN -Message "Project identity roles do not include AcrPull; verify an appropriate ABAC repository role is assigned."
            }
        }

        if ($account) {
            try {
                $managedNetwork = (Invoke-Native -Command 'az' -Arguments @(
                    'rest', '--method', 'GET',
                    '--url', "$($account.id)/managedNetworks/default?api-version=2025-10-01-preview"
                ) | Out-String) | ConvertFrom-Json
                $rules = $managedNetwork.properties.managedNetwork.outboundRules
                Write-Check -Status INFO -Message "Managed VNet isolation mode: $($managedNetwork.properties.managedNetwork.isolationMode)"

                $requiredTargets = @('account', 'blob', 'searchService', 'sql', 'registry')
                foreach ($target in $requiredTargets) {
                    $matchingRules = @($rules.PSObject.Properties.Value | Where-Object {
                        $_.type -eq 'PrivateEndpoint' -and $_.destination.subresourceTarget -ieq $target
                    })
                    if ($matchingRules.Count -eq 0) {
                        Write-Check -Status FAIL -Message "No managed-VNet PrivateEndpoint outbound rule targets '$target'."
                    } elseif ($matchingRules.status -contains 'Active') {
                        Write-Check -Status PASS -Message "Managed-VNet outbound target '$target' is Active."
                    } else {
                        Write-Check -Status FAIL -Message "Managed-VNet outbound target '$target' is '$($matchingRules.status -join ', ')'."
                    }
                }

                $registryRule = @($rules.PSObject.Properties.Value | Where-Object {
                    $_.type -eq 'PrivateEndpoint' -and
                    $_.destination.subresourceTarget -eq 'registry' -and
                    $_.destination.serviceResourceId.TrimEnd('/') -eq $acr.id.TrimEnd('/')
                })
                if ($registryRule.Count -eq 0) {
                    Write-Check -Status FAIL -Message "The registry outbound rule does not target deployed image registry '$registryName'."
                }
            } catch {
                Write-Check -Status FAIL -Message "Managed network rules could not be read: $($_.Exception.Message)"
            }
        }
    }
} elseif ($image) {
    Write-Check -Status WARN -Message "Container image '$image' is not an Azure Container Registry image; ACR checks were skipped."
} else {
    Write-Check -Status WARN -Message 'The deployed definition has no container image; ACR checks were skipped.'
}

if ($TestInvocation) {
    Write-Check -Status INFO -Message 'Testing with a new session and conversation to avoid stale cached state.'
    $invokeOutput = Invoke-Native -Command 'azd' -Arguments @(
        'ai', 'agent', 'invoke', '--version', $Version,
        '--new-session', '--new-conversation',
        'Reply with exactly: healthy'
    ) -AllowFailure
    if ($LASTEXITCODE -eq 0 -and ($invokeOutput -join "`n") -match '(?im)^.*healthy\s*$') {
        Write-Check -Status PASS -Message 'Fresh hosted-agent invocation succeeded.'
    } else {
        Write-Check -Status FAIL -Message "Fresh hosted-agent invocation failed.`n$($invokeOutput -join "`n")"
    }
} else {
    Write-Check -Status INFO -Message 'Invocation not tested. Use -TestInvocation to force a fresh session and conversation.'
}

Write-Host ''
Write-Host "Checklist complete: $script:failures failure(s), $script:warnings warning(s)."
if ($script:failures -gt 0) {
    exit 1
}
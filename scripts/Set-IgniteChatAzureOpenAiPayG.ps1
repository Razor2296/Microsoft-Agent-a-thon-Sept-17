<#
.SYNOPSIS
  Write PAYG Azure OpenAI (Foundry v1) credentials into kvignitechatsiu for ignitechat-api.

.DESCRIPTION
  Chat uses foundryignitechatsiu (IgniteChat RG), NOT igniteapifoundry2296.
  Do not use Set-IgniteApiAzureOpenAiPayG.ps1 -AlsoUpdateChatVault for Chat.

.EXAMPLE
  az account set --subscription 4a614b14-fa98-4088-b2ec-dd6e3cc593bd
  pwsh -File .\scripts\Set-IgniteChatAzureOpenAiPayG.ps1
#>
[CmdletBinding()]
param(
    [string]$SubscriptionId = "4a614b14-fa98-4088-b2ec-dd6e3cc593bd",
    [string]$ResourceGroup = "IgniteChat",
    [string]$FoundryAccountName = "foundryignitechatsiu",
    [string]$TargetVault = "kvignitechatsiu"
)

$ErrorActionPreference = "Stop"

function Assert-AzCliSession {
    az account show -o none 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI not signed in. Run: az login --tenant 19b73b1f-8603-4b51-ac82-5b17f03d2820"
    }
}

Assert-AzCliSession
az account set --subscription $SubscriptionId | Out-Null
if ($LASTEXITCODE -ne 0) { throw "az account set failed for $SubscriptionId" }

$endpointRaw = az cognitiveservices account show -g $ResourceGroup -n $FoundryAccountName `
    --query "properties.endpoint" -o tsv 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Could not read OpenAI account: $ResourceGroup / $FoundryAccountName`n$endpointRaw"
}
$baseEndpoint = ($endpointRaw | Out-String).Trim().TrimEnd("/")
if ([string]::IsNullOrWhiteSpace($baseEndpoint)) {
    throw "OpenAI account not found: $ResourceGroup / $FoundryAccountName"
}

$chatEndpoint = "$baseEndpoint/openai/v1"
$key = az cognitiveservices account keys list -g $ResourceGroup -n $FoundryAccountName --query key1 -o tsv
if ([string]::IsNullOrWhiteSpace($key)) {
    throw "Could not read key1 for $FoundryAccountName"
}

$deployments = az cognitiveservices account deployment list -g $ResourceGroup -n $FoundryAccountName `
    --query "[].name" -o tsv 2>$null
if ([string]::IsNullOrWhiteSpace($deployments)) {
    Write-Host "WARNING: No deployments on $FoundryAccountName. Run Deploy-IgniteOpenAiModelsPayG.ps1" -ForegroundColor Yellow
}
else {
    Write-Host "Deployments on ${FoundryAccountName}: $($deployments -replace "`n", ', ')" -ForegroundColor DarkGray
}

Write-Host "Writing AZURE-OPENAI-ENDPOINT + AZURE-OPENAI-API-KEY to $TargetVault ..." -ForegroundColor Cyan
az keyvault secret set --vault-name $TargetVault --name AZURE-OPENAI-ENDPOINT --value $chatEndpoint -o none
if ($LASTEXITCODE -ne 0) {
    throw "Key Vault write failed. Run: pwsh -File .\scripts\Grant-IgniteChatKeyVaultAccess.ps1"
}
az keyvault secret set --vault-name $TargetVault --name AZURE-OPENAI-API-KEY --value $key -o none
if ($LASTEXITCODE -ne 0) { throw "Failed writing AZURE-OPENAI-API-KEY" }

Write-Host "Done. Chat KV endpoint: $chatEndpoint" -ForegroundColor Green
Write-Host "Redeploy or restart ignitechat-api if secrets were stale (Deploy-IgniteChatAca.ps1 -SkipBuild)." -ForegroundColor Cyan

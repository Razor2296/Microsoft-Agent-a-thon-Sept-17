<#
.SYNOPSIS
  Write PAYG Azure OpenAI credentials into kvsecret2296siu for ignite-api Doc/LLM calls.

.DESCRIPTION
  Import-IgniteApiSecretsToPayG often copies AZURE-OPENAI-* from Chat vault or Students migrate.env.
  ignite-api must use the PAYG resource igniteapifoundry2296 (classic endpoint + key), not Students.

.EXAMPLE
  az account set --subscription 4a614b14-fa98-4088-b2ec-dd6e3cc593bd
  pwsh -File .\scripts\Set-IgniteApiAzureOpenAiPayG.ps1
#>
[CmdletBinding()]
param(
    [string]$SubscriptionId = "4a614b14-fa98-4088-b2ec-dd6e3cc593bd",
    [string]$ResourceGroup = "IgniteAPI",
    [string]$FoundryAccountName = "igniteapifoundry2296",
    [string]$TargetVault = "kvsecret2296siu"
)

$ErrorActionPreference = "Stop"

function Assert-AzCliSession {
    $accountJson = az account show -o json 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($accountJson)) {
        throw @"
Azure CLI session is not signed in or the token expired (AADSTS50173 after password change is common).

Run:
  az logout
  az login --tenant "19b73b1f-8603-4b51-ac82-5b17f03d2820" --scope "https://management.core.windows.net//.default"
  az account set --subscription $SubscriptionId

Then re-run this script.
"@
    }
}

Assert-AzCliSession

az account set --subscription $SubscriptionId 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "az account set failed for subscription $SubscriptionId. Sign in again with az login."
}

$endpointRaw = az cognitiveservices account show -g $ResourceGroup -n $FoundryAccountName `
    --query "properties.endpoint" -o tsv 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Could not read OpenAI account (check login/RBAC): $ResourceGroup / $FoundryAccountName`n$endpointRaw"
}
$endpoint = ($endpointRaw | Out-String).Trim()
if ([string]::IsNullOrWhiteSpace($endpoint)) {
    throw "OpenAI account not found: $ResourceGroup / $FoundryAccountName"
}

$key = az cognitiveservices account keys list -g $ResourceGroup -n $FoundryAccountName --query key1 -o tsv
if ([string]::IsNullOrWhiteSpace($key)) {
    throw "Could not read key1 for $FoundryAccountName"
}

$deployments = az cognitiveservices account deployment list -g $ResourceGroup -n $FoundryAccountName `
    --query "[].name" -o tsv 2>$null
if ([string]::IsNullOrWhiteSpace($deployments)) {
    Write-Host "WARNING: No model deployments on $FoundryAccountName." -ForegroundColor Yellow
    Write-Host "  Deploy gpt-4.1-mini (or change AZURE_OPENAI_DEPLOYMENT_NAME on ignite-api ACA) in Azure Portal." -ForegroundColor Yellow
}
else {
    Write-Host "Deployments on ${FoundryAccountName}: $($deployments -replace "`n", ', ')" -ForegroundColor DarkGray
}

Write-Host "Writing AZURE-OPENAI-ENDPOINT + AZURE-OPENAI-API-KEY to $TargetVault ..." -ForegroundColor Cyan
az keyvault secret set --vault-name $TargetVault --name AZURE-OPENAI-ENDPOINT --value $endpoint -o none
if ($LASTEXITCODE -ne 0) {
    throw "Key Vault write failed. Run: pwsh -File .\scripts\Grant-IgniteApiKeyVaultAccess.ps1"
}
az keyvault secret set --vault-name $TargetVault --name AZURE-OPENAI-API-KEY --value $key -o none
if ($LASTEXITCODE -ne 0) { throw "Failed writing AZURE-OPENAI-API-KEY" }

Write-Host "Done. ignite-api KV now points to: $endpoint" -ForegroundColor Green
Write-Host "Restart/redeploy not required (app reads KV at runtime). Re-run Postman extract to verify tokens > 0." -ForegroundColor Cyan
Write-Host "For ignitechat-api use: pwsh -File .\scripts\Set-IgniteChatAzureOpenAiPayG.ps1" -ForegroundColor DarkGray

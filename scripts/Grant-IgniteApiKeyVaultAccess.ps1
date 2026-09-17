<#
.SYNOPSIS
  RBAC on KV-Secret2296 (PAYG) for signed-in user + ignite-api MI when it exists.
#>
[CmdletBinding()]
param(
    [string]$SubscriptionId = "4a614b14-fa98-4088-b2ec-dd6e3cc593bd",
    [string]$KeyVaultName = "kvsecret2296siu",
    [string]$KeyVaultResourceGroup = "IgniteAPI",
    [string]$ContainerAppName = "ignite-api"
)

$ErrorActionPreference = "Stop"
az account set --subscription $SubscriptionId | Out-Null
$kvId = az keyvault show -g $KeyVaultResourceGroup -n $KeyVaultName --query id -o tsv
$userId = az ad signed-in-user show --query id -o tsv
$miId = az containerapp show -g $KeyVaultResourceGroup -n $ContainerAppName --query identity.principalId -o tsv 2>$null

function Ensure-Role($Role, $ObjectId, $Type, $Label) {
    if ([string]::IsNullOrWhiteSpace($ObjectId)) { return }
    $existing = az role assignment list --assignee $ObjectId --scope $kvId --role $Role --query "[0].id" -o tsv 2>$null
    if ($existing) { Write-Host "$Label already has $Role" -ForegroundColor DarkGray; return }
    Write-Host "Assigning $Role to $Label ..." -ForegroundColor Cyan
    az role assignment create --assignee-object-id $ObjectId --assignee-principal-type $Type --role $Role --scope $kvId -o none
}

Ensure-Role "Key Vault Secrets Officer" $userId "User" "signed-in user"
Ensure-Role "Key Vault Secrets User" $miId "ServicePrincipal" "ignite-api MI"
Write-Host "Done." -ForegroundColor Green

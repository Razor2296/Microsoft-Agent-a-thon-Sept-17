<#
.SYNOPSIS
  Grant Key Vault RBAC on kvignitechatsiu (PAYG) for you and ignitechat-api MI.

.EXAMPLE
  az login --tenant 19b73b1f-8603-4b51-ac82-5b17f03d2820
  az account set --subscription 4a614b14-fa98-4088-b2ec-dd6e3cc593bd
  pwsh -File .\scripts\Grant-IgniteChatKeyVaultAccess.ps1
#>
[CmdletBinding()]
param(
    [string]$SubscriptionId = "4a614b14-fa98-4088-b2ec-dd6e3cc593bd",
    [string]$KeyVaultName = "kvignitechatsiu",
    [string]$KeyVaultResourceGroup = "IgniteChat",
    [string]$ContainerAppName = "ignitechat-api",
    [string]$ContainerAppResourceGroup = "IgniteAPI"
)

$ErrorActionPreference = "Stop"
az account set --subscription $SubscriptionId | Out-Null

$kvId = az keyvault show -g $KeyVaultResourceGroup -n $KeyVaultName --query id -o tsv
$userId = az ad signed-in-user show --query id -o tsv
$miId = az containerapp show -g $ContainerAppResourceGroup -n $ContainerAppName --query identity.principalId -o tsv

function Ensure-Role {
    param([string]$Role, [string]$ObjectId, [string]$PrincipalType, [string]$Label)
    if ([string]::IsNullOrWhiteSpace($ObjectId)) { return }
    $existing = az role assignment list --assignee $ObjectId --scope $kvId --role $Role --query "[0].id" -o tsv 2>$null
    if ($existing) {
        Write-Host "$Label already has $Role" -ForegroundColor DarkGray
        return
    }
    Write-Host "Assigning $Role to $Label ..." -ForegroundColor Cyan
    az role assignment create `
        --assignee-object-id $ObjectId `
        --assignee-principal-type $PrincipalType `
        --role $Role `
        --scope $kvId `
        -o none
}

Ensure-Role -Role "Key Vault Secrets Officer" -ObjectId $userId -PrincipalType "User" -Label "signed-in user"
Ensure-Role -Role "Key Vault Secrets User" -ObjectId $miId -PrincipalType "ServicePrincipal" -Label "ignitechat-api MI"

Write-Host "Done. Wait ~1 min for RBAC propagation, then set secrets or re-run Copy-IgniteChatSecretsStudentsToPayG.ps1." -ForegroundColor Green

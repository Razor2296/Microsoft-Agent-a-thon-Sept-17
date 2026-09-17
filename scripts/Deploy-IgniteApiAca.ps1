<#
.SYNOPSIS
  Deploy ignite-api Container App on PAYG (mirror of Students).

.EXAMPLE
  pwsh -File .\scripts\Deploy-IgniteApiAca.ps1
  pwsh -File .\scripts\Deploy-IgniteApiAca.ps1 -SkipBuild -ExportFile .\scripts\ignite-api-payg-export.json
#>
[CmdletBinding()]
param(
    [string]$SubscriptionId = "4a614b14-fa98-4088-b2ec-dd6e3cc593bd",
    [string]$AppResourceGroup = "IgniteAPI",
    [string]$AcrName = "igniteapisiuacr",
    [string]$ContainerAppName = "ignite-api",
    [string]$ContainerEnvId = "/subscriptions/4a614b14-fa98-4088-b2ec-dd6e3cc593bd/resourceGroups/IgniteAPI/providers/Microsoft.App/managedEnvironments/managedEnvironment-IgniteAPI-862f",
    [string]$KeyVaultName = "kvsecret2296siu",
    [string]$ImageName = "ignite-api",
    [string]$ImageTag = "latest",
    [string]$ExportFile = "",
    [string]$Cpu = "",
    [string]$Memory = "",
    [int]$TargetPort = 8080,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ExportFile)) {
    $ExportFile = Join-Path $PSScriptRoot "ignite-api-payg-export.json"
}

az account set --subscription $SubscriptionId | Out-Null
az acr update -n $AcrName -g $AppResourceGroup --admin-enabled true | Out-Null
$acrServer = az acr show -g $AppResourceGroup -n $AcrName --query loginServer -o tsv
$acrUser = az acr credential show -n $AcrName -g $AppResourceGroup --query username -o tsv
$acrPass = az acr credential show -n $AcrName -g $AppResourceGroup --query "passwords[0].value" -o tsv

$fullImage = "${acrServer}/${ImageName}:${ImageTag}"
if (Test-Path $ExportFile) {
    $exp = Get-Content $ExportFile -Raw | ConvertFrom-Json
    if ($exp.image -match "ignite-api") {
        $fullImage = $exp.image -replace "caacc1441625acr.azurecr.io", $acrServer
        if ($exp.image -notmatch $acrServer) {
            $fullImage = "${acrServer}/${ImageName}:${ImageTag}"
        }
    }
    $Cpu = $exp.cpu
    $Memory = $exp.memory
    $MinRep = $exp.minReplicas
    $MaxRep = $exp.maxReplicas
    $TargetPort = $exp.targetPort
}
else {
    Write-Host "No export file at $ExportFile — using defaults (import ignite-api image to ACR first)." -ForegroundColor Yellow
    if ([string]::IsNullOrWhiteSpace($Cpu)) { $Cpu = "2.0" }
    if ([string]::IsNullOrWhiteSpace($Memory)) { $Memory = "4Gi" }
    $MinRep = 0
    $MaxRep = 1
}
if ([string]::IsNullOrWhiteSpace($Cpu)) { $Cpu = "2.0" }
if ([string]::IsNullOrWhiteSpace($Memory)) { $Memory = "4Gi" }

$kvUri = (az keyvault show -n $KeyVaultName -g $AppResourceGroup --query properties.vaultUri -o tsv).TrimEnd("/") + "/"
$kvId = az keyvault show -n $KeyVaultName -g $AppResourceGroup --query id -o tsv

$runtimeEnvVars = @(
    "APP_ROLE=api",
    "AZURE_KEYVAULT_URL=$kvUri",
    "AZURE_STORAGE_CONTAINER_UPLOADS=ignite-uploads",
    "AZURE_STORAGE_CONTAINER_RESULTS=ignite-results",
    "AZURE_SERVICE_BUS_QUEUE_NAME=ignite-jobs-queue",
    "DEFAULT_LLM_PROVIDER=azure_openai",
    "AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4.1-mini",
    "MAX_ROW_PER_FILE=10",
    "DEEPSEEK_MAX_TOKENS=8192",
    "GEMINI_MAX_TOKENS=8192",
    "GROK_MAX_TOKENS=8192",
    "OPENAI_ENABLED=false"
)

$kvSecrets = @(
    "AZURE-STORAGE-CONNECTION-STRING", "AZURE-SERVICE-BUS-CONNECTION-STRING", "AZURE-DATALAKE-CONNECTION-STRING",
    "IGNITE-MASTER-API-KEY", "IGNITE-AUDIO-API-KEY", "IGNITE-DOC-API-KEY", "IGNITE-IMAGE-API-KEY", "IGNITE-VIDEO-API-KEY",
    "GEMINI-API-KEY", "OPENAI-API-KEY", "AZURE-OPENAI-API-KEY", "AZURE-OPENAI-ENDPOINT",
    "ANTHROPIC-API-KEY", "PERPLEXITY-API-KEY", "GROK-API-KEY", "DEEPSEEK-API-KEY"
)

$secretArgs = @()
$optionalKvSecrets = @(
    "AZURE-SERVICE-BUS-CONNECTION-STRING",
    "AZURE-DATALAKE-CONNECTION-STRING"
)
foreach ($kvName in $kvSecrets) {
    $id = az keyvault secret show --vault-name $KeyVaultName --name $kvName --query id -o tsv 2>$null
    if ([string]::IsNullOrWhiteSpace($id)) {
        if ($optionalKvSecrets -contains $kvName) {
            Write-Host "Skipping optional KV secret (not in vault): $kvName" -ForegroundColor Yellow
            continue
        }
        throw "Required Key Vault secret missing: $KeyVaultName / $kvName"
    }
    $acaName = ($kvName.ToLower() -replace "_", "-")
    $secretArgs += "$acaName=keyvaultref:${kvUri}secrets/$kvName,identityref:system"
}
if ($secretArgs.Count -eq 0) {
    throw "No Key Vault secrets to bind for $ContainerAppName"
}

$removeAcaSecrets = @()
foreach ($kvName in $optionalKvSecrets) {
    $id = az keyvault secret show --vault-name $KeyVaultName --name $kvName --query id -o tsv 2>$null
    if ([string]::IsNullOrWhiteSpace($id)) {
        $removeAcaSecrets += ($kvName.ToLower() -replace "_", "-")
    }
}

$exists = az containerapp show -g $AppResourceGroup -n $ContainerAppName --query name -o tsv 2>$null

if (-not $exists) {
    Write-Host "Creating $ContainerAppName ..." -ForegroundColor Cyan
    az containerapp create `
        -g $AppResourceGroup -n $ContainerAppName `
        --environment $ContainerEnvId `
        --image $fullImage `
        --cpu $Cpu --memory $Memory `
        --min-replicas $MinRep --max-replicas $MaxRep `
        --ingress external --target-port $TargetPort `
        --registry-server $acrServer `
        --registry-username $acrUser `
        --registry-password $acrPass `
        --system-assigned `
        --secrets $secretArgs `
        --env-vars $runtimeEnvVars `
        -o none
}
else {
    Write-Host "Updating $ContainerAppName ..." -ForegroundColor Cyan
    az containerapp registry set -g $AppResourceGroup -n $ContainerAppName --server $acrServer --username $acrUser --password $acrPass -o none
    az containerapp identity assign -g $AppResourceGroup -n $ContainerAppName --system-assigned -o none
    if ($removeAcaSecrets.Count -gt 0) {
        Write-Host "Removing stale ACA secret refs (optional KV missing): $($removeAcaSecrets -join ', ')" -ForegroundColor Yellow
        az containerapp secret remove -g $AppResourceGroup -n $ContainerAppName --secret-names $removeAcaSecrets -o none 2>$null
    }
    az containerapp secret set -g $AppResourceGroup -n $ContainerAppName --secrets $secretArgs -o none
    az containerapp update -g $AppResourceGroup -n $ContainerAppName --image $fullImage --cpu $Cpu --memory $Memory `
        --min-replicas $MinRep --max-replicas $MaxRep --set-env-vars $runtimeEnvVars -o none
}

$principalId = az containerapp show -g $AppResourceGroup -n $ContainerAppName --query identity.principalId -o tsv
if ($principalId) {
    $existing = az role assignment list --assignee $principalId --scope $kvId --role "Key Vault Secrets User" --query "[0].id" -o tsv 2>$null
    if (-not $existing) {
        az role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal `
            --role "Key Vault Secrets User" --scope $kvId -o none
    }
}

$fqdn = az containerapp show -g $AppResourceGroup -n $ContainerAppName --query "properties.configuration.ingress.fqdn" -o tsv
Write-Host ""
Write-Host "ignite-api deploy complete." -ForegroundColor Green
Write-Host "  URL: https://$fqdn"
Write-Host "  Set IGNITE_EXTRACTION_API_URL=https://$fqdn in Chat ACA / desktop if needed."

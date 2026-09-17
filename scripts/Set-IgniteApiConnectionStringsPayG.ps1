<#
.SYNOPSIS
  Escribe connection strings en kvsecret2296siu (PowerShell). PAYG mirror: solo Storage por defecto.

.EXAMPLE
  # Pegar manualmente (Portal KV-Secret2296)
  pwsh -File .\scripts\Set-IgniteApiConnectionStringsPayG.ps1 -Interactive

.EXAMPLE
  # Storage PAYG ignitechatsiu08d0 (sin Service Bus / Data Lake)
  pwsh -File .\scripts\Set-IgniteApiConnectionStringsPayG.ps1 -Interactive -UsePaygStorageAccount -StorageOnly
#>
[CmdletBinding()]
param(
    [string]$SubscriptionId = "4a614b14-fa98-4088-b2ec-dd6e3cc593bd",
    [string]$VaultName = "kvsecret2296siu",
    [string]$StorageAccountName = "ignitechatsiu08d0",
    [string]$StorageResourceGroup = "IgniteChat",
    [switch]$Interactive,
    [switch]$UsePaygStorageAccount,
    [string]$StorageConnectionString = "",
    [string]$ServiceBusConnectionString = "",
    [string]$DataLakeConnectionString = "",
    [switch]$StorageOnly
)

$ErrorActionPreference = "Stop"
az account set --subscription $SubscriptionId | Out-Null

function Set-KvSecret {
    param([string]$Name, [string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    az keyvault secret set --vault-name $VaultName --name $Name --value $Value -o none | Out-Null
    Write-Host "  OK $Name" -ForegroundColor Green
    return $true
}

if ($UsePaygStorageAccount -and [string]::IsNullOrWhiteSpace($StorageConnectionString)) {
    Write-Host "Generando AZURE-STORAGE-CONNECTION-STRING desde $StorageAccountName (PAYG)..." -ForegroundColor Cyan
    $StorageConnectionString = az storage account show-connection-string `
        -g $StorageResourceGroup -n $StorageAccountName --query connectionString -o tsv
}

if ($Interactive) {
    Write-Host "Pega valores desde Portal -> KV-Secret2296 (Students). Enter vacío = omitir." -ForegroundColor Cyan
    if (-not $UsePaygStorageAccount -and [string]::IsNullOrWhiteSpace($StorageConnectionString)) {
        $StorageConnectionString = Read-Host "AZURE-STORAGE-CONNECTION-STRING"
    }
    if (-not $StorageOnly) {
        if ([string]::IsNullOrWhiteSpace($ServiceBusConnectionString)) {
            $ServiceBusConnectionString = Read-Host "AZURE-SERVICE-BUS-CONNECTION-STRING"
        }
        if ([string]::IsNullOrWhiteSpace($DataLakeConnectionString)) {
            $DataLakeConnectionString = Read-Host "AZURE-DATALAKE-CONNECTION-STRING"
        }
    }
}

$n = 0
if (Set-KvSecret "AZURE-STORAGE-CONNECTION-STRING" $StorageConnectionString) { $n++ }
if (Set-KvSecret "AZURE-SERVICE-BUS-CONNECTION-STRING" $ServiceBusConnectionString) { $n++ }
if (Set-KvSecret "AZURE-DATALAKE-CONNECTION-STRING" $DataLakeConnectionString) { $n++ }

if ($n -eq 0) {
    throw "Nada que escribir. Usa -Interactive o -UsePaygStorageAccount -Interactive"
}

# Persistir en migrate.env (sin mostrar valores en consola)
$migrate = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")) "secrets\kvsecret2296-migrate.env"
$lines = @()
if ($StorageConnectionString) { $lines += "AZURE-STORAGE-CONNECTION-STRING=$StorageConnectionString" }
if ($ServiceBusConnectionString) { $lines += "AZURE-SERVICE-BUS-CONNECTION-STRING=$ServiceBusConnectionString" }
if ($DataLakeConnectionString) { $lines += "AZURE-DATALAKE-CONNECTION-STRING=$DataLakeConnectionString" }
if ($lines.Count -gt 0) {
    Set-Content -LiteralPath $migrate -Value $lines -Encoding UTF8
    Write-Host "Actualizado $migrate ($n secretos)." -ForegroundColor DarkGray
}

Write-Host "Listo: $n connection string(s) en $VaultName." -ForegroundColor Green
Write-Host "Siguiente: pwsh -File .\scripts\Complete-IgniteMirrorPayG.ps1 -ImportApiImage -DeployApi" -ForegroundColor Cyan

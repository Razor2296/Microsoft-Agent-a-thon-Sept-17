<#
.SYNOPSIS
  Pasos finales del espejo Students -> PAYG (PowerShell).

.DESCRIPTION
  - Secretos API (chat vault + app/.env + migrate.env + master -> IGNITE-*)
  - Import imagen ignite-api al ACR PAYG
  - Deploy ignite-api + refresh ignitechat-api (Foundry endpoint PAYG)

.EXAMPLE
  # Solo secretos API (13+3)
  pwsh -File .\scripts\Complete-IgniteMirrorPayG.ps1 -ImportApiSecrets

.EXAMPLE
  # Todo (secretos + ACR + deploys) — requiere login Students para ACR import
  pwsh -File .\scripts\Complete-IgniteMirrorPayG.ps1 -ImportApiSecrets -ImportApiImage -DeployApi -RefreshChat
#>
[CmdletBinding()]
param(
    [string]$PaygSubscriptionId = "4a614b14-fa98-4088-b2ec-dd6e3cc593bd",
    [string]$StudentsSubscriptionId = "3636d316-ce18-4497-99d7-ec747ffc4289",
    [string]$StudentsTenantId = "3209b50b-b79b-43dc-9fc4-8d42c406dd61",
    [string]$PaygTenantId = "19b73b1f-8603-4b51-ac82-5b17f03d2820",
    [string]$PaygAcr = "igniteapisiuacr",
    [string]$StudentsAcr = "caacc1441625acr",
    [string]$FoundryChatEndpoint = "https://foundryignitechatsiu-87996.openai.azure.com/openai/v1",
    [switch]$ImportApiSecrets,
    [switch]$ImportApiImage,
    [switch]$BuildApiFromGitHub,
    [switch]$DeployApi,
    [switch]$RefreshChat,
    [switch]$DeployOpenAiModels,
    [switch]$FinishPayGMirror,
    [switch]$SetConnectionStringsInteractive,
    [switch]$UsePaygStorageForApi,
    [switch]$All
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")

function Ensure-PaygContext {
    Write-Host "==> PAYG $PaygSubscriptionId" -ForegroundColor Cyan
    az account set --subscription $PaygSubscriptionId | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "az account set PAYG falló. az login --tenant $PaygTenantId" }
}

if ($All) {
    $ImportApiSecrets = $true
    $BuildApiFromGitHub = $true
    $DeployApi = $true
    $RefreshChat = $true
}

if ($FinishPayGMirror) {
    $DeployOpenAiModels = $true
    $RefreshChat = $true
}

if ($SetConnectionStringsInteractive) {
    Ensure-PaygContext
    $connArgs = @("-NoProfile", "-File", (Join-Path $ScriptDir "Set-IgniteApiConnectionStringsPayG.ps1"), "-Interactive")
    if ($UsePaygStorageForApi) { $connArgs += "-UsePaygStorageAccount" }
    $connArgs += "-StorageOnly"
    & pwsh @connArgs
    return
}

if (-not ($ImportApiSecrets -or $ImportApiImage -or $BuildApiFromGitHub -or $DeployApi -or $RefreshChat -or $DeployOpenAiModels -or $FinishPayGMirror)) {
    Write-Host @"
Uso (PowerShell):

  cd `"$RepoRoot`"
  az login --tenant $PaygTenantId
  az account set --subscription $PaygSubscriptionId

  # 1) Secretos API (13 claves)
  pwsh -File .\scripts\Complete-IgniteMirrorPayG.ps1 -ImportApiSecrets

  # 1b) Solo Storage PAYG (sin Service Bus / Data Lake)
  pwsh -File .\scripts\Complete-IgniteMirrorPayG.ps1 -SetConnectionStringsInteractive -UsePaygStorageForApi

  # Cierre espejo: modelos Foundry + KV OpenAI API/Chat + redeploy Chat
  pwsh -File .\scripts\Complete-IgniteMirrorPayG.ps1 -FinishPayGMirror

  # 2) Imagen ignite-api SIN Students (build desde GitHub Razor2296/IgniteAPI)
  pwsh -File .\scripts\Complete-IgniteMirrorPayG.ps1 -BuildApiFromGitHub

  # 3) Container App ignite-api
  pwsh -File .\scripts\Complete-IgniteMirrorPayG.ps1 -DeployApi

  # 4) Foundry PAYG en Chat + redeploy
  pwsh -File .\scripts\Complete-IgniteMirrorPayG.ps1 -RefreshChat

  # 4b) Model deployments Students -> PAYG (quota en Portal si falla)
  pwsh -File .\scripts\Complete-IgniteMirrorPayG.ps1 -DeployOpenAiModels

  # O todo junto:
  pwsh -File .\scripts\Complete-IgniteMirrorPayG.ps1 -All

Connection strings: edita secrets\kvsecret2296-migrate.env (copia desde Portal KV-Secret2296).
"@ -ForegroundColor Cyan
    return
}

function Ensure-MigrateEnvTemplate {
    $migrate = Join-Path $RepoRoot "secrets\kvsecret2296-migrate.env"
    $example = Join-Path $RepoRoot "secrets\kvsecret2296-migrate.env.example"
    if (-not (Test-Path $migrate) -and (Test-Path $example)) {
        Copy-Item -LiteralPath $example -Destination $migrate
        Write-Host "Creado $migrate — rellena las 3 connection strings y vuelve a -ImportApiSecrets." -ForegroundColor Yellow
    }
    return $migrate
}

if ($FinishPayGMirror) {
    Ensure-PaygContext
    & pwsh -NoProfile -File (Join-Path $ScriptDir "Set-IgniteApiAzureOpenAiPayG.ps1")
    & pwsh -NoProfile -File (Join-Path $ScriptDir "Set-IgniteChatAzureOpenAiPayG.ps1")
}

if ($DeployOpenAiModels -or $FinishPayGMirror) {
    Ensure-PaygContext
    & pwsh -NoProfile -File (Join-Path $ScriptDir "Deploy-IgniteOpenAiModelsPayG.ps1")
}

if ($ImportApiSecrets) {
    Ensure-PaygContext
    $null = Ensure-MigrateEnvTemplate
    & pwsh -NoProfile -File (Join-Path $ScriptDir "Grant-IgniteApiKeyVaultAccess.ps1")
    & pwsh -NoProfile -File (Join-Path $ScriptDir "Import-IgniteApiSecretsToPayG.ps1") `
        -CopyFromChatVault -AlsoReadAppDotEnv -UseChatIgniteKeyAsMaster -ReplicateMasterIgniteKeys
    Write-Host "Sincronizando Azure OpenAI PAYG (API + Chat Foundry -> KV) ..." -ForegroundColor Cyan
    & pwsh -NoProfile -File (Join-Path $ScriptDir "Set-IgniteApiAzureOpenAiPayG.ps1")
    & pwsh -NoProfile -File (Join-Path $ScriptDir "Set-IgniteChatAzureOpenAiPayG.ps1")
    $migrate = Join-Path $RepoRoot "secrets\kvsecret2296-migrate.env"
    if (Test-Path $migrate) {
        $hasConn = Select-String -Path $migrate -Pattern '^AZURE-STORAGE-CONNECTION-STRING=+.+' -Quiet
        if ($hasConn) {
            Write-Host "Aplicando secrets\kvsecret2296-migrate.env (connection strings)..." -ForegroundColor Cyan
            & pwsh -NoProfile -File (Join-Path $ScriptDir "Import-IgniteApiSecretsToPayG.ps1") -EnvFile $migrate
        }
        else {
            Write-Host "kvsecret2296-migrate.env existe pero faltan valores de connection strings (Portal KV-Secret2296)." -ForegroundColor Yellow
        }
    }
}

if ($ImportApiImage) {
    Ensure-PaygContext
    Write-Host "==> Import ignite-api desde ACR Students (solo si tienes password)" -ForegroundColor Cyan
    & pwsh -NoProfile -File (Join-Path $ScriptDir "Import-IgniteApiImagePayG.ps1") -Interactive
}

if ($BuildApiFromGitHub) {
    Ensure-PaygContext
    Write-Host "==> Build ignite-api desde GitHub (Razor2296/IgniteAPI) -> PAYG ACR" -ForegroundColor Cyan
    & pwsh -NoProfile -File (Join-Path $ScriptDir "Build-Push-IgniteApiFromGitHub.ps1")
}

if ($DeployApi) {
    Ensure-PaygContext
    & pwsh -NoProfile -File (Join-Path $ScriptDir "Deploy-IgniteApiAca.ps1") -SkipBuild
}

if ($RefreshChat) {
    Ensure-PaygContext
    if (-not $FinishPayGMirror) {
        & pwsh -NoProfile -File (Join-Path $ScriptDir "Set-IgniteChatAzureOpenAiPayG.ps1")
    }
    $master = az keyvault secret show --vault-name kvsecret2296siu --name IGNITE-MASTER-API-KEY --query value -o tsv 2>$null
    if ($master) {
        Write-Host "Replicando IGNITE-EXTRACTION-API-KEY en kvignitechatsiu (master ignite-api) ..." -ForegroundColor Cyan
        az keyvault secret set --vault-name kvignitechatsiu --name IGNITE-EXTRACTION-API-KEY --value $master -o none
    }
    & pwsh -NoProfile -File (Join-Path $ScriptDir "Deploy-IgniteChatAca.ps1") -SkipBuild
}

if ($DeployApi) {
    Ensure-PaygContext
    $fqdn = az containerapp show -g IgniteAPI -n ignite-api --query "properties.configuration.ingress.fqdn" -o tsv 2>$null
    if ($fqdn) {
        Write-Host ""
        Write-Host "ignite-api: https://$fqdn" -ForegroundColor Green
        Write-Host "Prueba health (ajusta puerto/ruta si aplica):" -ForegroundColor Cyan
        Write-Host '  $h=@{ "X-API-Key" = (az keyvault secret show --vault-name kvsecret2296siu --name IGNITE-MASTER-API-KEY -o tsv --query value) }'
        Write-Host "  Invoke-RestMethod -Uri `"https://$fqdn/health`" -Headers `$h"
    }
}

Write-Host ""
Write-Host "Listo." -ForegroundColor Green

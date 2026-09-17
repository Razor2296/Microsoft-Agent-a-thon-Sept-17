<#
.SYNOPSIS
  Upload Ignite API secrets into kvsecret2296siu (PAYG).

.EXAMPLE
  az account set --subscription 4a614b14-fa98-4088-b2ec-dd6e3cc593bd
  pwsh -File .\scripts\Import-IgniteApiSecretsToPayG.ps1 -CopyFromChatVault -AlsoReadAppDotEnv
#>
[CmdletBinding()]
param(
    [string]$PaygSubscriptionId = "4a614b14-fa98-4088-b2ec-dd6e3cc593bd",
    [string]$TargetVault = "kvsecret2296siu",
    [string]$ChatVault = "kvignitechatsiu",
    [string]$EnvFile = "",
    [switch]$CopyFromChatVault,
    [switch]$AlsoReadAppDotEnv,
    [switch]$UseChatIgniteKeyAsMaster,
    [switch]$ReplicateMasterIgniteKeys,
    [switch]$SkipServiceBusAndDataLake = $true
)

$ErrorActionPreference = "Stop"

$expected = @(
    "ANTHROPIC-API-KEY", "AZURE-DATALAKE-CONNECTION-STRING", "AZURE-OPENAI-API-KEY",
    "AZURE-OPENAI-ENDPOINT", "AZURE-SERVICE-BUS-CONNECTION-STRING", "AZURE-STORAGE-CONNECTION-STRING",
    "DEEPSEEK-API-KEY", "GEMINI-API-KEY", "GROK-API-KEY", "IGNITE-AUDIO-API-KEY",
    "IGNITE-DOC-API-KEY", "IGNITE-IMAGE-API-KEY", "IGNITE-MASTER-API-KEY", "IGNITE-VIDEO-API-KEY",
    "OPENAI-API-KEY", "PERPLEXITY-API-KEY"
)

$sharedWithChatVault = @(
    "ANTHROPIC-API-KEY", "AZURE-OPENAI-API-KEY", "AZURE-OPENAI-ENDPOINT",
    "DEEPSEEK-API-KEY", "GEMINI-API-KEY", "GROK-API-KEY", "OPENAI-API-KEY", "PERPLEXITY-API-KEY"
)

function Read-DotEnvFile {
    param([string]$Path)
    $out = @{}
    if (-not (Test-Path $Path)) { return $out }
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { return }
        $k = $line.Substring(0, $idx).Trim()
        $v = $line.Substring($idx + 1).Trim().Trim('"').Trim("'")
        if ($v) { $out[$k] = $v }
    }
    return $out
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if ([string]::IsNullOrWhiteSpace($EnvFile)) {
    $EnvFile = Join-Path $repoRoot "secrets\kvsecret2296-migrate.env"
}

$alias = @{
    "ANTHROPIC_API_KEY" = "ANTHROPIC-API-KEY"
    "AZURE_DATALAKE_CONNECTION_STRING" = "AZURE-DATALAKE-CONNECTION-STRING"
    "AZURE_OPENAI_API_KEY" = "AZURE-OPENAI-API-KEY"
    "AZURE_OPENAI_ENDPOINT" = "AZURE-OPENAI-ENDPOINT"
    "AZURE_SERVICE_BUS_CONNECTION_STRING" = "AZURE-SERVICE-BUS-CONNECTION-STRING"
    "AZURE_STORAGE_CONNECTION_STRING" = "AZURE-STORAGE-CONNECTION-STRING"
    "DEEPSEEK_API_KEY" = "DEEPSEEK-API-KEY"
    "GEMINI_API_KEY" = "GEMINI-API-KEY"
    "GROK_API_KEY" = "GROK-API-KEY"
    "IGNITE_AUDIO_API_KEY" = "IGNITE-AUDIO-API-KEY"
    "IGNITE_DOC_API_KEY" = "IGNITE-DOC-API-KEY"
    "IGNITE_IMAGE_API_KEY" = "IGNITE-IMAGE-API-KEY"
    "IGNITE_MASTER_API_KEY" = "IGNITE-MASTER-API-KEY"
    "IGNITE_VIDEO_API_KEY" = "IGNITE-VIDEO-API-KEY"
    "OPENAI_API_KEY" = "OPENAI-API-KEY"
    "PERPLEXITY_API_KEY" = "PERPLEXITY-API-KEY"
}

$byKv = @{}
foreach ($path in @($EnvFile, $(if ($AlsoReadAppDotEnv) { Join-Path $repoRoot "app\.env" }))) {
    if (-not $path) { continue }
    $raw = Read-DotEnvFile -Path $path
    foreach ($k in $raw.Keys) {
        if ($expected -contains $k) { $byKv[$k] = $raw[$k]; continue }
        if ($alias.ContainsKey($k)) { $byKv[$alias[$k]] = $raw[$k] }
    }
}

az account set --subscription $PaygSubscriptionId | Out-Null

if ($CopyFromChatVault) {
    Write-Host "Copying provider keys from $ChatVault ..." -ForegroundColor Cyan
    foreach ($name in $sharedWithChatVault) {
        if ($byKv.ContainsKey($name)) { continue }
        $val = az keyvault secret show --vault-name $ChatVault --name $name --query value -o tsv 2>$null
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($val)) {
            $byKv[$name] = $val
            Write-Host "  from chat vault: $name" -ForegroundColor DarkGray
        }
    }
    if ($UseChatIgniteKeyAsMaster -and -not $byKv.ContainsKey("IGNITE-MASTER-API-KEY")) {
        $mk = az keyvault secret show --vault-name $ChatVault --name "IGNITE-API-KEY" --query value -o tsv 2>$null
        if ($LASTEXITCODE -eq 0 -and $mk) {
            $byKv["IGNITE-MASTER-API-KEY"] = $mk
            Write-Host "  IGNITE-MASTER-API-KEY from chat IGNITE-API-KEY" -ForegroundColor DarkGray
        }
    }
}

if ($SkipServiceBusAndDataLake) {
    foreach ($skip in @("AZURE-SERVICE-BUS-CONNECTION-STRING", "AZURE-DATALAKE-CONNECTION-STRING")) {
        if ($byKv.ContainsKey($skip)) {
            $byKv.Remove($skip)
            Write-Host "  omit $skip (PAYG mirror skips async/Data Lake infra)" -ForegroundColor DarkGray
        }
    }
}

if ($ReplicateMasterIgniteKeys) {
    $master = $byKv["IGNITE-MASTER-API-KEY"]
    if (-not $master) {
        $master = az keyvault secret show --vault-name $TargetVault --name "IGNITE-MASTER-API-KEY" --query value -o tsv 2>$null
    }
    if ($master) {
        foreach ($n in @("IGNITE-AUDIO-API-KEY", "IGNITE-DOC-API-KEY", "IGNITE-IMAGE-API-KEY", "IGNITE-VIDEO-API-KEY")) {
            if (-not $byKv.ContainsKey($n)) { $byKv[$n] = $master }
        }
        Write-Host "Reusing IGNITE-MASTER-API-KEY for AUDIO/DOC/IMAGE/VIDEO keys." -ForegroundColor Cyan
    }
}

if ($byKv.Count -eq 0) {
    throw @"
No secret values found. Run:
  pwsh -File .\scripts\Complete-IgniteMirrorPayG.ps1 -ImportApiSecrets
Or:
  pwsh -File .\scripts\Import-IgniteApiSecretsToPayG.ps1 -CopyFromChatVault -UseChatIgniteKeyAsMaster -ReplicateMasterIgniteKeys
"@
}

$written = 0
foreach ($name in $expected) {
    if (-not $byKv.ContainsKey($name)) {
        Write-Host "  skip $name (no value yet)" -ForegroundColor Yellow
        continue
    }
    az keyvault secret set --vault-name $TargetVault --name $name --value $byKv[$name] -o none
    if ($LASTEXITCODE -ne 0) { throw "Failed writing $name (run Grant-IgniteApiKeyVaultAccess.ps1)" }
    Write-Host "  wrote $name" -ForegroundColor DarkGray
    $written++
}

Write-Host "Done. Wrote $written / $($expected.Count) secrets to $TargetVault." -ForegroundColor Green
$missing = @($expected | Where-Object { -not $byKv.ContainsKey($_) })
if ($missing.Count -gt 0) {
    Write-Host "Still missing (add to migrate.env or Portal): $($missing -join ', ')" -ForegroundColor Yellow
}

<#
.SYNOPSIS
  Upload provider secrets into kvignitechatsiu when Students vault GET is blocked.

.DESCRIPTION
  Reads KEY=VALUE lines from a local file (never commit). Maps desktop env names to
  Key Vault secret names used by Deploy-IgniteChatAca.ps1.

.EXAMPLE
  az account set --subscription 4a614b14-fa98-4088-b2ec-dd6e3cc593bd
  pwsh -File .\scripts\Grant-IgniteChatKeyVaultAccess.ps1
  pwsh -File .\scripts\Import-IgniteChatSecretsToPayG.ps1 -EnvFile .\secrets\kvignitechat-migrate.env
#>
[CmdletBinding()]
param(
    [string]$PaygSubscriptionId = "4a614b14-fa98-4088-b2ec-dd6e3cc593bd",
    [string]$TargetVault = "kvignitechatsiu",
    [string]$EnvFile = "",
    [switch]$AlsoReadAppDotEnv
)

$ErrorActionPreference = "Stop"

# Env var (file) -> Key Vault secret name
$map = [ordered]@{
    "IGNITE_API_KEY"         = "IGNITE-API-KEY"
    "GEMINI_API_KEY"         = "GEMINI-API-KEY"
    "OPENAI_API_KEY"         = "OPENAI-API-KEY"
    "AZURE_OPENAI_API_KEY"   = "AZURE-OPENAI-API-KEY"
    "AZURE_OPENAI_ENDPOINT"  = "AZURE-OPENAI-ENDPOINT"
    "ANTHROPIC_API_KEY"      = "ANTHROPIC-API-KEY"
    "PERPLEXITY_API_KEY"     = "PERPLEXITY-API-KEY"
    "GROK_API_KEY"           = "GROK-API-KEY"
    "DEEPSEEK_API_KEY"       = "DEEPSEEK-API-KEY"
}

function Read-DotEnvFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return @{} }
    $out = @{}
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
    $EnvFile = Join-Path $repoRoot "secrets\kvignitechat-migrate.env"
}

$values = @{}
foreach ($path in @($EnvFile, $(if ($AlsoReadAppDotEnv) { Join-Path $repoRoot "app\.env" }))) {
    if (-not $path) { continue }
    $parsed = Read-DotEnvFile -Path $path
    foreach ($k in $parsed.Keys) { $values[$k] = $parsed[$k] }
}

if ($values.Count -eq 0) {
    throw @"
No secrets found. Create $EnvFile with lines like:
  GEMINI_API_KEY=...
  OPENAI_API_KEY=...
Or copy values from Azure Portal (kvignitechat -> each secret -> Show) while Students sub is active,
or re-enable Azure for Students and run Copy-IgniteChatSecretsStudentsToPayG.ps1.
Use -AlsoReadAppDotEnv if your app\.env already has provider keys.
"@
}

az account set --subscription $PaygSubscriptionId | Out-Null
$written = 0
foreach ($envKey in $map.Keys) {
    if (-not $values.ContainsKey($envKey)) { continue }
    $kvName = $map[$envKey]
    az keyvault secret set --vault-name $TargetVault --name $kvName --value $values[$envKey] -o none
    if ($LASTEXITCODE -ne 0) {
        throw "Failed writing $kvName (run Grant-IgniteChatKeyVaultAccess.ps1)"
    }
    Write-Host "  wrote $kvName" -ForegroundColor DarkGray
    $written++
}

if ($written -eq 0) {
    throw "File had entries but none matched expected keys: $($map.Keys -join ', ')"
}
Write-Host "Done. $written secrets uploaded to $TargetVault." -ForegroundColor Green
Write-Host "Restart ACA revision if providers still fail: Deploy-IgniteChatAca.ps1 -SkipBuild" -ForegroundColor Cyan

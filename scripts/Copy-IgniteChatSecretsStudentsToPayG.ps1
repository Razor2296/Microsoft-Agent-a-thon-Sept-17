<#
.SYNOPSIS
  Copy kvignitechat secrets (Students) into kvignitechatsiu (PAYG).

.NOTES
  Run in PowerShell after:
    az login --tenant 3209b50b-b79b-43dc-9fc4-8d42c406dd61
  You must see Azure for Students when listing secrets from kvignitechat.
  Then the script switches to PAYG and writes secrets (same login if both subs visible).
#>
[CmdletBinding()]
param(
    [string]$StudentsSubscriptionId = "3636d316-ce18-4497-99d7-ec747ffc4289",
    [string]$PaygSubscriptionId = "4a614b14-fa98-4088-b2ec-dd6e3cc593bd",
    [string]$SourceVault = "kvignitechat",
    [string]$TargetVault = "kvignitechatsiu"
)

$ErrorActionPreference = "Stop"

Write-Host "Reading from $SourceVault (Students)..." -ForegroundColor Cyan
Write-Host "  az login --tenant 3209b50b-b79b-43dc-9fc4-8d42c406dd61  (usil.pe)" -ForegroundColor DarkGray
az account set --subscription $StudentsSubscriptionId | Out-Null
$names = az keyvault secret list --vault-name $SourceVault --query "[].name" -o tsv
if (-not $names) { throw "No secrets listed. Use: az login --tenant 3209b50b-b79b-43dc-9fc4-8d42c406dd61" }

$probe = ($names -split "`n" | Where-Object { $_.Trim() } | Select-Object -First 1).Trim()
$probeVal = az keyvault secret show --vault-name $SourceVault --name $probe --query value -o tsv 2>&1
if ($LASTEXITCODE -ne 0 -and ($probeVal -match "subscription associated with this vault has been disabled")) {
    throw @"
Students subscription is disabled for Key Vault GET (list works, values do not).
Fix: Azure Portal -> Azure for Students -> re-enable subscription, then re-run this script.
Or use Portal (kvignitechat -> Show on each secret) + Import-IgniteChatSecretsToPayG.ps1
Or: pwsh -File .\scripts\Import-IgniteChatSecretsToPayG.ps1 -AlsoReadAppDotEnv
"@
}

$pairs = @()
foreach ($sn in ($names -split "`n")) {
    $sn = $sn.Trim()
    if (-not $sn) { continue }
    $val = az keyvault secret show --vault-name $SourceVault --name $sn --query value -o tsv
    if ($LASTEXITCODE -ne 0) { throw "Failed reading $sn from $SourceVault" }
    $pairs += [pscustomobject]@{ Name = $sn; Value = $val }
    Write-Host "  read $sn" -ForegroundColor DarkGray
}

Write-Host "Writing to $TargetVault (PAYG)..." -ForegroundColor Cyan
Write-Host "  If ForbiddenByRbac: pwsh -File .\scripts\Grant-IgniteChatKeyVaultAccess.ps1" -ForegroundColor DarkGray
az account set --subscription $PaygSubscriptionId | Out-Null
foreach ($p in $pairs) {
    az keyvault secret set --vault-name $TargetVault --name $p.Name --value $p.Value -o none
    if ($LASTEXITCODE -ne 0) {
        throw "Failed writing $($p.Name) to $TargetVault (run Grant-IgniteChatKeyVaultAccess.ps1 on PAYG login)"
    }
    Write-Host "  wrote $($p.Name)" -ForegroundColor DarkGray
}
Write-Host "Done. $($pairs.Count) secrets copied." -ForegroundColor Green

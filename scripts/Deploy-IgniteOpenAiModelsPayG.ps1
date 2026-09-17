<#
.SYNOPSIS
  Mirror Azure OpenAI deployments from Students Foundry accounts onto PAYG.

.DESCRIPTION
  Source (Students sub 3636d316-ce18-4497-99d7-ec747ffc4289):
    IgniteChat / foundryignitechat
    IgniteAPI  / igniteapiazfoundry2296

  Target (PAYG sub 4a614b14-fa98-4088-b2ec-dd6e3cc593bd):
    IgniteChat / foundryignitechatsiu
    IgniteAPI  / igniteapifoundry2296

  Idempotent: skips deployments that already exist (same name on target).

.EXAMPLE
  az login --tenant 19b73b1f-8603-4b51-ac82-5b17f03d2820
  az account set --subscription 4a614b14-fa98-4088-b2ec-dd6e3cc593bd
  pwsh -File .\scripts\Deploy-IgniteOpenAiModelsPayG.ps1
#>
[CmdletBinding()]
param(
    [string]$PayGSubscriptionId = "4a614b14-fa98-4088-b2ec-dd6e3cc593bd",
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

function Assert-AzCliSession {
    az account show -o none 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI not signed in. Run: az login --tenant 19b73b1f-8603-4b51-ac82-5b17f03d2820"
    }
}

# Captured from Students (foundryignitechat + igniteapiazfoundry2296)
$TargetPlans = @(
    @{
        ResourceGroup = "IgniteChat"
        AccountName   = "foundryignitechatsiu"
        Deployments   = @(
            @{ Name = "gpt-5.6-sol"; Model = "gpt-5.6-sol"; Version = "2026-07-09"; Sku = "GlobalStandard"; Capacity = 500 },
            @{ Name = "gpt-5.6-luna"; Model = "gpt-5.6-luna"; Version = "2026-07-09"; Sku = "GlobalStandard"; Capacity = 500 },
            @{ Name = "gpt-5.6-terra"; Model = "gpt-5.6-terra"; Version = "2026-07-09"; Sku = "GlobalStandard"; Capacity = 500 },
            @{ Name = "gpt-4.1-mini"; Model = "gpt-4.1-mini"; Version = "2025-04-14"; Sku = "GlobalStandard"; Capacity = 2450 },
            @{ Name = "o3"; Model = "o3"; Version = "2025-04-16"; Sku = "GlobalStandard"; Capacity = 500 },
            @{ Name = "gpt-6-astra"; Model = "gpt-6-astra"; Version = "2026-09-03"; Sku = "GlobalStandard"; Capacity = 500 }
        )
    },
    @{
        ResourceGroup = "IgniteAPI"
        AccountName   = "igniteapifoundry2296"
        Deployments   = @(
            @{ Name = "gpt-5-mini"; Model = "gpt-5-mini"; Version = "2025-08-07"; Sku = "GlobalStandard"; Capacity = 250 },
            @{ Name = "gpt-4.1-mini"; Model = "gpt-4.1-mini"; Version = "2025-04-14"; Sku = "GlobalStandard"; Capacity = 100 },
            @{ Name = "gpt-audio-mini"; Model = "gpt-audio-mini"; Version = "2025-12-15"; Sku = "GlobalStandard"; Capacity = 30 },
            @{ Name = "whisper"; Model = "whisper"; Version = "001"; Sku = "Standard"; Capacity = 2 }
        )
    }
)

Assert-AzCliSession
az account set --subscription $PayGSubscriptionId | Out-Null
if ($LASTEXITCODE -ne 0) { throw "az account set failed for $PayGSubscriptionId" }

foreach ($plan in $TargetPlans) {
    $rg = $plan.ResourceGroup
    $account = $plan.AccountName
    $existing = @(az cognitiveservices account deployment list -g $rg -n $account --query "[].name" -o tsv 2>$null)
    Write-Host "`n=== $rg / $account (existing: $($existing -join ', ')) ===" -ForegroundColor Cyan

    foreach ($d in $plan.Deployments) {
        if ($existing -contains $d.Name) {
            Write-Host "  SKIP $($d.Name) (already deployed)" -ForegroundColor DarkGray
            continue
        }

        $cmd = @(
            "cognitiveservices", "account", "deployment", "create",
            "-g", $rg,
            "-n", $account,
            "--deployment-name", $d.Name,
            "--model-name", $d.Model,
            "--model-version", $d.Version,
            "--model-format", "OpenAI",
            "--sku-name", $d.Sku,
            "--sku-capacity", [string]$d.Capacity
        )

        if ($WhatIf) {
            Write-Host "  WHATIF: az $($cmd -join ' ')" -ForegroundColor Yellow
            continue
        }

        Write-Host "  CREATE $($d.Name) ($($d.Model) $($d.Version), $($d.Sku) cap=$($d.Capacity)) ..." -ForegroundColor Green
        az @cmd -o none
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  FAILED $($d.Name) — see error above (often InsufficientQuota on PAYG or deprecating model)." -ForegroundColor Red
            Write-Host "    Portal: Azure OpenAI / Foundry -> Quotas -> request TPM for this model on subscription $PayGSubscriptionId" -ForegroundColor DarkYellow
        }
    }
}

Write-Host "`nDone. Run Set-IgniteApiAzureOpenAiPayG.ps1 if KV not synced yet." -ForegroundColor Cyan

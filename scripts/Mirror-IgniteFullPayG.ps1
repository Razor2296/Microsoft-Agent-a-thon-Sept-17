<#
.SYNOPSIS
  Run full PAYG mirror: Chat stack + API stack (orchestrator).

.EXAMPLE
  az login --tenant 19b73b1f-8603-4b51-ac82-5b17f03d2820
  az account set --subscription 4a614b14-fa98-4088-b2ec-dd6e3cc593bd
  pwsh -File .\scripts\Mirror-IgniteFullPayG.ps1
#>
[CmdletBinding()]
param(
    [switch]$ImportIgniteApiImage
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot

Write-Host "=== Chat / shared infra ===" -ForegroundColor Cyan
& pwsh -NoProfile -File (Join-Path $here "Mirror-IgniteStackPayG.ps1")

Write-Host "=== Ignite API infra (KV + Foundry) ===" -ForegroundColor Cyan
$apiArgs = @("-NoProfile", "-File", (Join-Path $here "Mirror-IgniteApiPayG.ps1"))
if ($ImportIgniteApiImage) { $apiArgs += "-ImportIgniteApiImage" }
& pwsh @apiArgs

Write-Host ""
Write-Host "Manual steps (Students sub often blocks KV GET + CAE suspended):" -ForegroundColor Yellow
Write-Host "  1. secrets\kvsecret2296-migrate.env  -> Import-IgniteApiSecretsToPayG.ps1"
Write-Host "  2. az acr import ignite-api:latest from caacc1441625acr (Students login)"
Write-Host "  3. Export-IgniteApiFromStudents.ps1 (if CAE up) OR Deploy-IgniteApiAca.ps1 defaults"
Write-Host "  4. pwsh -File .\scripts\Complete-IgniteMirrorPayG.ps1 -FinishPayGMirror"
Write-Host "     (Foundry models + Set-IgniteChatAzureOpenAiPayG + Chat redeploy; no Service Bus/Data Lake)"

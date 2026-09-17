<#
.SYNOPSIS
  Create Ignite API mirror resources on PAYG (KV, Foundry, optional ACR image import).

.EXAMPLE
  az login --tenant 19b73b1f-8603-4b51-ac82-5b17f03d2820
  pwsh -File .\scripts\Mirror-IgniteApiPayG.ps1
  pwsh -File .\scripts\Mirror-IgniteApiPayG.ps1 -ImportIgniteApiImage  # needs Students ACR creds
#>
[CmdletBinding()]
param(
    [string]$PaygSubscriptionId = "4a614b14-fa98-4088-b2ec-dd6e3cc593bd",
    [string]$AcrName = "igniteapisiuacr",
    [string]$KeyVaultApi = "kvsecret2296siu",
    [string]$FoundryChatName = "foundryignitechatsiu",
    [string]$FoundryApiName = "igniteapifoundry2296",
    [string]$SourceAcr = "caacc1441625acr.azurecr.io",
    [string]$SourceImage = "ignite-api:latest",
    [switch]$ImportIgniteApiImage
)

$ErrorActionPreference = "Stop"

function Invoke-Az {
    param([Parameter(Mandatory)][string[]]$AzArgs)
    & az @AzArgs
    if ($LASTEXITCODE -ne 0) { throw "az failed: az $($AzArgs -join ' ')" }
}

Invoke-Az -AzArgs @("account", "set", "--subscription", $PaygSubscriptionId)
$userOid = az ad signed-in-user show --query id -o tsv

$kv = az keyvault show -g IgniteAPI -n $KeyVaultApi --query name -o tsv 2>$null
if (-not $kv) {
    Write-Host "Creating Key Vault $KeyVaultApi ..." -ForegroundColor Cyan
    Invoke-Az -AzArgs @(
        "keyvault", "create", "-g", "IgniteAPI", "-n", $KeyVaultApi, "-l", "eastus2",
        "--sku", "standard", "--enable-rbac-authorization", "true", "-o", "none"
    )
    Invoke-Az -AzArgs @(
        "role", "assignment", "create",
        "--assignee-object-id", $userOid, "--assignee-principal-type", "User",
        "--role", "Key Vault Secrets Officer",
        "--scope", (az keyvault show -g IgniteAPI -n $KeyVaultApi --query id -o tsv),
        "-o", "none"
    )
}

foreach ($pair in @(
        @{ Rg = "IgniteChat"; Name = $FoundryChatName; Loc = "eastus" }
        @{ Rg = "IgniteAPI"; Name = $FoundryApiName; Loc = "eastus2" }
    )) {
    $exists = az cognitiveservices account show -g $pair.Rg -n $pair.Name --query name -o tsv 2>$null
    if ($exists) { continue }
    Write-Host "Creating Foundry/OpenAI account $($pair.Name) in $($pair.Rg) ..." -ForegroundColor Cyan
    Invoke-Az -AzArgs @(
        "cognitiveservices", "account", "create",
        "-g", $pair.Rg, "-n", $pair.Name, "-l", $pair.Loc,
        "--kind", "OpenAI", "--sku", "S0", "--yes", "-o", "none"
    )
}

if ($ImportIgniteApiImage) {
    Write-Host "Importing $SourceImage -> $AcrName ..." -ForegroundColor Cyan
    $user = az acr credential show -n caacc1441625acr -g IgniteAPI --subscription 3636d316-ce18-4497-99d7-ec747ffc4289 --query username -o tsv 2>$null
    $pass = az acr credential show -n caacc1441625acr -g IgniteAPI --subscription 3636d316-ce18-4497-99d7-ec747ffc4289 --query "passwords[0].value" -o tsv 2>$null
    if (-not $user) {
        Write-Host "Login Students + enable ACR admin, or pass creds manually:" -ForegroundColor Yellow
        Write-Host "  az acr import -n $AcrName -g IgniteAPI --source $SourceAcr/$SourceImage --username USER --password PASS"
    }
    else {
        Invoke-Az -AzArgs @(
            "acr", "import", "-n", $AcrName, "-g", "IgniteAPI",
            "--source", "$SourceAcr/$SourceImage",
            "--username", $user, "--password", $pass, "-o", "none"
        )
    }
}

$chatEp = az cognitiveservices account show -g IgniteChat -n $FoundryChatName --query "properties.endpoint" -o tsv 2>$null
$apiEp = az cognitiveservices account show -g IgniteAPI -n $FoundryApiName --query "properties.endpoint" -o tsv 2>$null
Write-Host ""
Write-Host "Ignite API mirror (PAYG) bootstrap done." -ForegroundColor Green
Write-Host "  KV: $KeyVaultApi"
Write-Host "  Foundry Chat: $FoundryChatName -> $chatEp"
Write-Host "  Foundry API:  $FoundryApiName -> $apiEp"
Write-Host "Next:"
Write-Host "  1) pwsh -File .\scripts\Import-IgniteApiSecretsToPayG.ps1"
Write-Host "  2) Update AZURE-OPENAI-ENDPOINT in kvignitechatsiu to $chatEp/openai/v1 (if new Foundry)"
Write-Host "  3) pwsh -File .\scripts\Deploy-IgniteApiAca.ps1 -SkipBuild  (after image import)"

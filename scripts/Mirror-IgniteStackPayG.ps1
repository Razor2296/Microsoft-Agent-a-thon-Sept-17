<#
.SYNOPSIS
  Bootstrap IgniteAPI + IgniteChat mirror on San Ignacio PAYG subscription.

.DESCRIPTION
  Old Students tenant keeps global names (caacc1441625acr, kvignitechat, ...).
  PAYG uses igniteapisiuacr until old resources are deleted.
  Copies kvignitechat secrets from Students sub when -CopySecretsFromStudents is set.

.EXAMPLE
  pwsh -File .\scripts\Mirror-IgniteStackPayG.ps1 -CopySecretsFromStudents
#>
[CmdletBinding()]
param(
    [string]$PaygSubscriptionId = "4a614b14-fa98-4088-b2ec-dd6e3cc593bd",
    [string]$StudentsSubscriptionId = "3636d316-ce18-4497-99d7-ec747ffc4289",
    [string]$AcrName = "igniteapisiuacr",
    [string]$LawName = "workspaceigniteapi8417",
    [string]$CaeName = "managedEnvironment-IgniteAPI-862f",
    [string]$StorageAccountName = "ignitechatsiu08d0",
    [string]$KeyVaultChat = "kvignitechatsiu",
    [string]$FileShareName = "ignite-sessions",
    [string]$CaeStorageName = "ignitechat-sessions",
    [switch]$CopySecretsFromStudents,
    [switch]$CreateServicePrincipal
)

$ErrorActionPreference = "Stop"

function Invoke-Az {
    param([Parameter(Mandatory)][string[]]$AzArgs)
    & az @AzArgs
    if ($LASTEXITCODE -ne 0) { throw "az failed: az $($AzArgs -join ' ')" }
}

Write-Host "==> PAYG subscription $PaygSubscriptionId" -ForegroundColor Cyan
Invoke-Az -AzArgs @("account", "set", "--subscription", $PaygSubscriptionId)

foreach ($rg in @("IgniteAPI", "IgniteChat")) {
    $exists = az group exists -n $rg -o tsv
    if ($exists -ne "true") {
        Write-Host "Creating RG $rg (eastus2)..." -ForegroundColor Cyan
        Invoke-Az -AzArgs @("group", "create", "-n", $rg, "-l", "eastus2", "-o", "none")
    }
}

$lawId = az monitor log-analytics workspace show -g IgniteAPI -n $LawName --query id -o tsv 2>$null
if (-not $lawId) {
    Write-Host "Creating Log Analytics $LawName..." -ForegroundColor Cyan
    Invoke-Az -AzArgs @(
        "monitor", "log-analytics", "workspace", "create",
        "-g", "IgniteAPI", "-n", $LawName, "-l", "eastus2",
        "--sku", "PerGB2018", "--retention-time", "30", "-o", "none"
    )
    $lawId = az monitor log-analytics workspace show -g IgniteAPI -n $LawName --query id -o tsv
}

$caeId = az containerapp env show -g IgniteAPI -n $CaeName --query id -o tsv 2>$null
if (-not $caeId) {
    Write-Host "Creating Container Apps environment $CaeName (auto Log Analytics)..." -ForegroundColor Cyan
    Invoke-Az -AzArgs @(
        "containerapp", "env", "create",
        "-g", "IgniteAPI", "-n", $CaeName, "-l", "eastus2", "-o", "none"
    )
    $caeId = az containerapp env show -g IgniteAPI -n $CaeName --query id -o tsv
}

$acrExists = az acr show -g IgniteAPI -n $AcrName --query name -o tsv 2>$null
if (-not $acrExists) {
    Write-Host "Creating ACR $AcrName (eastus, admin enabled)..." -ForegroundColor Cyan
    Invoke-Az -AzArgs @(
        "acr", "create", "-g", "IgniteAPI", "-n", $AcrName, "-l", "eastus",
        "--sku", "Basic", "--admin-enabled", "true", "-o", "none"
    )
}

$stExists = az storage account show -g IgniteChat -n $StorageAccountName --query name -o tsv 2>$null
if (-not $stExists) {
    Write-Host "Creating storage $StorageAccountName..." -ForegroundColor Cyan
    Invoke-Az -AzArgs @(
        "storage", "account", "create",
        "-g", "IgniteChat", "-n", $StorageAccountName, "-l", "eastus2",
        "--sku", "Standard_LRS", "--kind", "StorageV2", "-o", "none"
    )
}

$shareExists = az storage share exists --account-name $StorageAccountName -n $FileShareName --query exists -o tsv 2>$null
if ($shareExists -ne "true") {
    Write-Host "Creating file share $FileShareName..." -ForegroundColor Cyan
    $stKey = az storage account keys list -g IgniteChat -n $StorageAccountName --query "[0].value" -o tsv
    Invoke-Az -AzArgs @(
        "storage", "share", "create",
        "--account-name", $StorageAccountName, "--account-key", $stKey,
        "-n", $FileShareName, "--quota", "5", "-o", "none"
    )
}

$caeSt = az containerapp env storage list -g IgniteAPI -n $CaeName --query "[?name=='$CaeStorageName'].name" -o tsv 2>$null
if (-not $caeSt) {
    Write-Host "Binding CAE storage $CaeStorageName..." -ForegroundColor Cyan
    $stKey = az storage account keys list -g IgniteChat -n $StorageAccountName --query "[0].value" -o tsv
    Invoke-Az -AzArgs @(
        "containerapp", "env", "storage", "set",
        "-g", "IgniteAPI", "-n", $CaeName,
        "--storage-name", $CaeStorageName,
        "--azure-file-account-name", $StorageAccountName,
        "--azure-file-account-key", $stKey,
        "--azure-file-share-name", $FileShareName,
        "--access-mode", "ReadWrite", "-o", "none"
    )
}

$tenantId = az account show --query tenantId -o tsv
$userOid = az ad signed-in-user show --query id -o tsv
$kvExists = az keyvault show -g IgniteChat -n $KeyVaultChat --query name -o tsv 2>$null
if (-not $kvExists) {
    Write-Host "Creating Key Vault $KeyVaultChat..." -ForegroundColor Cyan
    Invoke-Az -AzArgs @(
        "keyvault", "create",
        "-g", "IgniteChat", "-n", $KeyVaultChat, "-l", "eastus2",
        "--sku", "standard", "--enable-rbac-authorization", "false", "-o", "none"
    )
    Invoke-Az -AzArgs @(
        "keyvault", "set-policy", "-n", $KeyVaultChat,
        "--object-id", $userOid,
        "--secret-permissions", "get", "list", "set", "delete", "-o", "none"
    )
}

if ($CopySecretsFromStudents) {
    Write-Host "Copying secrets from Students kvignitechat -> $KeyVaultChat ..." -ForegroundColor Cyan
    Invoke-Az -AzArgs @("account", "set", "--subscription", $StudentsSubscriptionId)
    $oldNames = az keyvault secret list --vault-name kvignitechat --query "[].name" -o tsv
    if (-not $oldNames) { throw "No secrets readable in Students kvignitechat (login as usil.pe?)" }
    $pairs = @()
    foreach ($sn in ($oldNames -split "`n")) {
        $sn = $sn.Trim()
        if (-not $sn) { continue }
        $val = az keyvault secret show --vault-name kvignitechat --name $sn --query value -o tsv
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($val)) {
            throw "Could not read secret $sn from Students kvignitechat (sub enabled? MFA login as usil.pe?)"
        }
        $pairs += @{ Name = $sn; Value = $val }
    }
    Invoke-Az -AzArgs @("account", "set", "--subscription", $PaygSubscriptionId)
    foreach ($p in $pairs) {
        Invoke-Az -AzArgs @("keyvault", "secret", "set", "--vault-name", $KeyVaultChat, "--name", $p.Name, "--value", $p.Value, "-o", "none")
        Write-Host "  copied $($p.Name)" -ForegroundColor DarkGray
    }
}

if ($CreateServicePrincipal) {
    Write-Host "Creating GitHub deploy SP (Contributor on IgniteAPI RG)..." -ForegroundColor Cyan
    $spJson = az ad sp create-for-rbac `
        --name "github-ignitechat-deploy" `
        --role contributor `
        --scopes "/subscriptions/$PaygSubscriptionId/resourceGroups/IgniteAPI" `
        --only-show-errors `
        -o json 2>&1
    if ($LASTEXITCODE -ne 0) { throw $spJson }
    $outPath = Join-Path $env:USERPROFILE ".ignitechat-azure-credentials.json"
    Set-Content -Path $outPath -Value $spJson -Encoding UTF8
    Write-Host "Wrote AZURE_CREDENTIALS JSON to $outPath (add to GitHub secrets; do not commit)." -ForegroundColor Yellow
}

$acrLogin = az acr show -g IgniteAPI -n $AcrName --query loginServer -o tsv
Write-Host ""
Write-Host "Mirror bootstrap complete." -ForegroundColor Green
Write-Host "  Subscription: $PaygSubscriptionId"
Write-Host "  CAE ID:       $caeId"
Write-Host "  ACR:          $acrLogin"
Write-Host "  Key Vault:    $KeyVaultChat"
Write-Host "  Storage:      $StorageAccountName / $FileShareName"
Write-Host ""
Write-Host "Next: pwsh -File .\scripts\Deploy-IgniteChatAca.ps1 -SubscriptionId $PaygSubscriptionId ..." -ForegroundColor Cyan

<#
.SYNOPSIS
  Copia ignite-api:latest del ACR Students al ACR PAYG (sin escribir en sub Students).

.NOTES
  Students disabled = no uses az acr credential show. Portal ACR caacc1441625acr -> Access keys.

.EXAMPLE
  az account set --subscription 4a614b14-fa98-4088-b2ec-dd6e3cc593bd
  pwsh -File .\scripts\Import-IgniteApiImagePayG.ps1 -Interactive
#>
[CmdletBinding()]
param(
    [string]$PaygSubscriptionId = "4a614b14-fa98-4088-b2ec-dd6e3cc593bd",
    [string]$PaygAcr = "igniteapisiuacr",
    [string]$SourceAcr = "caacc1441625acr",
    [string]$ImageName = "ignite-api",
    [string]$ImageTag = "latest",
    [string]$SourceUsername = "",
    [string]$SourcePassword = "",
    [switch]$Interactive,
    [switch]$UseDockerViaWsl
)

$ErrorActionPreference = "Stop"
$sourceServer = "${SourceAcr}.azurecr.io"
$paygServer = "${PaygAcr}.azurecr.io"
$sourceImage = "${sourceServer}/${ImageName}:${ImageTag}"
$paygImage = "${paygServer}/${ImageName}:${ImageTag}"

if ([string]::IsNullOrWhiteSpace($SourceUsername)) {
    $SourceUsername = $SourceAcr
}
if ($Interactive -or [string]::IsNullOrWhiteSpace($SourcePassword)) {
    Write-Host "Portal: ACR $SourceAcr -> Access keys -> password1" -ForegroundColor Cyan
    Write-Host "Username (fijo): $SourceUsername" -ForegroundColor Green
    $secure = Read-Host "Password" -AsSecureString
    $SourcePassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
}

if ([string]::IsNullOrWhiteSpace($SourceUsername) -or [string]::IsNullOrWhiteSpace($SourcePassword)) {
    throw "Faltan credenciales del ACR origen."
}

az account set --subscription $PaygSubscriptionId | Out-Null
az acr update -n $PaygAcr -g IgniteAPI --admin-enabled true | Out-Null

if ($UseDockerViaWsl) {
    Write-Host "Docker WSL: pull $sourceImage -> push $paygImage" -ForegroundColor Cyan
    $paygUser = az acr credential show -n $PaygAcr -g IgniteAPI --query username -o tsv
    $paygPass = az acr credential show -n $PaygAcr -g IgniteAPI --query "passwords[0].value" -o tsv
    $SourcePassword | & wsl -e docker login $sourceServer -u $SourceUsername --password-stdin
    if ($LASTEXITCODE -ne 0) { throw "docker login origen falló" }
    & wsl -e docker pull $sourceImage
    if ($LASTEXITCODE -ne 0) { throw "docker pull falló (sub/ACR deshabilitado o imagen inexistente)" }
    & wsl -e docker tag $sourceImage $paygImage
    $paygPass | & wsl -e docker login $paygServer -u $paygUser --password-stdin
    & wsl -e docker push $paygImage
    if ($LASTEXITCODE -ne 0) { throw "docker push PAYG falló" }
    Write-Host "OK: $paygImage" -ForegroundColor Green
    return
}

Write-Host "az acr import (solo escribe en PAYG) ..." -ForegroundColor Cyan
az acr import `
    -n $PaygAcr -g IgniteAPI `
    --source $sourceImage `
    --username $SourceUsername `
    --password $SourcePassword `
    -o none
if ($LASTEXITCODE -ne 0) {
    Write-Host "az acr import falló. Reintenta con Docker:" -ForegroundColor Yellow
    Write-Host "  pwsh -File .\scripts\Import-IgniteApiImagePayG.ps1 -Interactive -UseDockerViaWsl"
    throw "acr import exit $LASTEXITCODE"
}
Write-Host "OK: $paygImage" -ForegroundColor Green

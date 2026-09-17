<#
.SYNOPSIS
  Clona Razor2296/IgniteAPI, build linux/amd64 en WSL, push a igniteapisiuacr (sin ACR Students).

.EXAMPLE
  az account set --subscription 4a614b14-fa98-4088-b2ec-dd6e3cc593bd
  pwsh -File .\scripts\Build-Push-IgniteApiFromGitHub.ps1
#>
[CmdletBinding()]
param(
    [string]$SubscriptionId = "4a614b14-fa98-4088-b2ec-dd6e3cc593bd",
    [string]$AcrName = "igniteapisiuacr",
    [string]$ImageName = "ignite-api",
    [string]$ImageTag = "latest",
    [string]$CloneDir = "",
    [string]$Repo = "https://github.com/Razor2296/IgniteAPI.git"
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($CloneDir)) {
    $CloneDir = Join-Path $env:TEMP "IgniteAPI-payg-build"
}

az account set --subscription $SubscriptionId | Out-Null
az acr update -n $AcrName -g IgniteAPI --admin-enabled true | Out-Null
$acrServer = az acr show -g IgniteAPI -n $AcrName --query loginServer -o tsv
$acrUser = az acr credential show -n $AcrName -g IgniteAPI --query username -o tsv
$acrPass = az acr credential show -n $AcrName -g IgniteAPI --query "passwords[0].value" -o tsv
$fullImage = "${acrServer}/${ImageName}:${ImageTag}"

if (-not (Test-Path (Join-Path $CloneDir ".git"))) {
    Write-Host "Cloning $Repo -> $CloneDir ..." -ForegroundColor Cyan
    if (Test-Path $CloneDir) { Remove-Item -Recurse -Force $CloneDir }
    gh repo clone Razor2296/IgniteAPI $CloneDir -- --depth 1
}

$wslDir = (& wsl -e wslpath -a $CloneDir).Trim()
Write-Host "Building $fullImage (linux/amd64) in WSL ..." -ForegroundColor Cyan
& wsl -e docker run --privileged --rm tonistiigi/binfmt --install all | Out-Null
$acrPass | & wsl -e docker login $acrServer -u $acrUser --password-stdin
if ($LASTEXITCODE -ne 0) { throw "docker login PAYG ACR failed" }

& wsl -e docker buildx build --platform linux/amd64 --provenance=false --pull -t $fullImage --load $wslDir
if ($LASTEXITCODE -ne 0) { throw "docker build failed" }
& wsl -e docker push $fullImage
if ($LASTEXITCODE -ne 0) { throw "docker push failed" }

Write-Host "OK: $fullImage" -ForegroundColor Green
Write-Host "Siguiente: pwsh -File .\scripts\Deploy-IgniteApiAca.ps1 -SkipBuild -Cpu 2.0 -Memory 4Gi" -ForegroundColor Cyan

<#
.SYNOPSIS
  Build/push Ignite Chat API with WSL Docker using the IgniteAPI runtime host,
  while keeping IgniteChat consumption secrets in RG IgniteChat.

.DESCRIPTION
  - Docker via: wsl -e docker --platform linux/amd64 --provenance=false
  - Shared ACR/CAE live in IgniteAPI (Students allows only 1 CAE)
  - Container App: IgniteAPI/ignitechat-api
  - Secrets vault (consumption): IgniteChat/kvignitechatsiu (PAYG)
  - ACA secrets use keyvaultref + system-assigned managed identity

.EXAMPLE
  pwsh -File .\scripts\Deploy-IgniteChatAca.ps1
  pwsh -File .\scripts\Deploy-IgniteChatAca.ps1 -ApiKey "my-stable-desktop-key"
  pwsh -File .\scripts\Deploy-IgniteChatAca.ps1 -SkipBuild -SkipKeyVaultSync
#>

[CmdletBinding()]
param(
    [string]$SubscriptionId = "4a614b14-fa98-4088-b2ec-dd6e3cc593bd",
    [string]$AppResourceGroup = "IgniteAPI",
    [string]$AcrName = "igniteapisiuacr",
    [string]$AcrResourceGroup = "IgniteAPI",
    [string]$ImageName = "ignitechat-api",
    [string]$ImageTag = "",
    [string]$ContainerAppName = "ignitechat-api",
    [string]$ContainerEnvId = "/subscriptions/4a614b14-fa98-4088-b2ec-dd6e3cc593bd/resourceGroups/IgniteAPI/providers/Microsoft.App/managedEnvironments/managedEnvironment-IgniteAPI-862f",
    [string]$KeyVaultName = "kvignitechatsiu",
    [string]$KeyVaultResourceGroup = "IgniteChat",
    [string]$ApiKey = "",
    [ValidateSet("0.5", "1.0")]
    [string]$Cpu = "1.0",
    [ValidateSet("1Gi", "2Gi")]
    [string]$Memory = "2Gi",
    [string]$FoundryChatEndpoint = "https://foundryignitechatsiu-87996.openai.azure.com/openai/v1",
    [string]$ExtractionApiUrl = "https://ignite-api.orangefield-53e31d49.eastus2.azurecontainerapps.io",
    # PAYG Foundry: only gpt-4.1-mini until quota (Deploy-IgniteOpenAiModelsPayG.ps1). Full Students list:
    # gpt-4.1-mini,gpt-5.6-sol,gpt-5.6-luna,gpt-5.6-terra,o3
    [string]$AzureOpenAiAvailableModels = "gpt-4.1-mini",
    [switch]$SkipBuild,
    [switch]$SkipDeploy,
    [switch]$SkipKeyVaultSync,
    [switch]$SkipWslDockerCheck
)

$ErrorActionPreference = "Stop"

function Assert-Command($Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Invoke-WslDocker {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$DockerArgs)
    Write-Host "==> wsl -e docker $($DockerArgs -join ' ')" -ForegroundColor Cyan
    & wsl -e docker @DockerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "WSL docker failed with exit code $LASTEXITCODE"
    }
}

Assert-Command az
if (-not $SkipBuild -and -not $SkipWslDockerCheck) {
    Assert-Command wsl
    & wsl -e docker version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker inside WSL is not available. Install Docker Engine in your WSL distro first."
    }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$appDir = Join-Path $repoRoot "app"
if (-not (Test-Path (Join-Path $appDir "Dockerfile"))) {
    throw "Dockerfile not found under $appDir"
}

if ([string]::IsNullOrWhiteSpace($ImageTag)) {
    $ImageTag = Get-Date -Format "yyyyMMddHHmmss"
}

Write-Host "Setting Azure subscription $SubscriptionId ..." -ForegroundColor Cyan
az account set --subscription $SubscriptionId | Out-Null

az acr update -n $AcrName -g $AcrResourceGroup --admin-enabled true | Out-Null
$acrServer = az acr show -g $AcrResourceGroup -n $AcrName --query loginServer -o tsv
$acrUser = az acr credential show -n $AcrName -g $AcrResourceGroup --query username -o tsv
$acrPass = az acr credential show -n $AcrName -g $AcrResourceGroup --query "passwords[0].value" -o tsv
$fullImage = "${acrServer}/${ImageName}:${ImageTag}"
$latestImage = "${acrServer}/${ImageName}:latest"

Write-Host "Logging into shared IgniteAPI ACR ($acrServer) via WSL docker ..." -ForegroundColor Cyan
$acrPass | & wsl -e docker login $acrServer -u $acrUser --password-stdin
if ($LASTEXITCODE -ne 0) { throw "docker login failed" }

if (-not $SkipBuild) {
    $wslAppDir = (& wsl -e wslpath -a "$appDir").Trim()
    $wslStageScript = (& wsl -e wslpath -a (Join-Path $repoRoot "scripts\stage-aca-build.sh")).Trim()
    if ($appDir -match '(?i)OneDrive') {
        Write-Host "WARNING: app path is under OneDrive ($appDir)." -ForegroundColor Yellow
        Write-Host "Staging a clean copy inside WSL /tmp to avoid huge/flaky Docker contexts." -ForegroundColor Yellow
    }

    # Stage only what the image needs into a Linux-native temp dir.
    # OneDrive + live log/media folders often inflate the context past 100MB and cancel the sender.
    $stageDir = "/tmp/ignitechat-aca-build"
    $stageRunner = "/tmp/ignitechat-stage-aca-build.sh"
    Write-Host "Preparing WSL staging directory $stageDir ..." -ForegroundColor Cyan
    # OneDrive/Windows checkouts often store *.sh with CRLF; bash then fails on `set -o pipefail\r`.
    # Copy + strip CR into /tmp, then run with explicit argv (paths may contain spaces).
    & wsl -e bash -lc "sed 's/\r$//' '$wslStageScript' > '$stageRunner' && chmod +x '$stageRunner' && bash '$stageRunner' '$wslAppDir' '$stageDir'"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to stage Docker build context in WSL (exit $LASTEXITCODE)"
    }

    $wslArch = (& wsl -e uname -m).Trim()
    Write-Host "WSL arch: $wslArch (target image platform: linux/amd64)" -ForegroundColor Cyan
    # ACA needs linux/amd64. On ARM hosts (or broken binfmt), RUN steps fail with:
    #   exec /bin/sh: exec format error
    # Register QEMU handlers and prefer buildx --load.
    Write-Host "Ensuring QEMU/binfmt for cross-platform amd64 builds ..." -ForegroundColor Cyan
    & wsl -e docker run --privileged --rm tonistiigi/binfmt --install all | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WARNING: binfmt install returned $LASTEXITCODE — continuing; build may still fail on ARM." -ForegroundColor Yellow
    }

    # Drop stale wrong-arch layers that can cause exec format errors even with --platform.
    & wsl -e docker builder prune -f --filter "until=24h" | Out-Null

    Write-Host "Building linux/amd64 image in WSL: $fullImage" -ForegroundColor Cyan
    # Critical: explicit platform + no provenance attestation index (ACA needs linux/amd64)
    # Build from the staged Linux path — not directly from OneDrive.
    $buildxAvailable = $true
    & wsl -e docker buildx version | Out-Null
    if ($LASTEXITCODE -ne 0) { $buildxAvailable = $false }

    if ($buildxAvailable) {
        Invoke-WslDocker buildx build `
            --platform linux/amd64 `
            --provenance=false `
            --pull `
            --load `
            -t $fullImage -t $latestImage `
            -f "$stageDir/Dockerfile" $stageDir
    }
    else {
        Invoke-WslDocker build `
            --platform linux/amd64 `
            --provenance=false `
            --pull `
            -t $fullImage -t $latestImage `
            -f "$stageDir/Dockerfile" $stageDir
    }

    Write-Host "Pushing image tags ..." -ForegroundColor Cyan
    Invoke-WslDocker push $fullImage
    Invoke-WslDocker push $latestImage

    Write-Host "Cleaning WSL staging directory ..." -ForegroundColor DarkGray
    & wsl -e rm -rf $stageDir $stageRunner | Out-Null
}
else {
    Write-Host "SkipBuild set — deploying existing tag $fullImage" -ForegroundColor Yellow
}

if ($SkipDeploy) {
    Write-Host "SkipDeploy set — build/push finished." -ForegroundColor Yellow
    return
}

$exists = az containerapp show -g $AppResourceGroup -n $ContainerAppName --query name -o tsv 2>$null
$shouldSetApiKey = -not [string]::IsNullOrWhiteSpace($ApiKey)

if (-not $exists -and -not $shouldSetApiKey) {
    $ApiKey = -join ((1..48) | ForEach-Object { "{0:x}" -f (Get-Random -Maximum 16) })
    $shouldSetApiKey = $true
    Write-Host "Generated IGNITE_API_KEY (copy it now): $ApiKey" -ForegroundColor Yellow
}
elseif ($shouldSetApiKey) {
    Write-Host "Using provided IGNITE_API_KEY (will store in $KeyVaultName)." -ForegroundColor Cyan
}
else {
    Write-Host "Keeping existing IGNITE-API-KEY in $KeyVaultName." -ForegroundColor Cyan
}

$kvUri = az keyvault show -n $KeyVaultName -g $KeyVaultResourceGroup --query properties.vaultUri -o tsv
if ([string]::IsNullOrWhiteSpace($kvUri)) {
    throw "Key Vault $KeyVaultName not found in $KeyVaultResourceGroup"
}
$kvUri = $kvUri.TrimEnd("/") + "/"
$kvId = az keyvault show -n $KeyVaultName -g $KeyVaultResourceGroup --query id -o tsv

# ACA secret name -> Key Vault secret name (consumption vault in IgniteChat RG)
$providerSecretMap = [ordered]@{
    "ignite-api-key"         = "IGNITE-API-KEY"
    "gemini-api-key"         = "GEMINI-API-KEY"
    "openai-api-key"         = "OPENAI-API-KEY"
    "azure-openai-api-key"   = "AZURE-OPENAI-API-KEY"
    "anthropic-api-key"      = "ANTHROPIC-API-KEY"
    "perplexity-api-key"     = "PERPLEXITY-API-KEY"
    "grok-api-key"           = "GROK-API-KEY"
    "deepseek-api-key"       = "DEEPSEEK-API-KEY"
}

$extractionKvSecret = "IGNITE-EXTRACTION-API-KEY"
$hasExtractionSecret = $false
if (-not $SkipKeyVaultSync) {
    $hasExtractionSecret = -not [string]::IsNullOrWhiteSpace(
        (az keyvault secret show --vault-name $KeyVaultName --name $extractionKvSecret --query id -o tsv 2>$null)
    )
    if ($hasExtractionSecret) {
        $providerSecretMap["ignite-extraction-api-key"] = $extractionKvSecret
    }
    else {
        Write-Host "No $extractionKvSecret in $KeyVaultName — replicate IGNITE-MASTER-API-KEY from kvsecret2296siu for Chat→API extraction." -ForegroundColor Yellow
    }
}

# OpenAI chat routes through Azure AI Foundry (PAYG) when base URL is set.
$azureOpenAiEndpoint = $FoundryChatEndpoint
$azureOpenAiModels = $AzureOpenAiAvailableModels
$geminiModels = "gemini-3.1-flash-lite,gemini-3.5-flash-lite,gemini-3.5-flash,gemini-3.1-pro-preview"
$deepseekModels = "deepseek-v4-pro,deepseek-v4-flash"
$anthropicModels = "claude-fable-5,claude-opus-5,claude-opus-4-8,claude-opus-4-6,claude-haiku-4-5-20251001"
$perplexityModels = "sonar,sonar-pro,sonar-reasoning"
$grokModels = "grok-4.3,grok-4.5,grok-4.20-0309-reasoning,grok-4.20-0309-non-reasoning"

$runtimeEnvVars = @(
    "IGNITE_RUNTIME_MODE=server",
    "IGNITE_DATA_DIR=/data",
    "IGNITE_API_HOST=0.0.0.0",
    "IGNITE_API_PORT=8000",
    "IGNITE_API_KEY=secretref:ignite-api-key",
    "GEMINI_API_KEY=secretref:gemini-api-key",
    "GEMINI_AVAILABLE_MODELS=$geminiModels",
    "GEMINI_MODEL_VERSION=gemini-3.1-flash-lite",
    "OPENAI_API_KEY=secretref:openai-api-key",
    "AZURE_OPENAI_API_KEY=secretref:azure-openai-api-key",
    "AZURE_OPENAI_ENDPOINT=$azureOpenAiEndpoint",
    "OPENAI_BASE_URL=$azureOpenAiEndpoint",
    "OPENAI_MODEL_VERSION=gpt-4.1-mini",
    "OPENAI_AVAILABLE_MODELS=$azureOpenAiModels",
    "ANTHROPIC_API_KEY=secretref:anthropic-api-key",
    "ANTHROPIC_AVAILABLE_MODELS=$anthropicModels",
    "ANTHROPIC_MODEL_VERSION=claude-fable-5",
    "PERPLEXITY_API_KEY=secretref:perplexity-api-key",
    "PERPLEXITY_AVAILABLE_MODELS=$perplexityModels",
    "PERPLEXITY_MODEL_VERSION=sonar",
    "GROK_API_KEY=secretref:grok-api-key",
    "GROK_AVAILABLE_MODELS=$grokModels",
    "GROK_MODEL_VERSION=grok-4.3",
    "DEEPSEEK_API_KEY=secretref:deepseek-api-key",
    "DEEPSEEK_AVAILABLE_MODELS=$deepseekModels",
    "DEEPSEEK_MODEL_VERSION=deepseek-v4-pro",
    "AZURE_KEYVAULT_URL=$kvUri",
    "IGNITE_EXTRACTION_ENABLED=true",
    "IGNITE_EXTRACTION_API_URL=$ExtractionApiUrl"
)
if ($hasExtractionSecret) {
    $runtimeEnvVars += "IGNITE_EXTRACTION_API_KEY=secretref:ignite-extraction-api-key"
}

if ($shouldSetApiKey) {
    Write-Host "Writing IGNITE-API-KEY into $KeyVaultName ..." -ForegroundColor Cyan
    az keyvault secret set --vault-name $KeyVaultName --name "IGNITE-API-KEY" --value $ApiKey -o none
}

$secretArgs = @()
if (-not $SkipKeyVaultSync) {
    Write-Host "Binding ACA secrets to $KeyVaultName via keyvaultref + system identity ..." -ForegroundColor Cyan
    foreach ($acaSecret in $providerSecretMap.Keys) {
        $kvName = $providerSecretMap[$acaSecret]
        $secretArgs += "$acaSecret=keyvaultref:${kvUri}secrets/$kvName,identityref:system"
        Write-Host "  $acaSecret -> ${kvUri}secrets/$kvName" -ForegroundColor DarkGray
    }
}
else {
    Write-Host "SkipKeyVaultSync set — Key Vault secret bindings left unchanged." -ForegroundColor Yellow
}

if (-not $exists) {
    Write-Host "Creating Container App $ContainerAppName in $AppResourceGroup ..." -ForegroundColor Cyan
    if ($secretArgs.Count -eq 0) {
        throw "Creating $ContainerAppName requires Key Vault bindings (remove -SkipKeyVaultSync)."
    }
    az containerapp create `
        -g $AppResourceGroup -n $ContainerAppName `
        --environment $ContainerEnvId `
        --image $fullImage `
        --cpu $Cpu --memory $Memory `
        --min-replicas 0 --max-replicas 1 `
        --ingress external --target-port 8000 `
        --registry-server $acrServer `
        --registry-username $acrUser `
        --registry-password $acrPass `
        --system-assigned `
        --secrets $secretArgs `
        --env-vars $runtimeEnvVars `
        -o none
}
else {
    Write-Host "Updating Container App $ContainerAppName (refresh ACR secret + image) ..." -ForegroundColor Cyan
    # Same pattern as IgniteAPI: keep registry password secret in sync on every deploy
    az containerapp registry set `
        -g $AppResourceGroup -n $ContainerAppName `
        --server $acrServer `
        --username $acrUser `
        --password $acrPass `
        -o none

    Write-Host "Ensuring system-assigned managed identity ..." -ForegroundColor Cyan
    az containerapp identity assign -g $AppResourceGroup -n $ContainerAppName --system-assigned -o none

    if ($secretArgs.Count -gt 0) {
        az containerapp secret set `
            -g $AppResourceGroup -n $ContainerAppName `
            --secrets $secretArgs `
            -o none
    }

    az containerapp update `
        -g $AppResourceGroup -n $ContainerAppName `
        --image $fullImage `
        --cpu $Cpu --memory $Memory `
        --min-replicas 0 --max-replicas 1 `
        --set-env-vars $runtimeEnvVars `
        --revision-suffix ("u" + (Get-Date -Format "HHmmss")) `
        -o none

    if ($secretArgs.Count -gt 0) {
        $rev = az containerapp show -g $AppResourceGroup -n $ContainerAppName --query "properties.latestRevisionName" -o tsv
        if (-not [string]::IsNullOrWhiteSpace($rev)) {
            Write-Host "Restarting revision $rev (secret ref reload) ..." -ForegroundColor Cyan
            az containerapp revision restart -g $AppResourceGroup -n $ContainerAppName --revision $rev -o none
        }
    }
}

# Ensure /data is a mounted Azure Files volume — without it IGNITE_DATA_DIR is
# ephemeral and every scale-to-zero wipes chats/sessions.
$mounts = az containerapp show -g $AppResourceGroup -n $ContainerAppName --query "properties.template.containers[0].volumeMounts" -o tsv 2>$null
if ([string]::IsNullOrWhiteSpace($mounts)) {
    Write-Host "Attaching Azure Files volume (ignitechat-sessions) to /data ..." -ForegroundColor Cyan
    $appYamlPath = Join-Path ([System.IO.Path]::GetTempPath()) "ignitechat-api-mount.yaml"
    az containerapp show -g $AppResourceGroup -n $ContainerAppName -o yaml > $appYamlPath
    $yamlText = Get-Content $appYamlPath -Raw
    $volumeBlock = @"
    volumes:
    - name: ignite-data
      storageName: ignitechat-sessions
      storageType: AzureFile
"@
    $yamlText = $yamlText -replace "(?m)^\s{4}volumes:\s*null\s*$", $volumeBlock
    $yamlText = $yamlText -replace "(?m)^(\s{6})volumeMounts:\s*null\s*$", "`$1volumeMounts:`n`$1- volumeName: ignite-data`n`$1  mountPath: /data"
    Set-Content -Path $appYamlPath -Value $yamlText -Encoding UTF8
    az containerapp update -g $AppResourceGroup -n $ContainerAppName --yaml $appYamlPath -o none
    Write-Host "Volume mounted: /data -> Azure Files share ignite-sessions." -ForegroundColor Green
}

# Ensure the container MI can read secrets from the IgniteChat consumption vault
$principalId = az containerapp show -g $AppResourceGroup -n $ContainerAppName --query identity.principalId -o tsv
if (-not [string]::IsNullOrWhiteSpace($principalId)) {
    Write-Host "Ensuring Key Vault Secrets User on $KeyVaultName for MI $principalId ..." -ForegroundColor Cyan
    $existing = az role assignment list --assignee $principalId --scope $kvId --role "Key Vault Secrets User" --query "[0].id" -o tsv 2>$null
    if ([string]::IsNullOrWhiteSpace($existing)) {
        az role assignment create `
            --assignee-object-id $principalId `
            --assignee-principal-type ServicePrincipal `
            --role "Key Vault Secrets User" `
            --scope $kvId `
            -o none
    }
}

$fqdn = az containerapp show -g $AppResourceGroup -n $ContainerAppName --query "properties.configuration.ingress.fqdn" -o tsv
Write-Host ""
Write-Host "Deploy complete." -ForegroundColor Green
Write-Host "API URL: https://$fqdn"
Write-Host "Health:  https://$fqdn/health"
Write-Host "Key Vault (IgniteChat RG): $KeyVaultName ($kvUri)"
Write-Host ""
Write-Host "Desktop .env (remote mode):" -ForegroundColor Cyan
Write-Host "IGNITE_RUNTIME_MODE=remote"
Write-Host "IGNITE_API_BASE_URL=https://$fqdn"
if ($shouldSetApiKey) {
    Write-Host "IGNITE_API_KEY=$ApiKey"
}
else {
    Write-Host "IGNITE_API_KEY=<$KeyVaultName secret IGNITE-API-KEY or app/.env IGNITE_API_KEY>"
}

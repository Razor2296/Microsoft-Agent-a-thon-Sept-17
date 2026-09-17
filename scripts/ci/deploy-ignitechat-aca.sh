#!/usr/bin/env bash
# Sync ignitechat-api on PAYG after CI build (image tag + env + Key Vault secret refs).
# Called from .github/workflows/deploy-aca.yml — keep in sync with Deploy-IgniteChatAca.ps1.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=az-retry.sh
source "${SCRIPT_DIR}/az-retry.sh"

: "${AZURE_SUBSCRIPTION_ID:?}"
: "${RESOURCE_GROUP:?}"
: "${CONTAINER_APP_NAME:?}"
: "${ACR_LOGIN_SERVER:?}"
: "${IMAGE_NAME:?}"
: "${GITHUB_SHA:?}"
: "${KEY_VAULT_NAME:?}"
: "${KEY_VAULT_URI:?}"
: "${FOUNDRY_CHAT_ENDPOINT:?}"
: "${IGNITE_EXTRACTION_API_URL:?}"
: "${ACR_USERNAME:?}"
: "${ACR_PASSWORD:?}"

IMAGE_TAG="${IMAGE_TAG:-${GITHUB_SHA}}"
IMAGE="${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"
echo "Deploying image tag: ${IMAGE_TAG}"

az extension add --name containerapp --upgrade --allow-preview true 2>/dev/null \
  || az extension add --name containerapp --upgrade
az account set --subscription "${AZURE_SUBSCRIPTION_ID}"

echo "Refreshing ACR registry credentials on ${CONTAINER_APP_NAME} ..."
az_retry az containerapp registry set \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${CONTAINER_APP_NAME}" \
  --server "${ACR_LOGIN_SERVER}" \
  --username "${ACR_USERNAME}" \
  --password "${ACR_PASSWORD}" \
  -o none

az_retry az containerapp identity assign \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${CONTAINER_APP_NAME}" \
  --system-assigned \
  -o none

# Let ACA finish the identity/registry write before secret bindings.
sleep 12

KV_BASE="${KEY_VAULT_URI%/}/secrets"

SECRET_BINDINGS=(
  "ignite-api-key=keyvaultref:${KV_BASE}/IGNITE-API-KEY,identityref:system"
  "gemini-api-key=keyvaultref:${KV_BASE}/GEMINI-API-KEY,identityref:system"
  "openai-api-key=keyvaultref:${KV_BASE}/OPENAI-API-KEY,identityref:system"
  "azure-openai-api-key=keyvaultref:${KV_BASE}/AZURE-OPENAI-API-KEY,identityref:system"
  "anthropic-api-key=keyvaultref:${KV_BASE}/ANTHROPIC-API-KEY,identityref:system"
  "perplexity-api-key=keyvaultref:${KV_BASE}/PERPLEXITY-API-KEY,identityref:system"
  "grok-api-key=keyvaultref:${KV_BASE}/GROK-API-KEY,identityref:system"
  "deepseek-api-key=keyvaultref:${KV_BASE}/DEEPSEEK-API-KEY,identityref:system"
)

if az keyvault secret show --vault-name "${KEY_VAULT_NAME}" --name "IGNITE-EXTRACTION-API-KEY" -o none 2>/dev/null; then
  SECRET_BINDINGS+=("ignite-extraction-api-key=keyvaultref:${KV_BASE}/IGNITE-EXTRACTION-API-KEY,identityref:system")
  EXTRACTION_KEY_ENV="IGNITE_EXTRACTION_API_KEY=secretref:ignite-extraction-api-key"
else
  echo "WARNING: ${KEY_VAULT_NAME}/IGNITE-EXTRACTION-API-KEY missing — extraction auth may fail until you replicate IGNITE-MASTER-API-KEY there."
  EXTRACTION_KEY_ENV=""
fi

echo "Binding Key Vault secret refs ..."
az_retry az containerapp secret set \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${CONTAINER_APP_NAME}" \
  --secrets "${SECRET_BINDINGS[@]}" \
  -o none

GEMINI_MODELS="gemini-3.1-flash-lite,gemini-3.5-flash-lite,gemini-3.5-flash,gemini-3.1-pro-preview"
# Match Foundry deployments on PAYG; expand after Deploy-IgniteOpenAiModelsPayG.ps1 + quota approval.
AZURE_OPENAI_MODELS="${AZURE_OPENAI_MODELS:-gpt-4.1-mini}"
ANTHROPIC_MODELS="claude-fable-5,claude-opus-5,claude-opus-4-8,claude-opus-4-6,claude-haiku-4-5-20251001"
PERPLEXITY_MODELS="sonar,sonar-pro,sonar-reasoning"
GROK_MODELS="grok-4.3,grok-4.5,grok-4.20-0309-reasoning,grok-4.20-0309-non-reasoning"
DEEPSEEK_MODELS="deepseek-v4-pro,deepseek-v4-flash"

ENV_VARS=(
  "IGNITE_RUNTIME_MODE=server"
  "IGNITE_DATA_DIR=/data"
  "IGNITE_API_HOST=0.0.0.0"
  "IGNITE_API_PORT=8000"
  "IGNITE_API_KEY=secretref:ignite-api-key"
  "GEMINI_API_KEY=secretref:gemini-api-key"
  "GEMINI_AVAILABLE_MODELS=${GEMINI_MODELS}"
  "GEMINI_MODEL_VERSION=gemini-3.1-flash-lite"
  "OPENAI_API_KEY=secretref:openai-api-key"
  "AZURE_OPENAI_API_KEY=secretref:azure-openai-api-key"
  "AZURE_OPENAI_ENDPOINT=${FOUNDRY_CHAT_ENDPOINT}"
  "OPENAI_BASE_URL=${FOUNDRY_CHAT_ENDPOINT}"
  "OPENAI_MODEL_VERSION=gpt-4.1-mini"
  "OPENAI_AVAILABLE_MODELS=${AZURE_OPENAI_MODELS}"
  "ANTHROPIC_API_KEY=secretref:anthropic-api-key"
  "ANTHROPIC_AVAILABLE_MODELS=${ANTHROPIC_MODELS}"
  "ANTHROPIC_MODEL_VERSION=claude-fable-5"
  "PERPLEXITY_API_KEY=secretref:perplexity-api-key"
  "PERPLEXITY_AVAILABLE_MODELS=${PERPLEXITY_MODELS}"
  "PERPLEXITY_MODEL_VERSION=sonar"
  "GROK_API_KEY=secretref:grok-api-key"
  "GROK_AVAILABLE_MODELS=${GROK_MODELS}"
  "GROK_MODEL_VERSION=grok-4.3"
  "DEEPSEEK_API_KEY=secretref:deepseek-api-key"
  "DEEPSEEK_AVAILABLE_MODELS=${DEEPSEEK_MODELS}"
  "DEEPSEEK_MODEL_VERSION=deepseek-v4-pro"
  "AZURE_KEYVAULT_URL=${KEY_VAULT_URI}"
  "IGNITE_EXTRACTION_ENABLED=true"
  "IGNITE_EXTRACTION_API_URL=${IGNITE_EXTRACTION_API_URL}"
)

if [[ -n "${EXTRACTION_KEY_ENV}" ]]; then
  ENV_VARS+=("${EXTRACTION_KEY_ENV}")
fi

SUFFIX="g$(echo "${GITHUB_SHA}" | cut -c1-7)"

echo "Deploying image ${IMAGE} (revision suffix ${SUFFIX}) ..."
az_retry az containerapp update \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${CONTAINER_APP_NAME}" \
  --image "${IMAGE}" \
  --set-env-vars "${ENV_VARS[@]}" \
  --revision-suffix "${SUFFIX}" \
  -o none

REV="$(az containerapp show -g "${RESOURCE_GROUP}" -n "${CONTAINER_APP_NAME}" --query properties.latestRevisionName -o tsv)"
if [[ -n "${REV}" ]]; then
  echo "Restarting revision ${REV} (Key Vault ref reload) ..."
  az_retry az containerapp revision restart -g "${RESOURCE_GROUP}" -n "${CONTAINER_APP_NAME}" --revision "${REV}" -o none
fi

echo "Deploy sync complete."

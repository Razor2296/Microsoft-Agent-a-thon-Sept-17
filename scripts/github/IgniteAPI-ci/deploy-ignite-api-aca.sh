#!/usr/bin/env bash
# Copy into Razor2296/IgniteAPI as scripts/ci/deploy-ignite-api-aca.sh (keep in sync with IgniteChat scripts/ci/).
set -euo pipefail

: "${AZURE_SUBSCRIPTION_ID:?}"
: "${RESOURCE_GROUP:?}"
: "${CONTAINER_APP_NAME:?}"
: "${ACR_LOGIN_SERVER:?}"
: "${IMAGE_NAME:?}"
: "${GITHUB_SHA:?}"
: "${KEY_VAULT_NAME:?}"
: "${ACR_USERNAME:?}"
: "${ACR_PASSWORD:?}"

IMAGE="${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${GITHUB_SHA}"

az extension add --name containerapp --upgrade --allow-preview true 2>/dev/null \
  || az extension add --name containerapp --upgrade
az account set --subscription "${AZURE_SUBSCRIPTION_ID}"

KV_URI="$(az keyvault show -n "${KEY_VAULT_NAME}" -g "${RESOURCE_GROUP}" --query properties.vaultUri -o tsv)"
KV_BASE="${KV_URI%/}/secrets"

az containerapp registry set -g "${RESOURCE_GROUP}" -n "${CONTAINER_APP_NAME}" \
  --server "${ACR_LOGIN_SERVER}" --username "${ACR_USERNAME}" --password "${ACR_PASSWORD}" -o none
az containerapp identity assign -g "${RESOURCE_GROUP}" -n "${CONTAINER_APP_NAME}" --system-assigned -o none

KV_SECRET_NAMES=(
  AZURE-STORAGE-CONNECTION-STRING
  AZURE-SERVICE-BUS-CONNECTION-STRING
  AZURE-DATALAKE-CONNECTION-STRING
  IGNITE-MASTER-API-KEY
  IGNITE-AUDIO-API-KEY
  IGNITE-DOC-API-KEY
  IGNITE-IMAGE-API-KEY
  IGNITE-VIDEO-API-KEY
  GEMINI-API-KEY
  OPENAI-API-KEY
  AZURE-OPENAI-API-KEY
  AZURE-OPENAI-ENDPOINT
  ANTHROPIC-API-KEY
  PERPLEXITY-API-KEY
  GROK-API-KEY
  DEEPSEEK-API-KEY
)
OPTIONAL_SECRETS="AZURE-SERVICE-BUS-CONNECTION-STRING AZURE-DATALAKE-CONNECTION-STRING"

REMOVE_ACA=()
SECRETS=()
for kv_name in "${KV_SECRET_NAMES[@]}"; do
  if ! az keyvault secret show --vault-name "${KEY_VAULT_NAME}" --name "${kv_name}" -o none 2>/dev/null; then
    if [[ " ${OPTIONAL_SECRETS} " == *" ${kv_name} "* ]]; then
      echo "Skipping optional KV secret: ${kv_name}"
      REMOVE_ACA+=("$(echo "${kv_name}" | tr '[:upper:]' '[:lower:]' | tr '_' '-')")
      continue
    fi
    echo "Required KV secret missing: ${kv_name}" >&2
    exit 1
  fi
  aca_name="$(echo "${kv_name}" | tr '[:upper:]' '[:lower:]' | tr '_' '-')"
  SECRETS+=("${aca_name}=keyvaultref:${KV_BASE}/${kv_name},identityref:system")
done

if [[ ${#REMOVE_ACA[@]} -gt 0 ]]; then
  az containerapp secret remove -g "${RESOURCE_GROUP}" -n "${CONTAINER_APP_NAME}" \
    --secret-names "${REMOVE_ACA[@]}" -o none 2>/dev/null || true
fi

az containerapp secret set -g "${RESOURCE_GROUP}" -n "${CONTAINER_APP_NAME}" --secrets "${SECRETS[@]}" -o none

SUFFIX="g$(echo "${GITHUB_SHA}" | cut -c1-7)"
az containerapp update -g "${RESOURCE_GROUP}" -n "${CONTAINER_APP_NAME}" \
  --image "${IMAGE}" \
  --cpu 2.0 --memory 4Gi \
  --set-env-vars \
    "APP_ROLE=api" \
    "AZURE_KEYVAULT_URL=${KV_URI}" \
    "AZURE_STORAGE_CONTAINER_UPLOADS=ignite-uploads" \
    "AZURE_STORAGE_CONTAINER_RESULTS=ignite-results" \
    "AZURE_SERVICE_BUS_QUEUE_NAME=ignite-jobs-queue" \
    "DEFAULT_LLM_PROVIDER=azure_openai" \
    "AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4.1-mini" \
    "MAX_ROW_PER_FILE=10" \
    "OPENAI_ENABLED=false" \
  --revision-suffix "${SUFFIX}" \
  -o none

echo "ignite-api deploy sync complete."

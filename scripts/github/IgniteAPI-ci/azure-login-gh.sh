#!/usr/bin/env bash
# Azure CLI login for GitHub Actions (no SP required).
# Modes: upn | device | sp-json (AZURE_CREDENTIALS env var)
set -euo pipefail

: "${AZURE_TENANT_ID:?}"
: "${AZURE_SUBSCRIPTION_ID:?}"
: "${AZURE_AUTH_MODE:?}"

install_containerapp_ext() {
  az extension add --name containerapp --upgrade --allow-preview true 2>/dev/null \
    || az extension add --name containerapp --upgrade
}

login_upn() {
  : "${AZURE_USERNAME:?}"
  : "${AZURE_PASSWORD:?}"
  echo "Logging in with AZURE_USERNAME (tenant ${AZURE_TENANT_ID}) ..."
  if ! az login -u "${AZURE_USERNAME}" -p "${AZURE_PASSWORD}" --tenant "${AZURE_TENANT_ID}" -o none; then
    echo "::error::UPN/password login failed. Many tenants block password flow + require MFA."
    echo "::error::Options: (1) Run workflow and use device mode — remove AZURE_PASSWORD secret temporarily, or"
    echo "::error::(2) Ask IT to create a CI service principal and set AZURE_CREDENTIALS, or"
    echo "::error::(3) Deploy from your PC: pwsh -File scripts/Deploy-IgniteChatAca.ps1"
    exit 1
  fi
}

login_sp_json() {
  : "${AZURE_CREDENTIALS:?}"
  CREDS_FILE="$(mktemp)"
  trap 'rm -f "${CREDS_FILE}"' EXIT
  printf '%s' "${AZURE_CREDENTIALS}" > "${CREDS_FILE}"
  CLIENT_ID="$(python3 -c "import json; print(json.load(open('${CREDS_FILE}'))['clientId'])")"
  CLIENT_SECRET="$(python3 -c "import json; print(json.load(open('${CREDS_FILE}'))['clientSecret'])")"
  TENANT="$(python3 -c "import json; print(json.load(open('${CREDS_FILE}')).get('tenantId','${AZURE_TENANT_ID}'))")"
  az login --service-principal -u "${CLIENT_ID}" -p "${CLIENT_SECRET}" --tenant "${TENANT}" -o none
}

login_device() {
  : "${DEVICE_LOGIN_URL:=https://microsoft.com/devicelogin}"
  : "${MFA_WAIT_SECONDS:=900}"
  install_containerapp_ext
  DEADLINE=$(( $(date +%s) + MFA_WAIT_SECONDS ))
  LOGGED_IN=false
  while [ "$(date +%s)" -lt "${DEADLINE}" ]; do
    REMAIN=$((DEADLINE - $(date +%s)))
    PER_ATTEMPT=$(( REMAIN < 300 ? REMAIN : 300 ))
    echo "::warning title=Device login::Open ${DEVICE_LOGIN_URL} — ${REMAIN}s left"
    LOGIN_LOG="$(mktemp)"
    set +e
    timeout "${PER_ATTEMPT}" az login --use-device-code --tenant "${AZURE_TENANT_ID}" \
      --scope "https://management.core.windows.net//.default" 2>&1 | tee "${LOGIN_LOG}"
    RC="${PIPESTATUS[0]}"
    set -e
    DEVICE_CODE="$(grep -oE 'enter the code [A-Z0-9]+' "${LOGIN_LOG}" | grep -oE '[A-Z0-9]+$' | head -1 || true)"
    [ -n "${DEVICE_CODE}" ] && echo "::warning title=CODIGO::${DEVICE_CODE} at ${DEVICE_LOGIN_URL}"
    if [ "${RC}" -eq 0 ]; then LOGGED_IN=true; break; fi
    az logout 2>/dev/null || true
    sleep 15
  done
  if [ "${LOGGED_IN}" != "true" ]; then
    echo "::error::Device login timed out."
    exit 1
  fi
}

case "${AZURE_AUTH_MODE}" in
  upn) login_upn ;;
  sp-json) login_sp_json ;;
  device) login_device ;;
  *)
    echo "Unknown AZURE_AUTH_MODE=${AZURE_AUTH_MODE}" >&2
    exit 1
    ;;
esac

install_containerapp_ext
az account set --subscription "${AZURE_SUBSCRIPTION_ID}"
echo "Azure context: $(az account show --query '{name:name, id:id, user:user.name}' -o tsv)"

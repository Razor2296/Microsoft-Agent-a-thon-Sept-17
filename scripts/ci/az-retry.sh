#!/usr/bin/env bash
# Retry az CLI calls that fail with Azure concurrent-write races (common on containerapp).
# Usage: source scripts/ci/az-retry.sh && az_retry az containerapp secret set ...
az_retry() {
  local max_attempts="${AZ_RETRY_MAX:-8}"
  local delay="${AZ_RETRY_DELAY_SEC:-15}"
  local attempt=1
  local out rc

  while true; do
    set +e
    out="$("$@" 2>&1)"
    rc=$?
    set -e
    if [[ $rc -eq 0 ]]; then
      [[ -n "$out" ]] && printf '%s\n' "$out"
      return 0
    fi
    if [[ "$out" == *ConflictingConcurrentWriteNotAllowed* ]] \
      || [[ "$out" == *AnotherOperationInProgress* ]] \
      || [[ "$out" == *OperationInProgress* ]]; then
      if [[ $attempt -ge $max_attempts ]]; then
        printf '%s\n' "$out" >&2
        return "$rc"
      fi
      echo "Azure concurrent write (attempt ${attempt}/${max_attempts}), retry in ${delay}s ..." >&2
      sleep "$delay"
      attempt=$((attempt + 1))
      delay=$((delay + 10))
      continue
    fi
    printf '%s\n' "$out" >&2
    return "$rc"
  done
}

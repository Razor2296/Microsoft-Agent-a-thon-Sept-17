#!/usr/bin/env bash
# Stage a lean Docker build context for Ignite Chat ACA.
# Allowlist-only copy avoids OneDrive Files-On-Demand I/O errors on junk dirs
# like app/scratch/, app/log/, local media, etc.
set -eu

SRC="${1:?Usage: stage-aca-build.sh <source-app-dir> [dest-dir]}"
DST="${2:-/tmp/ignitechat-aca-build}"

if [[ ! -f "${SRC}/Dockerfile" ]]; then
  echo "Dockerfile not found under ${SRC}" >&2
  exit 1
fi

rm -rf "${DST}"
mkdir -p "${DST}"

# Only what the ACA runtime image needs (see app/Dockerfile).
REQUIRED_FILES=(
  Dockerfile
  .dockerignore
  requirements-server.txt
  docker-compose.yml
  .env.example
  .env.staging.example
  .env.prod.example
)

REQUIRED_DIRS=(
  server
  backend
  main
  frontend
  plugins
  assets
)

copy_file() {
  local rel="$1"
  if [[ -f "${SRC}/${rel}" ]]; then
    mkdir -p "$(dirname "${DST}/${rel}")"
    # cp -L follows links; ignore unreadables from OneDrive placeholders.
    if ! cp -f "${SRC}/${rel}" "${DST}/${rel}" 2>/dev/null; then
      echo "WARNING: skipped unreadable file: ${rel}" >&2
    fi
  fi
}

copy_dir() {
  local rel="$1"
  local from="${SRC}/${rel}"
  local to="${DST}/${rel}"
  [[ -d "${from}" ]] || return 0
  mkdir -p "${to}"
  if command -v rsync >/dev/null 2>&1; then
    # --ignore-errors keeps going past OneDrive cloud-only I/O failures.
    # Exclude caches / local runtime junk that must never enter the image.
    rsync -a --ignore-errors \
      --exclude='__pycache__/' \
      --exclude='*.py[cod]' \
      --exclude='.pytest_cache/' \
      --exclude='*.db' \
      --exclude='*.sqlite*' \
      --exclude='local_rag.db' \
      --exclude='log/' \
      --exclude='scratch/' \
      --exclude='node_modules/' \
      "${from}/" "${to}/" || true
  else
    # Best-effort recursive copy; do not fail the whole stage on one bad file.
    (cd "${from}" && tar \
      --exclude='__pycache__' \
      --exclude='*.py[cod]' \
      --exclude='.pytest_cache' \
      --exclude='*.db' \
      --exclude='local_rag.db' \
      --exclude='log' \
      --exclude='scratch' \
      --exclude='node_modules' \
      --warning=no-file-changed \
      --ignore-failed-read \
      -cf - .) | tar -C "${to}" -xf - || true
  fi
}

for f in "${REQUIRED_FILES[@]}"; do
  copy_file "${f}"
done

for d in "${REQUIRED_DIRS[@]}"; do
  copy_dir "${d}"
done

# Always ensure Dockerfile + server requirements are present.
if [[ ! -f "${DST}/Dockerfile" || ! -f "${DST}/requirements-server.txt" ]]; then
  echo "Staging failed: Dockerfile/requirements-server.txt missing in ${DST}" >&2
  exit 1
fi

# Soft checks for runtime packages.
for must in server/main.py backend main/api.py; do
  if [[ ! -e "${DST}/${must}" ]]; then
    echo "WARNING: expected path missing after stage: ${must}" >&2
  fi
done

echo "Staged build context: $(du -sh "${DST}" | awk '{print $1}') -> ${DST}"

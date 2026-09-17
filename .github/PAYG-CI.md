# Ignite Chat — PAYG CI

| Workflow | Trigger | Action |
|----------|---------|--------|
| **Build Ignite Chat image (PAYG ACR)** | push `Develop` | Build `./app/Dockerfile` → `igniteapisiuacr/ignitechat-api` |
| **Deploy Ignite Chat ACA (PAYG)** | push `main` | Deploy `:latest` + env/KV via `scripts/ci/deploy-ignitechat-aca.sh` |
| **Build Windows Installer** | push/PR `Develop` (paths) | Artifact `IgniteChat_Setup.exe` |
| **Ignite Chat Checks** | PR → `main` / `Develop` | Ruff + pytest |

Production URL: https://ignitechat-api.orangefield-53e31d49.eastus2.azurecontainerapps.io

Secrets: `ACR_*`, `AZURE_USERNAME`, `AZURE_PASSWORD` (same PAYG tenant as IgniteAPI).

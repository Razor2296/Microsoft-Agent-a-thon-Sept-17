# Contest CI — Microsoft Agent-a-thon snapshot

This public repo is a **Founderz / Level 3 Architect** submission. ACA deploy mirrors [IgniteChat](https://github.com/Razor2296/IgniteChat): **build this repo’s `app/` → push ACR → update `ignitechat-api`** so the container gets the new commit (not a stale `:latest`).

| Workflow | Trigger | Secrets |
| --- | --- | --- |
| `ci.yml` | push/PR | none — Chat pytest + Foundry offline tests |
| `build-windows-installer.yml` | PR / manual | none |
| `deploy-aca.yml` | **push to `main`** + `workflow_dispatch` | Azure via **device code** (required). Optional: `ACR_USERNAME` / `ACR_PASSWORD` or `AZURE_CREDENTIALS`. If ACR secrets are missing, the job reads ACR admin creds with `az acr credential show` after device login. |

## Device code (same as Ignite Chat)

1. Merge to `main` (or Actions → **Deploy Ignite Chat ACA (PAYG)** → Run workflow with empty `image_tag`).  
2. Open the **Azure login** step log **first** — copy the code → https://microsoft.com/devicelogin (SIU MFA/passkey OK, up to ~15 min).  
3. After login, the job builds `app/Dockerfile`, pushes `:sha` + `:latest` to `igniteapisiuacr.azurecr.io/ignitechat-api`, then updates ACA.  
4. To redeploy an existing tag without rebuilding, set `image_tag` on `workflow_dispatch`.

If `AZURE_CREDENTIALS` (SP JSON) is set, the workflow uses SP instead of device code.

## Foundry (contest plane)

```powershell
cd foundry
copy .env.example .env
pip install -r requirements.txt
python test_tools.py
python test_brain.py
python brain.py
python agents.py
python monitor.py
python evaluate.py
python workflow.py
```

Project: **`juliancuray-7914`**. Details: [foundry/README.md](../foundry/README.md).

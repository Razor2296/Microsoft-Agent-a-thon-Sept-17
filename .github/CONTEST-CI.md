# Contest CI — Microsoft Agent-a-thon snapshot

This public repo is a **Founderz / Level 3 Architect** submission. ACA deploy mirrors [IgniteChat](https://github.com/Razor2296/IgniteChat):

**one action** — **Deploy Ignite Chat ACA (PAYG)** — order:

1. Build `app/Dockerfile` → push ACR `:sha` + `:latest`
2. Azure **device code** login (SIU MFA/passkey)
3. **Last step:** update Container App `ignitechat-api` to that ACR image

| Workflow | Trigger | Role |
| --- | --- | --- |
| `ci.yml` | push/PR | Contest checks only (pytest / Foundry offline) — **not** deploy |
| `build-windows-installer.yml` | PR / manual | Desktop installer |
| `deploy-aca.yml` | **push to `main`** + `workflow_dispatch` | Build/push ACR + update ACA |

## Secrets

| Secret | Required |
| --- | --- |
| `ACR_USERNAME` / `ACR_PASSWORD` | Yes — ACR push + ACA registry binding (same as IgniteChat) |
| `AZURE_CREDENTIALS` | Optional SP; default is **device code** |

## Device code

1. Merge to `main` (or Run workflow with empty `image_tag`).  
2. Wait for **Build & push image to ACR** to finish.  
3. Open **Azure login** → https://microsoft.com/devicelogin (up to ~15 min).  
4. Last step updates ACA to the new image.

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

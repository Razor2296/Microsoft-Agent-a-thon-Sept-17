# Contest CI — Microsoft Agent-a-thon snapshot

This public repo is a **Founderz / Level 3 Architect** submission. It is **not** the automatic PAYG production pipeline.

| Workflow | Trigger | Secrets |
| --- | --- | --- |
| `ci.yml` | push/PR | none — Chat pytest + Foundry offline tests |
| `build-windows-installer.yml` | PR / manual | none |
| `deploy-aca.yml` | **workflow_dispatch only** | optional `ACR_*`; Azure via **device code** (same as IgniteChat) or `AZURE_CREDENTIALS` |

**Why manual deploy?** Push-triggered ACA deploy failed here with `Username and password required` (no ACR secrets on this public fork). Production auto-deploy stays on [IgniteChat](https://github.com/Razor2296/IgniteChat).

## Device code (same as Ignite Chat)

1. Actions → **Deploy Ignite Chat ACA (PAYG) — manual** → Run workflow.  
2. Open the **Azure login** step log.  
3. Copy the code → https://microsoft.com/devicelogin (SIU MFA/passkey OK, up to ~15 min).  
4. Job continues with `scripts/ci/azure-login-gh.sh` + `deploy-ignitechat-aca.sh`.

If `AZURE_CREDENTIALS` (SP JSON) is set, the workflow uses SP instead of device code.

## Foundry (contest plane)

```powershell
cd foundry
copy .env.example .env
pip install -r requirements.txt
python test_tools.py
python agents.py
python monitor.py
python evaluate.py
python workflow.py
```

Project: **`juliancuray-7914`**. Details: [foundry/README.md](../foundry/README.md).

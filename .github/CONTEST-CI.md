# Contest CI — Microsoft Agent-a-thon snapshot

This public repo is a **Founderz / Level 3 Architect** submission. It is **not** the PAYG production pipeline.

| Workflow | What it does | Secrets needed |
| --- | --- | --- |
| `ci.yml` | Chat pytest + Foundry offline tool tests | none |
| `build-windows-installer.yml` | Optional Windows installer artifact | none |

**Removed on purpose:** `deploy-aca.yml`, `build-acr.yml` — those push to `igniteapisiuacr` / Container Apps and need `ACR_*` (and Azure login). They live in [IgniteChat](https://github.com/Razor2296/IgniteChat).

## Foundry (contest plane)

Run on your machine after `az login`, project **`juliancuray-7914`**:

```powershell
cd foundry
copy .env.example .env
# set PROJECT_CONNECTION_STRING + MODEL_DEPLOYMENT_NAME=gpt-5-mini
pip install -r requirements.txt
python test_tools.py
python agents.py
python monitor.py
python evaluate.py
python workflow.py
```

Details: [foundry/README.md](../foundry/README.md).

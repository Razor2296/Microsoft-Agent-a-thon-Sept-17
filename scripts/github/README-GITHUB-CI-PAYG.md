# GitHub CI — PAYG sin Service Principal

El **401 / No access** en *Enterprise applications* en el portal SIU es normal: no puedes registrar SP tú mismo. CI usa **device code** (MFA/passkey OK en el navegador). Opcional más adelante: `AZURE_CREDENTIALS` (SP) para deploy desatendido.

## Secrets (ambos repos)

| Secret | Valor |
| --- | --- |
| `ACR_USERNAME` | `igniteapisiuacr` |
| `ACR_PASSWORD` | admin password del ACR PAYG |
| `AZURE_CREDENTIALS` | *(opcional)* JSON del service principal |

`AZURE_USERNAME` / `AZURE_PASSWORD` ya **no** se usan en el deploy ACA (el tenant bloquea ROPC + MFA). Pueden quedar en el repo; el workflow los ignora.

## IgniteChat (`Razor2296/IgniteChat`)

1. Workflow `.github/workflows/deploy-aca.yml` → modo **device** por defecto (salvo `AZURE_CREDENTIALS`).
2. Tras merge a `main` (o **Run workflow**): abre el step **Azure login**, copia el código → https://microsoft.com/devicelogin (hasta ~15 min).

## IgniteAPI (`Razor2296/IgniteAPI`)

Mismo patrón: `.github/workflows/deploy-aca.yml` + `scripts/ci/azure-login-gh.sh` (device-first).

Plantillas en este repo (Chat):

- `scripts/github/IgniteAPI-deploy-aca-payg.yml` → `.github/workflows/deploy-aca.yml`
- `scripts/github/IgniteAPI-ci/azure-login-gh.sh` → `scripts/ci/azure-login-gh.sh`
- `scripts/github/IgniteAPI-ci/deploy-ignite-api-aca.sh` → `scripts/ci/deploy-ignite-api-aca.sh`

Desactiva o renombra el workflow viejo que apunta a `caacc1441625acr` / Students.

## RBAC mínimo (tu usuario)

En suscripción PAYG `4a614b14-…` necesitas poder actualizar Container Apps en RG `IgniteAPI` (p. ej. **Contributor** en el RG o en la suscripción). Sin eso, el build en ACR puede funcionar y el deploy fallará.

## Alternativa sin CI Azure

Build/push en GitHub + deploy local:

```powershell
az account set --subscription 4a614b14-fa98-4088-b2ec-dd6e3cc593bd
pwsh -File .\scripts\Deploy-IgniteChatAca.ps1 -SkipBuild
pwsh -File .\scripts\Deploy-IgniteApiAca.ps1 -SkipBuild
```

## Extracción Chat → API

Antes del primer deploy CI de Chat:

```powershell
pwsh -File .\scripts\Complete-IgniteMirrorPayG.ps1 -RefreshChat
```

(Crea `IGNITE-EXTRACTION-API-KEY` en `kvignitechatsiu`.)

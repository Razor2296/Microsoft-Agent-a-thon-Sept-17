# Contest CI note

This public Agent-a-thon snapshot **does not** run Azure Container Apps / ACR deploy.
Those workflows belong to the product pipeline ([IgniteChat](https://github.com/Razor2296/IgniteChat)).

Remaining Actions here:
- `ci.yml` — Ruff + pytest on PR
- `build-windows-installer.yml` — optional Windows installer on PR / manual run

Foundry Level 3 scripts live under `foundry/` and run locally against project `juliancuray-7914` (`az login`), not via GitHub Secrets.

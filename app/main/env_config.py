"""Multi-environment .env selection for Ignite Chat (dev/staging/prod)."""

from __future__ import annotations

import os

from dotenv import load_dotenv


def resolve_env_file(app_dir: str, environment: str | None = None) -> str:
    env_name = (environment or os.getenv("IGNITE_ENV") or "development").strip().lower()
    mapping = {
        "development": ".env",
        "dev": ".env",
        "local": ".env",
        "staging": ".env.staging",
        "stage": ".env.staging",
        "production": ".env.prod",
        "prod": ".env.prod",
    }
    filename = mapping.get(env_name, ".env")
    candidate = os.path.join(app_dir, filename)
    if os.path.isfile(candidate):
        return candidate
    # Fall back to default .env when specialized file is absent.
    return os.path.join(app_dir, ".env")


def load_environment(app_dir: str, environment: str | None = None) -> str:
    env_file = resolve_env_file(app_dir, environment)
    if os.path.isfile(env_file):
        load_dotenv(env_file, override=False)
    return env_file

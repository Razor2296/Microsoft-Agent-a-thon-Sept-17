"""
Level 3 — Observability: GenAI tracing to Application Insights / Foundry Tracing.

Must set AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true BEFORE SDK import.
Then open Foundry → your project → Tracing.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

FOUNDRY_DIR = Path(__file__).resolve().parent
load_dotenv(FOUNDRY_DIR / ".env")

if (os.getenv("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING") or "").strip().lower() != "true":
    print("Set AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true in foundry/.env before monitor.py")
    sys.exit(1)

PROJECT_CONNECTION_STRING = (os.getenv("PROJECT_CONNECTION_STRING") or "").strip()
MODEL_DEPLOYMENT_NAME = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-5-mini").strip()
APPINSIGHTS_CONN_STRING = (os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING") or "").strip()
ORCHESTRATOR_AGENT = os.getenv("IGNITE_ORCHESTRATOR_AGENT", "ignite-orchestrator-agent").strip()


def setup_tracing() -> None:
    from azure.ai.projects.telemetry import AIProjectInstrumentor
    from azure.monitor.opentelemetry import configure_azure_monitor

    AIProjectInstrumentor().instrument()
    if APPINSIGHTS_CONN_STRING:
        configure_azure_monitor(
            connection_string=APPINSIGHTS_CONN_STRING,
            enable_live_metrics=True,
        )
        print("Azure Monitor exporter connected")
    else:
        print("APPLICATIONINSIGHTS_CONNECTION_STRING empty — traces still go to Foundry if the project has App Insights linked")


def run_traced_call() -> None:
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import PromptAgentDefinition
    from azure.identity import DefaultAzureCredential

    client = AIProjectClient(
        endpoint=PROJECT_CONNECTION_STRING,
        credential=DefaultAzureCredential(),
    )
    openai_client = client.get_openai_client()
    agent = client.agents.create_version(
        agent_name="ignite-tracing-probe",
        definition=PromptAgentDefinition(
            model=MODEL_DEPLOYMENT_NAME,
            instructions="You are Ignite Chat's observability probe. Reply in one short sentence confirming EXTRACT routing for DOC-001.",
        ),
    )
    conversation = openai_client.conversations.create()
    response = openai_client.responses.create(
        input="User attached DOC-001. Confirm EXTRACT then summarize.",
        conversation=conversation.id,
        extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
    )
    print(f"Probe: {response.output_text[:200]}")
    openai_client.conversations.delete(conversation_id=conversation.id)
    client.agents.delete_version(agent_name=agent.name, agent_version=agent.version)
    client.close()


def main() -> int:
    if not PROJECT_CONNECTION_STRING:
        print("Set PROJECT_CONNECTION_STRING in foundry/.env")
        return 1
    setup_tracing()
    run_traced_call()
    print("Wait ~30s then open Foundry → Tracing (and App Insights transaction search).")
    time.sleep(3)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Level 3 — Multi-agent orchestration.

Part A: Python pipeline document-agent → orchestrator.
Part B: WorkflowAgentDefinition so the graph appears in Foundry → Build → Agents.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from tools import inspect_document, load_documents

FOUNDRY_DIR = Path(__file__).resolve().parent
load_dotenv(FOUNDRY_DIR / ".env")

PROJECT_CONNECTION_STRING = (os.getenv("PROJECT_CONNECTION_STRING") or "").strip()
MODEL_DEPLOYMENT_NAME = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-5-mini").strip()
DOCUMENT_AGENT = os.getenv("IGNITE_DOCUMENT_AGENT", "ignite-document-agent").strip()
ORCHESTRATOR_AGENT = os.getenv("IGNITE_ORCHESTRATOR_AGENT", "ignite-orchestrator-agent").strip()
WORKFLOW_AGENT = os.getenv("IGNITE_WORKFLOW_AGENT", "ignite-document-workflow").strip()


def _client(*, preview: bool = False):
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    kwargs = {
        "endpoint": PROJECT_CONNECTION_STRING,
        "credential": DefaultAzureCredential(),
    }
    if preview:
        kwargs["allow_preview"] = True
    return AIProjectClient(**kwargs)


def ensure_agents() -> None:
    print("Ensuring Foundry agents exist (run agents.py if this fails).")
    client = _client()
    names = {a.name for a in client.agents.list()}
    client.close()
    missing = [n for n in (DOCUMENT_AGENT, ORCHESTRATOR_AGENT) if n not in names]
    if missing:
        raise SystemExit(f"Missing agents {missing}. Run: python agents.py")


def _respond(openai_client, agent_name: str, text: str) -> str:
    agent_ref = {"agent_reference": {"name": agent_name, "type": "agent_reference"}}
    conversation = openai_client.conversations.create()
    response = openai_client.responses.create(
        input=text,
        conversation=conversation.id,
        extra_body=agent_ref,
    )
    out = response.output_text
    openai_client.conversations.delete(conversation_id=conversation.id)
    return out


def run_sdk_pipeline() -> None:
    """Orchestrate in code: inspect facts → document agent → orchestrator."""
    print("=== Part A: SDK orchestration ===")
    facts = inspect_document("DOC-001")
    client = _client()
    openai_client = client.get_openai_client()
    try:
        extracted = _respond(
            openai_client,
            DOCUMENT_AGENT,
            "Do NOT call tools. Use these facts only:\n" + facts,
        )
        print("Document agent:\n", extracted)
        routed = _respond(
            openai_client,
            ORCHESTRATOR_AGENT,
            "User asked: extrae la receta DOC-001. Route EXTRACT then answer in Spanish.\n"
            f"FACTS:\n{facts}\nEXTRACTED:\n{extracted}",
        )
        print("Orchestrator:\n", routed)
    finally:
        client.close()


def create_workflow_agent() -> str:
    from azure.ai.projects.models import WorkflowAgentDefinition

    yaml_text = (
        "kind: Workflow\n"
        f"name: {WORKFLOW_AGENT}\n"
        "description: Ignite extract-then-answer — document agent then orchestrator\n"
        "trigger:\n"
        "  kind: OnConversationStart\n"
        "  id: trigger_start\n"
        "actions:\n"
        "  - kind: InvokeAzureAgent\n"
        "    id: step_extract\n"
        "    agent:\n"
        f"      name: {DOCUMENT_AGENT}\n"
        "    conversationId: =System.ConversationId\n"
        "    input:\n"
        '      messages: ""\n'
        "    output:\n"
        "      autoSend: true\n"
        "  - kind: InvokeAzureAgent\n"
        "    id: step_orchestrate\n"
        "    agent:\n"
        f"      name: {ORCHESTRATOR_AGENT}\n"
        "    conversationId: =System.ConversationId\n"
        "    input:\n"
        '      messages: ""\n'
        "    output:\n"
        "      autoSend: true\n"
        "  - kind: EndConversation\n"
        "    id: step_end\n"
    )
    client = _client(preview=True)
    result = client.agents.create_version(
        agent_name=WORKFLOW_AGENT,
        definition=WorkflowAgentDefinition(workflow=yaml_text),
        description="Ignite document workflow (Foundry-visible multi-agent)",
    )
    print(f"Workflow agent: {result.name} v{result.version}")
    print("Visible in Foundry → Build → Agents (kind: workflow)")
    client.close()
    return result.name


def run_workflow(name: str) -> None:
    client = _client(preview=True)
    openai_client = client.get_openai_client()
    payload = json.dumps(load_documents(), indent=2)
    query = (
        "All sample Ignite documents are below — do not call inspect_document. "
        "Extract DOC-001 then give the user a short Spanish summary.\n\n"
        + payload
    )
    conversation = openai_client.conversations.create()
    resp = openai_client.responses.create(
        conversation=conversation.id,
        extra_body={"agent_reference": {"name": name, "type": "agent_reference"}},
        input=query,
        background=True,
    )
    print(f"Workflow run {resp.id} status={resp.status}")
    output_text = ""
    for attempt in range(12):
        time.sleep(8)
        fetched = openai_client.responses.retrieve(resp.id)
        print(f"  [{attempt + 1}] {fetched.status}")
        if fetched.status in ("completed", "failed", "cancelled"):
            output_text = fetched.output_text or ""
            break
    if output_text:
        print(output_text)
    else:
        print("No API text — open the workflow in Foundry portal to confirm the graph.")
    openai_client.conversations.delete(conversation_id=conversation.id)
    client.close()


def main() -> int:
    if not PROJECT_CONNECTION_STRING:
        print("Set PROJECT_CONNECTION_STRING in foundry/.env")
        return 1
    ensure_agents()
    run_sdk_pipeline()
    name = create_workflow_agent()
    run_workflow(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())

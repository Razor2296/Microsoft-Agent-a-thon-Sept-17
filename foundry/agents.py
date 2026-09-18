"""
Level 3 — Agent design: Foundry agents for Ignite (Architect plane).

  ignite-orchestrator-agent  BRAIN — emits Plan JSON (modality + steps)
  ignite-document-agent      specialist (inspect_document tool)
  ignite-media-agent         specialist (describe_media tool)

Usage (from this folder, after az login):
  copy .env.example .env   # fill PROJECT_CONNECTION_STRING
  pip install -r requirements.txt
  python agents.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from media_tools import DESCRIBE_MEDIA_TOOL, describe_media, load_media
from plan_schema import PLAN_JSON_SCHEMA_HINT
from tools import INSPECT_DOCUMENT_TOOL, inspect_document, load_documents

FOUNDRY_DIR = Path(__file__).resolve().parent
load_dotenv(FOUNDRY_DIR / ".env")

PROJECT_CONNECTION_STRING = (os.getenv("PROJECT_CONNECTION_STRING") or "").strip()
MODEL_DEPLOYMENT_NAME = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-5-mini").strip()
DOCUMENT_AGENT = os.getenv("IGNITE_DOCUMENT_AGENT", "ignite-document-agent").strip()
ORCHESTRATOR_AGENT = os.getenv("IGNITE_ORCHESTRATOR_AGENT", "ignite-orchestrator-agent").strip()
MEDIA_AGENT = os.getenv("IGNITE_MEDIA_AGENT", "ignite-media-agent").strip()


def _inspect_tool():
    from azure.ai.projects.models import FunctionTool

    return FunctionTool(
        name=INSPECT_DOCUMENT_TOOL["name"],
        description=INSPECT_DOCUMENT_TOOL["description"],
        parameters=INSPECT_DOCUMENT_TOOL["parameters"],
        strict=False,
    )


def _media_tool():
    from azure.ai.projects.models import FunctionTool

    return FunctionTool(
        name=DESCRIBE_MEDIA_TOOL["name"],
        description=DESCRIBE_MEDIA_TOOL["description"],
        parameters=DESCRIBE_MEDIA_TOOL["parameters"],
        strict=False,
    )


def _client():
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    return AIProjectClient(
        endpoint=PROJECT_CONNECTION_STRING,
        credential=DefaultAzureCredential(),
    )


def create_document_agent(client):
    from azure.ai.projects.models import PromptAgentDefinition

    instructions = """
You are Ignite Document Agent — specialist extractor for the Ignite multi-agent system.
When the user (or orchestrator plan) names a document id, call inspect_document.
Return structured facts only from the tool result. Never invent patient or invoice fields.
If the id is unknown, say so and list known ids.
Keep answers short enough to read in a WhatsApp-style bubble.
You do NOT decide routing — the orchestrator Plan JSON already chose EXTRACT.
"""
    return client.agents.create_version(
        agent_name=DOCUMENT_AGENT,
        definition=PromptAgentDefinition(
            model=MODEL_DEPLOYMENT_NAME,
            instructions=instructions,
            tools=[_inspect_tool()],
        ),
    )


def create_media_agent(client):
    from azure.ai.projects.models import PromptAgentDefinition

    instructions = """
You are Ignite Media Agent — specialist for image, audio, and video sample assets.
When given a media id (MED-IMG-*, MED-AUD-*, MED-VID-*), call describe_media.
Summarize caption + fields only from the tool. Never invent PHI.
Suggest linking to a document id when fields.suggested_doc_id is present.
You do NOT decide routing — the orchestrator Plan JSON already chose MEDIA_DESCRIBE.
"""
    return client.agents.create_version(
        agent_name=MEDIA_AGENT,
        definition=PromptAgentDefinition(
            model=MODEL_DEPLOYMENT_NAME,
            instructions=instructions,
            tools=[_media_tool()],
        ),
    )


def create_orchestrator_agent(client):
    from azure.ai.projects.models import PromptAgentDefinition

    instructions = f"""
You are Ignite Orchestrator — the BRAIN of the Foundry workflow.
Your ONLY job on the first turn is to emit a structured Plan JSON that downstream
agents and the local runner execute. Do not call tools yourself.

{PLAN_JSON_SCHEMA_HINT}

Routing rules (mirror Ignite Chat operational verbs):
- Document attach / extract / analyze / DOC-*** → modality=document, intent=EXTRACT,
  steps: inspect_document then synthesize.
- Image / audio / video / MED-*** → modality=image|audio|video, intent=MEDIA_DESCRIBE,
  steps: describe_media then synthesize.
- Export Word/Excel/PowerPoint → intent=EXPORT, action export_office.
- Greeting / missing id → intent=CLARIFY.
Align user_message_* language with the user. Never mention ClaimSight or insurance labs.
Trace tags MUST include modality:* and intent:* for Foundry Tracing filters.
"""
    return client.agents.create_version(
        agent_name=ORCHESTRATOR_AGENT,
        definition=PromptAgentDefinition(
            model=MODEL_DEPLOYMENT_NAME,
            instructions=instructions,
        ),
    )


def _run_with_tools(openai_client, agent_name: str, input_text: str) -> str:
    from openai.types.responses.response_input_param import FunctionCallOutput

    agent_ref = {"agent_reference": {"name": agent_name, "type": "agent_reference"}}
    conversation = openai_client.conversations.create()
    response = openai_client.responses.create(
        input=input_text,
        conversation=conversation.id,
        extra_body=agent_ref,
    )
    while True:
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            break
        outputs = []
        for item in calls:
            if item.name == "inspect_document":
                args = json.loads(item.arguments or "{}")
                result = inspect_document(args.get("doc_id") or "")
            elif item.name == "describe_media":
                args = json.loads(item.arguments or "{}")
                result = describe_media(args.get("media_id") or "")
            else:
                result = json.dumps({"error": f"Unknown tool '{item.name}'"})
            outputs.append(
                FunctionCallOutput(
                    type="function_call_output",
                    call_id=item.call_id,
                    output=result,
                )
            )
        response = openai_client.responses.create(
            input=outputs,
            conversation=conversation.id,
            extra_body=agent_ref,
        )
    text = response.output_text
    openai_client.conversations.delete(conversation_id=conversation.id)
    return text


def main() -> int:
    if not PROJECT_CONNECTION_STRING:
        print("Set PROJECT_CONNECTION_STRING in foundry/.env (Foundry project endpoint).")
        return 1

    client = _client()
    openai_client = client.get_openai_client()
    try:
        doc_agent = create_document_agent(client)
        media_agent = create_media_agent(client)
        orch = create_orchestrator_agent(client)
        print(f"Created {doc_agent.name} v{doc_agent.version}")
        print(f"Created {media_agent.name} v{media_agent.version}")
        print(f"Created {orch.name} v{orch.version}")

        ids = [d["doc_id"] for d in load_documents()]
        media_ids = [m["media_id"] for m in load_media()]
        print("\n--- Document agent ---")
        print(_run_with_tools(openai_client, DOCUMENT_AGENT, f"Extract DOC-001. Known ids: {ids}"))
        print("\n--- Media agent ---")
        print(
            _run_with_tools(
                openai_client,
                MEDIA_AGENT,
                f"Describe MED-IMG-001. Known ids: {media_ids}",
            )
        )
        print("\n--- Orchestrator (Plan JSON) ---")
        print(
            _run_with_tools(
                openai_client,
                ORCHESTRATOR_AGENT,
                "User dropped medical PDF DOC-001 and said: extrae la receta.",
            )
        )
        print("\nAgents stay in Foundry → Build → Agents (do not delete).")
        print("Next: python brain.py (offline) or FOUNDRY_BRAIN_LIVE=true python -c \"...\"")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Level 3 — Agent design: Foundry agents for Ignite (Architect plane).

Canonical names (Foundry Build → Agents — do not invent):
  ignite-orchestrator-agent  BRAIN — Plan JSON
  ignite-document-agent      document / Ignite API channel=document
  ignite-image-agent         image  / channel=image
  ignite-audio-agent         audio  / channel=audio
  ignite-video-agent         video  / channel=video

NO TOCAR remotes IgniteChat / IgniteAPI — solo este repo de concurso.

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

from agent_names import (
    all_prompt_agents,
    audio_agent,
    document_agent,
    image_agent,
    orchestrator_agent,
    video_agent,
)
from media_tools import DESCRIBE_MEDIA_TOOL, describe_media, load_media
from plan_schema import PLAN_JSON_SCHEMA_HINT
from tools import INSPECT_DOCUMENT_TOOL, inspect_document, load_documents

FOUNDRY_DIR = Path(__file__).resolve().parent
load_dotenv(FOUNDRY_DIR / ".env")

PROJECT_CONNECTION_STRING = (os.getenv("PROJECT_CONNECTION_STRING") or "").strip()
MODEL_DEPLOYMENT_NAME = (
    os.getenv("MODEL_DEPLOYMENT_NAME")
    or os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME")
    or "gemini-2.5-flash"
).strip()
DOCUMENT_AGENT = document_agent()
ORCHESTRATOR_AGENT = orchestrator_agent()
IMAGE_AGENT = image_agent()
AUDIO_AGENT = audio_agent()
VIDEO_AGENT = video_agent()


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

    return client.agents.create_version(
        agent_name=DOCUMENT_AGENT,
        definition=PromptAgentDefinition(
            model=MODEL_DEPLOYMENT_NAME,
            instructions=(
                "You are Ignite Document Agent — specialist for Ignite API document channel. "
                "Call inspect_document for DOC-* ids. Return structured facts only. Never invent PHI."
            ),
            tools=[_inspect_tool()],
        ),
    )


def _create_modality_agent(client, agent_name: str, modality: str, id_prefix: str):
    from azure.ai.projects.models import PromptAgentDefinition

    return client.agents.create_version(
        agent_name=agent_name,
        definition=PromptAgentDefinition(
            model=MODEL_DEPLOYMENT_NAME,
            instructions=(
                f"You are Ignite {modality.title()} Agent — Ignite API channel={modality}. "
                f"Call describe_media for {id_prefix} ids only. Summarize caption/fields. Never invent PHI."
            ),
            tools=[_media_tool()],
        ),
    )


def create_image_agent(client):
    return _create_modality_agent(client, IMAGE_AGENT, "image", "MED-IMG-*")


def create_audio_agent(client):
    return _create_modality_agent(client, AUDIO_AGENT, "audio", "MED-AUD-*")


def create_video_agent(client):
    return _create_modality_agent(client, VIDEO_AGENT, "video", "MED-VID-*")


def create_orchestrator_agent(client):
    from azure.ai.projects.models import PromptAgentDefinition

    instructions = f"""
You are Ignite Orchestrator — the BRAIN of the Foundry workflow.
Emit Plan JSON only. Route steps to:
  ignite-document-agent | ignite-image-agent | ignite-audio-agent | ignite-video-agent
Never invent other agent names.

{PLAN_JSON_SCHEMA_HINT}
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
        calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]
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
    out = (response.output_text or "").strip()
    openai_client.conversations.delete(conversation_id=conversation.id)
    return out


def main() -> int:
    if not PROJECT_CONNECTION_STRING:
        print("Set PROJECT_CONNECTION_STRING in foundry/.env (Foundry project endpoint).")
        return 1

    # Prefer runtime ensure (same path Chat uses) so names stay canonical.
    try:
        from runtime import ensure_agents_and_workflow

        if ensure_agents_and_workflow(force=True):
            print("Ensured via runtime:", ", ".join(all_prompt_agents()))
        else:
            print("runtime ensure returned False; falling back to direct create_version")
    except Exception as exc:
        print(f"runtime ensure failed ({exc}); direct create_version")

    client = _client()
    openai_client = client.get_openai_client()
    try:
        created = [
            create_document_agent(client),
            create_image_agent(client),
            create_audio_agent(client),
            create_video_agent(client),
            create_orchestrator_agent(client),
        ]
        for agent in created:
            print(f"Created {agent.name} v{agent.version}")

        ids = [d["doc_id"] for d in load_documents()]
        media_ids = [m["media_id"] for m in load_media()]
        print("\n--- Document agent ---")
        print(_run_with_tools(openai_client, DOCUMENT_AGENT, f"Extract DOC-001. Known ids: {ids}"))
        print("\n--- Image agent ---")
        print(
            _run_with_tools(
                openai_client,
                IMAGE_AGENT,
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
        print("Chat auto-path (Agent-a-thon snapshot only — NOT IgniteChat remote).")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

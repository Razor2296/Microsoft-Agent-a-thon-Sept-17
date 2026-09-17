"""
Level 3 — Agent design: two Foundry agents for Ignite.

  ignite-document-agent   specialist (inspect_document tool)
  ignite-orchestrator-agent  routes extract vs chat vs export

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

from tools import INSPECT_DOCUMENT_TOOL, inspect_document, load_documents

FOUNDRY_DIR = Path(__file__).resolve().parent
load_dotenv(FOUNDRY_DIR / ".env")

PROJECT_CONNECTION_STRING = (os.getenv("PROJECT_CONNECTION_STRING") or "").strip()
MODEL_DEPLOYMENT_NAME = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-5-mini").strip()
DOCUMENT_AGENT = os.getenv("IGNITE_DOCUMENT_AGENT", "ignite-document-agent").strip()
ORCHESTRATOR_AGENT = os.getenv("IGNITE_ORCHESTRATOR_AGENT", "ignite-orchestrator-agent").strip()


def _function_tool():
    from azure.ai.projects.models import FunctionTool

    return FunctionTool(
        name=INSPECT_DOCUMENT_TOOL["name"],
        description=INSPECT_DOCUMENT_TOOL["description"],
        parameters=INSPECT_DOCUMENT_TOOL["parameters"],
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
You are Ignite Document Agent, a specialist extractor for Ignite Chat.
When the user names a document id, call inspect_document.
Return structured facts only from the tool result. Never invent patient or invoice fields.
If the id is unknown, say so and list known ids.
Keep answers short enough to read in a WhatsApp-style bubble.
"""
    return client.agents.create_version(
        agent_name=DOCUMENT_AGENT,
        definition=PromptAgentDefinition(
            model=MODEL_DEPLOYMENT_NAME,
            instructions=instructions,
            tools=[_function_tool()],
        ),
    )


def create_orchestrator_agent(client):
    from azure.ai.projects.models import PromptAgentDefinition

    instructions = """
You are Ignite Orchestrator for a desktop WhatsApp-style assistant.
Decide the next action:
- EXTRACT: user attached or named a document (DOC-001 / DOC-002 / DOC-003) → tell them the document agent will inspect it; summarize fields after the tool-style facts are provided in the prompt.
- ANSWER: user asks about a document already extracted → answer from provided facts only.
- EXPORT: user asks for Word/Excel/PowerPoint → describe the Office file you would generate (do not claim the bytes exist in Foundry).
- CLARIFY: greeting or missing file id → ask which document to extract. Do not fabricate PDFs.
Never mention insurance claims labs. This is Ignite documents, not ClaimSight.
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
        orch = create_orchestrator_agent(client)
        print(f"Created {doc_agent.name} v{doc_agent.version}")
        print(f"Created {orch.name} v{orch.version}")

        ids = [d["doc_id"] for d in load_documents()]
        sample = inspect_document("DOC-001")
        print("\n--- Document agent ---")
        print(_run_with_tools(openai_client, DOCUMENT_AGENT, f"Extract DOC-001. Known ids: {ids}"))
        print("\n--- Orchestrator ---")
        print(
            _run_with_tools(
                openai_client,
                ORCHESTRATOR_AGENT,
                "User dropped a medical PDF labelled DOC-001. Route EXTRACT then summarize.\n"
                f"TOOL_FACTS:\n{sample}",
            )
        )
        print("\nAgents stay in Foundry → Build → Agents (do not delete).")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

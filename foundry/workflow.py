"""
Level 3 — Multi-agent orchestration with Foundry as the brain.

Part A: brain.run_turn — Plan JSON → tools → business reply (works offline).
Part B: WorkflowAgentDefinition graph in Foundry → Build → Agents / Workflows.
Part C: Optional live workflow run against the portal graph.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from brain import execute_plan, heuristic_plan, run_turn
from tools import load_documents
from agent_names import (
    audio_agent,
    document_agent,
    image_agent,
    orchestrator_agent,
    video_agent,
    workflow_agent,
)

FOUNDRY_DIR = Path(__file__).resolve().parent
load_dotenv(FOUNDRY_DIR / ".env")

PROJECT_CONNECTION_STRING = (os.getenv("PROJECT_CONNECTION_STRING") or "").strip()
DOCUMENT_AGENT = document_agent()
ORCHESTRATOR_AGENT = orchestrator_agent()
IMAGE_AGENT = image_agent()
AUDIO_AGENT = audio_agent()
VIDEO_AGENT = video_agent()
WORKFLOW_AGENT = workflow_agent()
MEDIA_AGENT = IMAGE_AGENT  # legacy alias only


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
    """Prefer runtime.ensure_agents_and_workflow (used by Chat). This is CLI fallback."""
    try:
        from runtime import ensure_agents_and_workflow

        if ensure_agents_and_workflow(force=True):
            print("Agents + workflow ensured via runtime.")
            return
    except Exception as exc:
        print(f"runtime ensure failed ({exc}); checking list only...")
    print("Ensuring Foundry agents exist (run agents.py if this fails).")
    client = _client()
    names = {a.name for a in client.agents.list()}
    client.close()
    missing = [
        n
        for n in (
            DOCUMENT_AGENT,
            ORCHESTRATOR_AGENT,
            IMAGE_AGENT,
            AUDIO_AGENT,
            VIDEO_AGENT,
        )
        if n not in names
    ]
    if missing:
        raise SystemExit(f"Missing agents {missing}. Run: python agents.py")


def run_brain_pipeline() -> None:
    """Part A — Foundry Plan is the source of truth; runner executes tools."""
    print("=== Part A: Foundry brain → execute_plan (offline heuristic) ===")
    samples = [
        "Extrae la receta DOC-001.",
        "Describe la imagen MED-IMG-001.",
        "Resume el video MED-VID-001.",
    ]
    for sample in samples:
        result = run_turn(sample, lang="es", use_foundry=False)
        print(f"\nUSER: {sample}")
        print("PLAN:", json.dumps(result["plan"], ensure_ascii=False, indent=2))
        print("REPLY:", result["final_user_message"])
        print("TRACE_TAGS:", result["trace_tags"])


def create_workflow_agent() -> str:
    """Part B — visible graph: plan → document/image/audio/video → synthesize."""
    from azure.ai.projects.models import WorkflowAgentDefinition

    steps = [
        ("step_plan", ORCHESTRATOR_AGENT),
        ("step_document", DOCUMENT_AGENT),
        ("step_image", IMAGE_AGENT),
        ("step_audio", AUDIO_AGENT),
        ("step_video", VIDEO_AGENT),
        ("step_synthesize", ORCHESTRATOR_AGENT),
    ]
    actions = ""
    for step_id, agent_name in steps:
        actions += (
            "  - kind: InvokeAzureAgent\n"
            f"    id: {step_id}\n"
            "    agent:\n"
            f"      name: {agent_name}\n"
            "    conversationId: =System.ConversationId\n"
            "    input:\n"
            '      messages: ""\n'
            "    output:\n"
            "      autoSend: true\n"
        )
    yaml_text = (
        "kind: Workflow\n"
        f"name: {WORKFLOW_AGENT}\n"
        "description: Ignite Foundry brain — Traces activate multi-agent story in one conversation\n"
        "trigger:\n"
        "  kind: OnConversationStart\n"
        "  id: trigger_start\n"
        "actions:\n"
        f"{actions}"
        "  - kind: EndConversation\n"
        "    id: step_end\n"
    )
    client = _client(preview=True)
    result = client.agents.create_version(
        agent_name=WORKFLOW_AGENT,
        definition=WorkflowAgentDefinition(workflow=yaml_text),
        description="Ignite multi-agent workflow — Plan JSON brain + 4 specialists",
    )
    print(f"Workflow agent: {result.name} v{result.version}")
    print("Visible in Foundry → Build → Agents (kind: workflow)")
    client.close()
    return result.name


def run_workflow(name: str) -> None:
    client = _client(preview=True)
    openai_client = client.get_openai_client()
    # Seed with catalog so specialists need not invent data if tools are skipped.
    payload = {
        "documents": load_documents(),
        "instruction": (
            "Emit Plan JSON first (orchestrator). If intent=EXTRACT use DOC-001 facts; "
            "then document agent may refine; media agent no-ops unless MED-* present; "
            "finally orchestrator returns a short Spanish user reply."
        ),
    }
    query = json.dumps(payload, indent=2)
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
        # Also show what the local brain would have executed for the same ask
        local = execute_plan(heuristic_plan("Extrae DOC-001"), lang="es")
        print("\n--- Local brain mirror (for Traces tags) ---")
        print(json.dumps(local["plan"], ensure_ascii=False, indent=2))
    else:
        print("No API text — open the workflow in Foundry portal to confirm the graph.")
    openai_client.conversations.delete(conversation_id=conversation.id)
    client.close()


def main() -> int:
    # Always demonstrate the brain offline (Paso 3 sequence without Azure).
    run_brain_pipeline()

    if not PROJECT_CONNECTION_STRING:
        print(
            "\nNo PROJECT_CONNECTION_STRING — skipped portal workflow create/run. "
            "Offline brain above is enough for CI; set .env to publish the graph."
        )
        return 0

    ensure_agents()
    name = create_workflow_agent()
    run_workflow(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())

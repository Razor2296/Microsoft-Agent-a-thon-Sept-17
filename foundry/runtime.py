"""Runtime helpers: ensure Foundry agents/workflow exist, then orchestrate under Traces.

Called automatically from Ignite Chat turns (and Chat→API extract). Manual
`python agents.py` / `python workflow.py` remain optional seed/debug tools only.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_READY = False
_TRACING_READY = False

DOCUMENT_AGENT = lambda: (os.getenv("IGNITE_DOCUMENT_AGENT") or "ignite-document-agent").strip()
MEDIA_AGENT = lambda: (os.getenv("IGNITE_MEDIA_AGENT") or "ignite-media-agent").strip()
ORCHESTRATOR_AGENT = lambda: (os.getenv("IGNITE_ORCHESTRATOR_AGENT") or "ignite-orchestrator-agent").strip()
WORKFLOW_AGENT = lambda: (os.getenv("IGNITE_WORKFLOW_AGENT") or "ignite-document-workflow").strip()
MODEL = lambda: (os.getenv("MODEL_DEPLOYMENT_NAME") or "gpt-5-mini").strip()


def _project() -> str:
    return (os.getenv("PROJECT_CONNECTION_STRING") or "").strip()


def setup_tracing() -> bool:
    """Idempotent GenAI → Foundry Tracing / App Insights."""
    global _TRACING_READY
    if _TRACING_READY:
        return True
    os.environ.setdefault("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", "true")
    if not _project():
        return False
    try:
        from azure.ai.projects.telemetry import AIProjectInstrumentor
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError as exc:
        logger.warning("foundry.runtime: tracing deps missing (%s)", exc)
        return False
    try:
        AIProjectInstrumentor().instrument()
        conn = (os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING") or "").strip()
        if conn:
            configure_azure_monitor(connection_string=conn, enable_live_metrics=True)
        _TRACING_READY = True
        logger.info("foundry.runtime: GenAI tracing armed")
        return True
    except Exception as exc:
        logger.warning("foundry.runtime: tracing setup failed (%s)", exc)
        return False


def _client(*, preview: bool = False):
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    kwargs = {
        "endpoint": _project(),
        "credential": DefaultAzureCredential(),
    }
    if preview:
        kwargs["allow_preview"] = True
    return AIProjectClient(**kwargs)


def _create_agents(client) -> None:
    from plan_schema import PLAN_JSON_SCHEMA_HINT
    from media_tools import DESCRIBE_MEDIA_TOOL
    from tools import INSPECT_DOCUMENT_TOOL
    from azure.ai.projects.models import FunctionTool, PromptAgentDefinition

    inspect_tool = FunctionTool(
        name=INSPECT_DOCUMENT_TOOL["name"],
        description=INSPECT_DOCUMENT_TOOL["description"],
        parameters=INSPECT_DOCUMENT_TOOL["parameters"],
        strict=False,
    )
    media_tool = FunctionTool(
        name=DESCRIBE_MEDIA_TOOL["name"],
        description=DESCRIBE_MEDIA_TOOL["description"],
        parameters=DESCRIBE_MEDIA_TOOL["parameters"],
        strict=False,
    )
    client.agents.create_version(
        agent_name=DOCUMENT_AGENT(),
        definition=PromptAgentDefinition(
            model=MODEL(),
            instructions=(
                "You are Ignite Document Agent. Call inspect_document for DOC-* ids. "
                "Return structured facts only. Never invent PHI."
            ),
            tools=[inspect_tool],
        ),
    )
    client.agents.create_version(
        agent_name=MEDIA_AGENT(),
        definition=PromptAgentDefinition(
            model=MODEL(),
            instructions=(
                "You are Ignite Media Agent. Call describe_media for MED-* ids. "
                "Summarize caption/fields only."
            ),
            tools=[media_tool],
        ),
    )
    client.agents.create_version(
        agent_name=ORCHESTRATOR_AGENT(),
        definition=PromptAgentDefinition(
            model=MODEL(),
            instructions=(
                "You are Ignite Orchestrator — the BRAIN. Emit Plan JSON only on first turn.\n"
                + PLAN_JSON_SCHEMA_HINT
            ),
        ),
    )


def _create_workflow(client) -> str:
    from azure.ai.projects.models import WorkflowAgentDefinition

    name = WORKFLOW_AGENT()
    yaml_text = (
        "kind: Workflow\n"
        f"name: {name}\n"
        "description: Ignite — Traces-triggered orchestration (plan → document → media → synthesize)\n"
        "trigger:\n"
        "  kind: OnConversationStart\n"
        "  id: trigger_start\n"
        "actions:\n"
        "  - kind: InvokeAzureAgent\n"
        "    id: step_plan\n"
        "    agent:\n"
        f"      name: {ORCHESTRATOR_AGENT()}\n"
        "    conversationId: =System.ConversationId\n"
        "    input:\n"
        '      messages: ""\n'
        "    output:\n"
        "      autoSend: true\n"
        "  - kind: InvokeAzureAgent\n"
        "    id: step_document\n"
        "    agent:\n"
        f"      name: {DOCUMENT_AGENT()}\n"
        "    conversationId: =System.ConversationId\n"
        "    input:\n"
        '      messages: ""\n'
        "    output:\n"
        "      autoSend: true\n"
        "  - kind: InvokeAzureAgent\n"
        "    id: step_media\n"
        "    agent:\n"
        f"      name: {MEDIA_AGENT()}\n"
        "    conversationId: =System.ConversationId\n"
        "    input:\n"
        '      messages: ""\n'
        "    output:\n"
        "      autoSend: true\n"
        "  - kind: InvokeAzureAgent\n"
        "    id: step_synthesize\n"
        "    agent:\n"
        f"      name: {ORCHESTRATOR_AGENT()}\n"
        "    conversationId: =System.ConversationId\n"
        "    input:\n"
        '      messages: ""\n'
        "    output:\n"
        "      autoSend: true\n"
        "  - kind: EndConversation\n"
        "    id: step_end\n"
    )
    client.agents.create_version(
        agent_name=name,
        definition=WorkflowAgentDefinition(workflow=yaml_text),
        description="Ignite multi-agent workflow — auto-ensured from Chat turns",
    )
    return name


def ensure_agents_and_workflow(*, force: bool = False) -> bool:
    """Create agents + workflow in Foundry if missing. Cached per process."""
    global _READY
    if _READY and not force:
        return True
    if not _project():
        return False
    with _LOCK:
        if _READY and not force:
            return True
        try:
            client = _client(preview=True)
            try:
                names = {a.name for a in client.agents.list()}
                needed = {DOCUMENT_AGENT(), MEDIA_AGENT(), ORCHESTRATOR_AGENT()}
                if not needed.issubset(names):
                    logger.info("foundry.runtime: creating agents %s", sorted(needed - names))
                    _create_agents(client)
                    names = {a.name for a in client.agents.list()}
                if WORKFLOW_AGENT() not in names:
                    logger.info("foundry.runtime: creating workflow %s", WORKFLOW_AGENT())
                    _create_workflow(client)
            finally:
                client.close()
            _READY = True
            return True
        except Exception as exc:
            logger.warning("foundry.runtime: ensure agents/workflow failed (%s)", exc)
            return False


def invoke_workflow(user_text: str, *, timeout_s: float = 90.0) -> dict[str, Any] | None:
    """Run the Foundry workflow agent (shows up under Tracing)."""
    if not _project():
        return None
    name = WORKFLOW_AGENT()
    try:
        client = _client(preview=True)
        openai_client = client.get_openai_client()
        conversation = openai_client.conversations.create()
        resp = openai_client.responses.create(
            conversation=conversation.id,
            extra_body={"agent_reference": {"name": name, "type": "agent_reference"}},
            input=user_text,
            background=True,
        )
        output_text = ""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            fetched = openai_client.responses.retrieve(resp.id)
            if fetched.status in ("completed", "failed", "cancelled"):
                output_text = (fetched.output_text or "").strip()
                status = fetched.status
                break
            time.sleep(2)
        else:
            status = "timeout"
        openai_client.conversations.delete(conversation_id=conversation.id)
        client.close()
        if not output_text and status != "completed":
            return None
        return {
            "source": "foundry_workflow",
            "workflow": name,
            "status": status,
            "message": output_text,
            "trace_tags": [
                "source:foundry_workflow",
                f"workflow:{name}",
                "trace:genai",
            ],
        }
    except Exception as exc:
        logger.warning("foundry.runtime: workflow invoke failed (%s)", exc)
        return None


def run_traced_orchestration(
    user_text: str,
    *,
    lang: str = "es",
    trigger: str = "chat",
) -> dict[str, Any]:
    """
    Full path used by Ignite Chat:
      1) arm Traces
      2) ensure agents.py + workflow.py artifacts exist in Foundry
      3) invoke workflow (orchestration visible in Tracing)
      4) mirror Plan JSON via local brain for structured footer / offline fallback
    """
    tracing = setup_tracing()
    ensured = ensure_agents_and_workflow() if tracing or _project() else False

    workflow_payload = None
    if ensured and _project():
        tagged = (
            f"[trigger:{trigger}] {user_text}\n"
            "Orchestrate: emit Plan JSON, run specialists, reply to the user."
        )
        workflow_payload = invoke_workflow(tagged)

    # Always compute a Plan locally (offline-safe) so Chat has structured orchestration
    from brain import run_turn  # type: ignore

    brain = run_turn(user_text, lang=lang, use_foundry=False)
    plan = brain.get("plan")
    message = (workflow_payload or {}).get("message") or brain.get("final_user_message") or ""
    tags = list((workflow_payload or {}).get("trace_tags") or [])
    tags.extend(brain.get("trace_tags") or [])
    tags.append(f"trigger:{trigger}")
    if tracing:
        tags.append("trace:genai")
    # dedupe preserve order
    seen = set()
    uniq_tags = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            uniq_tags.append(t)

    return {
        "source": (workflow_payload or {}).get("source") or "foundry_brain_offline",
        "workflow": (workflow_payload or {}).get("workflow"),
        "message": message,
        "plan": plan,
        "trace_tags": uniq_tags,
        "tracing_enabled": tracing,
        "agents_ensured": ensured,
        "tool_results": brain.get("tool_results"),
        "trigger": trigger,
    }

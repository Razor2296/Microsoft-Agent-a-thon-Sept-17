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
# Foundry deployment name (Models + endpoints). Gemini first for Paso 3.
MODEL = lambda: (
    os.getenv("MODEL_DEPLOYMENT_NAME")
    or os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME")
    or "gemini-2.5-flash"
).strip()


def _project() -> str:
    return (os.getenv("PROJECT_CONNECTION_STRING") or "").strip()


def _app_insights() -> str:
    return (os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING") or "").strip()


def setup_tracing() -> bool:
    """Idempotent GenAI → Foundry Tracing / App Insights.

    Foundry Traces UI needs the project endpoint + (ideally) Application Insights.
    Without App Insights, agent calls may still create portal traces, but Monitor/Insights stay empty.
    """
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
        conn = _app_insights()
        if conn:
            configure_azure_monitor(connection_string=conn, enable_live_metrics=True)
            logger.info("foundry.runtime: GenAI tracing + App Insights armed")
        else:
            logger.warning(
                "foundry.runtime: APPLICATIONINSIGHTS_CONNECTION_STRING missing — "
                "agent calls still run, but Foundry Traces/Monitor may stay empty. "
                "Copy it from Foundry → project → Tracing / Application Insights."
            )
        _TRACING_READY = True
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
    """Ensure agents + workflow exist in Foundry (Gemini model by default).

    Always publishes a fresh agent/workflow version when missing OR when
    FOUNDRY_REFRESH_AGENTS=true / force=True so MODEL_DEPLOYMENT_NAME sticks.
    Cached per process after first success unless force.
    """
    global _READY
    if _READY and not force:
        return True
    if not _project():
        return False
    refresh = force or (os.getenv("FOUNDRY_REFRESH_AGENTS") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    with _LOCK:
        if _READY and not force:
            return True
        try:
            client = _client(preview=True)
            try:
                names = {a.name for a in client.agents.list()}
                needed = {DOCUMENT_AGENT(), MEDIA_AGENT(), ORCHESTRATOR_AGENT()}
                missing = needed - names
                if missing or refresh:
                    logger.info(
                        "foundry.runtime: publishing agents model=%s missing=%s refresh=%s",
                        MODEL(),
                        sorted(missing),
                        refresh,
                    )
                    _create_agents(client)
                    names = {a.name for a in client.agents.list()}
                if WORKFLOW_AGENT() not in names or refresh:
                    logger.info(
                        "foundry.runtime: publishing workflow %s (model=%s)",
                        WORKFLOW_AGENT(),
                        MODEL(),
                    )
                    _create_workflow(client)
            finally:
                client.close()
            _READY = True
            return True
        except Exception as exc:
            logger.warning("foundry.runtime: ensure agents/workflow failed (%s)", exc)
            return False


def _respond_agent(openai_client, agent_name: str, text: str) -> str:
    """One agent call (appears under that agent's Traces tab). Handles local tools."""
    from openai.types.responses.response_input_param import FunctionCallOutput
    from media_tools import describe_media
    from tools import inspect_document

    agent_ref = {"agent_reference": {"name": agent_name, "type": "agent_reference"}}
    conversation = openai_client.conversations.create()
    response = openai_client.responses.create(
        input=text,
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


def invoke_agent_pipeline(user_text: str) -> dict[str, Any] | None:
    """
    Live multi-agent orchestration under GenAI tracing.
    Creates spans on ignite-orchestrator-agent, ignite-document-agent, ignite-media-agent
    (open those tabs in Foundry → Agents → Traces — NOT ignite-image-agent).
    """
    if not _project():
        return None
    try:
        from brain import heuristic_plan  # type: ignore

        plan = heuristic_plan(user_text)
        client = _client()
        openai_client = client.get_openai_client()
        try:
            plan_prompt = (
                "Emit ONLY Plan JSON for this user turn (no tools):\n" + user_text
            )
            plan_text = _respond_agent(openai_client, ORCHESTRATOR_AGENT(), plan_prompt)

            specialist_out = ""
            intent = (plan.get("intent") or "").upper()
            if intent in ("EXTRACT", "ANSWER") or plan.get("doc_id"):
                doc_id = plan.get("doc_id") or "DOC-001"
                specialist_out = _respond_agent(
                    openai_client,
                    DOCUMENT_AGENT(),
                    f"Extract/inspect {doc_id}. User said: {user_text}",
                )
            elif intent == "MEDIA_DESCRIBE" or plan.get("media_id"):
                media_id = plan.get("media_id") or "MED-IMG-001"
                specialist_out = _respond_agent(
                    openai_client,
                    MEDIA_AGENT(),
                    f"Describe {media_id}. User said: {user_text}",
                )

            synth = _respond_agent(
                openai_client,
                ORCHESTRATOR_AGENT(),
                "Synthesize a short user-facing reply in the user's language.\n"
                f"USER: {user_text}\nPLAN: {json.dumps(plan, ensure_ascii=False)}\n"
                f"SPECIALIST: {specialist_out}\nPRIOR_PLAN_TEXT: {plan_text[:1500]}",
            )
            message = synth or specialist_out or plan_text
            if not message:
                return {
                    "source": "foundry_agent_pipeline",
                    "workflow": None,
                    "message": "",
                    "plan": plan,
                    "error": "Live agent calls returned empty text.",
                    "trace_tags": [
                        "source:foundry_agent_pipeline",
                        "live:empty",
                        f"agent:{DOCUMENT_AGENT()}",
                        f"agent:{MEDIA_AGENT()}",
                        f"agent:{ORCHESTRATOR_AGENT()}",
                    ],
                }
            return {
                "source": "foundry_agent_pipeline",
                "workflow": None,
                "message": message,
                "plan": plan,
                "trace_tags": [
                    "source:foundry_agent_pipeline",
                    f"intent:{plan.get('intent')}",
                    f"modality:{plan.get('modality')}",
                    "trace:genai",
                    f"agent:{DOCUMENT_AGENT()}",
                    f"agent:{ORCHESTRATOR_AGENT()}",
                    f"agent:{MEDIA_AGENT()}",
                ],
            }
        finally:
            client.close()
    except Exception as exc:
        logger.warning("foundry.runtime: agent pipeline failed (%s)", exc)
        return {
            "source": "foundry_agent_pipeline_error",
            "workflow": None,
            "message": "",
            "plan": None,
            "error": f"Live agent pipeline failed: {exc}",
            "trace_tags": ["source:foundry_agent_pipeline_error", "live:false"],
        }


def invoke_workflow(user_text: str, *, timeout_s: float = 90.0) -> dict[str, Any] | None:
    """Run the Foundry workflow agent (also appears under Tracing)."""
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
        status = "running"
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            fetched = openai_client.responses.retrieve(resp.id)
            status = fetched.status
            if fetched.status in ("completed", "failed", "cancelled"):
                output_text = (fetched.output_text or "").strip()
                break
            time.sleep(2)
        else:
            status = "timeout"
        openai_client.conversations.delete(conversation_id=conversation.id)
        client.close()
        if not output_text and status != "completed":
            return {
                "source": "foundry_workflow",
                "workflow": name,
                "status": status,
                "message": "",
                "trace_tags": ["source:foundry_workflow", f"workflow:{name}", "trace:genai"],
            }
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
        return {
            "source": "foundry_workflow_error",
            "workflow": name,
            "status": "error",
            "message": "",
            "error": f"Workflow invoke failed: {exc}",
            "trace_tags": ["source:foundry_workflow_error", f"workflow:{name}", "live:false"],
        }


def run_traced_orchestration(
    user_text: str,
    *,
    lang: str = "es",
    trigger: str = "chat",
) -> dict[str, Any]:
    """
    GOD path — Traces first, then workflow (Gemini agents):
      1) arm GenAI Traces / App Insights
      2) ensure agents + workflow exist (model=MODEL_DEPLOYMENT_NAME, default Gemini)
      3) invoke Foundry WORKFLOW under those traces (primary)
      4) if workflow empty, fall back to per-agent pipeline (still under Traces)
      5) offline brain only if PROJECT_CONNECTION_STRING is missing
    """
    from brain import run_turn  # type: ignore

    insights = bool(_app_insights())
    model_name = MODEL()

    if not _project():
        brain = run_turn(user_text, lang=lang, use_foundry=False)
        return {
            "source": "foundry_brain_offline",
            "workflow": None,
            "message": brain.get("final_user_message") or "",
            "plan": brain.get("plan"),
            "trace_tags": list(brain.get("trace_tags") or [])
            + [f"trigger:{trigger}", "live:false", f"model:{model_name}"],
            "tracing_enabled": False,
            "app_insights_enabled": False,
            "agents_ensured": False,
            "live": False,
            "model": model_name,
            "tool_results": brain.get("tool_results"),
            "trigger": trigger,
            "error": (
                "NO LLEGÓ A FOUNDRY: falta PROJECT_CONNECTION_STRING en app/.env y foundry/.env. "
                "Copia el Project endpoint de juliancuray-7914 → Overview. "
                "Sin eso Chat corre Plan offline y Traces no se actualizan."
            ),
        }

    # 1) Traces ON before any agent/workflow call
    tracing = setup_tracing()
    # 2) Agents + workflow (Gemini) must exist
    ensured = ensure_agents_and_workflow()
    if not ensured:
        return {
            "source": "foundry_ensure_failed",
            "workflow": None,
            "message": "",
            "plan": None,
            "trace_tags": [f"trigger:{trigger}", "live:false", f"model:{model_name}"],
            "tracing_enabled": tracing,
            "app_insights_enabled": insights,
            "agents_ensured": False,
            "live": False,
            "model": model_name,
            "trigger": trigger,
            "error": (
                "NO LLEGÓ A FOUNDRY: no se pudieron crear/listar agentes. "
                "Corre `az login`, verifica PROJECT_CONNECTION_STRING y "
                f"MODEL_DEPLOYMENT_NAME={model_name} (deploy Gemini in Foundry → Models)."
            ),
        }

    tagged = f"[trigger:{trigger}] [model:{model_name}] {user_text}"

    # 3) Primary: Foundry workflow graph under Traces
    workflow_payload = invoke_workflow(tagged)
    workflow_msg = (workflow_payload or {}).get("message") or ""
    workflow_err = (workflow_payload or {}).get("error")
    if not workflow_err:
        if workflow_payload is None:
            workflow_err = "Workflow invoke returned None (auth/endpoint/model?)."
        elif not workflow_msg:
            workflow_err = (
                f"Workflow '{WORKFLOW_AGENT()}' status="
                f"{(workflow_payload or {}).get('status')} but empty text."
            )

    # 4) Fallback: per-agent pipeline still under the same Traces session
    pipeline = None
    if not workflow_msg:
        pipeline = invoke_agent_pipeline(tagged)

    brain = run_turn(user_text, lang=lang, use_foundry=False)
    pipeline_msg = (pipeline or {}).get("message") or ""
    plan = (pipeline or {}).get("plan") or brain.get("plan")
    message = workflow_msg or pipeline_msg or brain.get("final_user_message") or ""
    tags: list[str] = [f"model:{model_name}", f"provider:gemini"]
    for src in (workflow_payload, pipeline, brain):
        if src:
            tags.extend(src.get("trace_tags") or [])
    tags.append(f"trigger:{trigger}")
    if tracing:
        tags.append("trace:genai")
    if insights:
        tags.append("appinsights:on")
    else:
        tags.append("appinsights:off")

    live_ok = bool(workflow_msg or pipeline_msg)
    tags.append("live:true" if live_ok else "live:false")
    if workflow_msg:
        tags.append("path:workflow")
    elif pipeline_msg:
        tags.append("path:agent_pipeline_fallback")

    seen: set[str] = set()
    uniq = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            uniq.append(t)

    err = None
    if not live_ok:
        err = (
            (pipeline or {}).get("error")
            or workflow_err
            or (
                "NO LLEGÓ A FOUNDRY (live vacío): revisa az login + endpoint + "
                f"MODEL_DEPLOYMENT_NAME={model_name}. "
                "Abre Traces en ignite-document-workflow / ignite-document-agent / "
                "ignite-media-agent / ignite-orchestrator-agent "
                "(NO ignite-image-agent) → Last day → Refresh."
            )
        )
    elif not insights:
        err = (
            "Workflow/agents sí corrieron, pero APPLICATIONINSIGHTS_CONNECTION_STRING falta — "
            "algunas vistas de Traces/Monitor pueden quedar vacías. "
            "Cópiala desde Foundry → Tracing / Application Insights."
        )
    elif workflow_err and pipeline_msg:
        err = f"Workflow vacío ({workflow_err}) — usé agent pipeline fallback."

    if workflow_msg:
        source = (workflow_payload or {}).get("source") or "foundry_workflow"
    elif pipeline_msg:
        source = (pipeline or {}).get("source") or "foundry_agent_pipeline"
    elif pipeline and pipeline.get("error"):
        source = pipeline.get("source") or "foundry_agent_pipeline_error"
    else:
        source = "foundry_partial"

    return {
        "source": source,
        "workflow": (workflow_payload or {}).get("workflow") or WORKFLOW_AGENT(),
        "message": message,
        "plan": plan,
        "trace_tags": uniq,
        "tracing_enabled": tracing,
        "app_insights_enabled": insights,
        "agents_ensured": ensured,
        "live": live_ok,
        "model": model_name,
        "tool_results": brain.get("tool_results"),
        "trigger": trigger,
        "error": err,
    }

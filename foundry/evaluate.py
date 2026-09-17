"""
Level 3 — Quality evaluations against ignite-document-agent.

Creates a Foundry eval (fluency + task adherence) and a run on the golden queries.
Also prints the portal path: Foundry → Build → Evaluations.

Upload foundry/eval/eval_portal.jsonl in the portal if you prefer the UI-only path
(Challenge 3 in FrontierWeekHack).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

FOUNDRY_DIR = Path(__file__).resolve().parent
load_dotenv(FOUNDRY_DIR / ".env")

PROJECT_CONNECTION_STRING = (os.getenv("PROJECT_CONNECTION_STRING") or "").strip()
MODEL_DEPLOYMENT_NAME = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-5-mini").strip()
DOCUMENT_AGENT = os.getenv("IGNITE_DOCUMENT_AGENT", "ignite-document-agent").strip()
EVAL_JSONL = FOUNDRY_DIR / "eval" / "eval_portal.jsonl"


def _queries() -> list[str]:
    rows = []
    with EVAL_JSONL.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line)["query"])
    return rows


def main() -> int:
    if not PROJECT_CONNECTION_STRING:
        print("Set PROJECT_CONNECTION_STRING in foundry/.env")
        return 1

    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import DataSourceConfigCustom
    from azure.identity import DefaultAzureCredential

    client = AIProjectClient(
        endpoint=PROJECT_CONNECTION_STRING,
        credential=DefaultAzureCredential(),
    )
    openai_client = client.get_openai_client()

    existing = {a.name for a in client.agents.list()}
    if DOCUMENT_AGENT not in existing:
        print(f"{DOCUMENT_AGENT} missing — run python agents.py first")
        client.close()
        return 1

    agent = next(a for a in client.agents.list() if a.name == DOCUMENT_AGENT)

    data_source_config = DataSourceConfigCustom(
        type="custom",
        item_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        include_sample_schema=True,
    )
    testing_criteria = [
        {
            "type": "azure_ai_evaluator",
            "name": "fluency",
            "evaluator_name": "builtin.fluency",
            "initialization_parameters": {"deployment_name": MODEL_DEPLOYMENT_NAME},
            "data_mapping": {"query": "{{item.query}}", "response": "{{sample.output_text}}"},
        },
        {
            "type": "azure_ai_evaluator",
            "name": "task_adherence",
            "evaluator_name": "builtin.task_adherence",
            "initialization_parameters": {"deployment_name": MODEL_DEPLOYMENT_NAME},
            "data_mapping": {"query": "{{item.query}}", "response": "{{sample.output_items}}"},
        },
    ]
    eval_object = openai_client.evals.create(
        name="Ignite document-agent evaluation",
        data_source_config=data_source_config,
        testing_criteria=testing_criteria,
    )
    content = [{"item": {"query": q}} for q in _queries()]
    data_source = {
        "type": "azure_ai_target_completions",
        "source": {"type": "file_content", "content": content},
        "input_messages": {
            "type": "template",
            "template": [
                {
                    "type": "message",
                    "role": "user",
                    "content": {"type": "input_text", "text": "{{item.query}}"},
                }
            ],
        },
        "target": {
            "type": "azure_ai_agent",
            "name": agent.name,
            "version": getattr(agent, "version", None) or "1",
        },
    }
    run = openai_client.evals.runs.create(
        eval_id=eval_object.id,
        name=f"Ignite eval run for {agent.name}",
        data_source=data_source,
    )
    print(f"Evaluation id: {eval_object.id}")
    print(f"Run id: {run.id}")
    print("Open Foundry → Build → Evaluations. Prefer Coherence/Fluency in the UI; skip Tool Call Accuracy (local tools).")
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

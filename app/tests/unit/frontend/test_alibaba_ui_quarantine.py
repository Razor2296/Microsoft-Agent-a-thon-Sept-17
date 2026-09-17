"""
AlibabaCloud must stay UI-quarantined (skill core / coding §12.5).
"""
from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[3]


def test_base_providers_exclude_alibaba():
    state_js = (APP_ROOT / "frontend" / "js" / "state.js").read_text(encoding="utf-8")
    assert 'baseProviders = ["Gemini", "DeepSeek", "OpenAI", "Anthropic", "Perplexity", "Grok"]' in state_js
    assert "AlibabaCloud" not in state_js.split("baseProviders")[1].split(";")[0]


def test_fsm_init_excludes_alibaba():
    fsm = (APP_ROOT / "frontend" / "js" / "stateMachine.js").read_text(encoding="utf-8")
    # Active FSM bootstrap list must not include AlibabaCloud
    assert 'baseProviderIds = ["Gemini", "DeepSeek", "OpenAI", "Anthropic", "Perplexity", "Grok"]' in fsm


def test_status_dashboard_excludes_alibaba():
    app_js = (APP_ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'const providers = ["Gemini", "OpenAI", "DeepSeek", "Anthropic", "Perplexity", "Grok"]' in app_js

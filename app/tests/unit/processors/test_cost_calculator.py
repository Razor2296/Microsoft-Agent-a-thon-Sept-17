"""
app/tests/unit/test_cost_calculator.py
Unit tests for the USD Cost Calculator module (environment-driven).
"""
import os
import pytest
from dotenv import load_dotenv, find_dotenv

# Try loading .env if available locally
dotenv_path = find_dotenv('.env', usecwd=True)
if not dotenv_path:
    for p in ['.env', 'app/.env', '../app/.env', '../.env']:
        if os.path.exists(p):
            dotenv_path = p
            break

if dotenv_path:
    load_dotenv(dotenv_path)

from backend.processors.cost_calculator import calculate_cost_usd, calculate_media_cost_usd, get_model_pricing_from_env
from backend.core.schemas import TokenInfo


class TestCostCalculator:

    def test_gemini_pricing_calculation(self, monkeypatch):
        # 1,000,000 prompt tokens + 1,000,000 completion tokens for gemini-3.1-pro-preview
        # $1.25 + $5.00 = $6.25
        monkeypatch.setenv("MODEL_PRICE_GEMINI_3_1_PRO_PREVIEW_INPUT", "1.25")
        monkeypatch.setenv("MODEL_PRICE_GEMINI_3_1_PRO_PREVIEW_OUTPUT", "5.00")
        cost = calculate_cost_usd("gemini-3.1-pro-preview", 1_000_000, 1_000_000)
        assert pytest.approx(cost, 0.001) == 6.25

    def test_openai_pricing_calculation(self, monkeypatch):
        # 1,000,000 prompt tokens + 1,000,000 completion tokens for gpt-5.6-sol
        # $2.50 + $10.00 = $12.50
        monkeypatch.setenv("MODEL_PRICE_GPT_5_6_SOL_INPUT", "2.50")
        monkeypatch.setenv("MODEL_PRICE_GPT_5_6_SOL_OUTPUT", "10.00")
        cost = calculate_cost_usd("gpt-5.6-sol", 1_000_000, 1_000_000)
        assert pytest.approx(cost, 0.001) == 12.50

    def test_anthropic_pricing_calculation(self, monkeypatch):
        # 1,000,000 prompt tokens + 1,000,000 completion tokens for claude-sonnet-5
        # $3.00 + $15.00 = $18.00
        monkeypatch.setenv("MODEL_PRICE_CLAUDE_SONNET_5_INPUT", "3.00")
        monkeypatch.setenv("MODEL_PRICE_CLAUDE_SONNET_5_OUTPUT", "15.00")
        cost = calculate_cost_usd("claude-sonnet-5", 1_000_000, 1_000_000)
        assert pytest.approx(cost, 0.001) == 18.00

    def test_deepseek_pricing_calculation(self, monkeypatch):
        # 1,000,000 prompt tokens + 1,000,000 completion tokens for deepseek-v4-pro
        # $0.27 + $1.10 = $1.37
        monkeypatch.setenv("MODEL_PRICE_DEEPSEEK_V4_PRO_INPUT", "0.27")
        monkeypatch.setenv("MODEL_PRICE_DEEPSEEK_V4_PRO_OUTPUT", "1.10")
        cost = calculate_cost_usd("deepseek-v4-pro", 1_000_000, 1_000_000)
        assert pytest.approx(cost, 0.001) == 1.37

    def test_zero_tokens_returns_zero(self):
        assert calculate_cost_usd("gpt-4o", 0, 0) == 0.0

    def test_empty_model_name(self):
        assert calculate_cost_usd("", 100, 100) == 0.0

    def test_dynamic_env_override(self, monkeypatch):
        monkeypatch.setenv("MODEL_PRICE_TEST_MODEL_INPUT", "5.00")
        monkeypatch.setenv("MODEL_PRICE_TEST_MODEL_OUTPUT", "20.00")
        cost = calculate_cost_usd("test-model", 1_000_000, 1_000_000)
        assert pytest.approx(cost, 0.001) == 25.00

    def test_media_cost_calculation(self):
        img_cost = calculate_media_cost_usd("gpt-image-1", count=2)
        assert img_cost >= 0.0

    def test_token_info_integration(self):
        cost = calculate_cost_usd("gemini-2.5-flash", 10_000, 10_000)
        t_info = TokenInfo(prompt_tokens=10_000, completion_tokens=10_000, cost_usd=cost)
        assert t_info.cost_usd >= 0.0
        assert t_info.to_legacy_dict()["cost_usd"] == round(cost, 6)


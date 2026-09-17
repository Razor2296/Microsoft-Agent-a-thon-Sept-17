"""
app/plugins/sample_calculator.py
Sample Plugin for Ignite Chat Skill Store (Skill 2.8).

Demonstrates a custom math calculator plugin loaded dynamically by SkillLoader.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from backend.core.schemas import PluginExecutionResult
from backend.tools.skill_loader import BasePlugin


class CalculatorPlugin(BasePlugin):
    """A dynamic calculator plugin for safe evaluation of math expressions."""

    name: str = "calculator"
    version: str = "1.0.0"
    description: str = "Evaluates basic mathematical expressions safely."
    author: str = "Ignite Team"
    commands: list[str] = ["/calc", "calculator", "math"]
    enabled: bool = True

    def execute(self, user_input: str, context: Optional[Dict[str, Any]] = None) -> PluginExecutionResult:
        """Parse and evaluate math expression safely."""
        expr = user_input.strip()
        # Remove slash command prefix if present
        if expr.startswith("/calc"):
            expr = expr[5:].strip()

        if not expr:
            return PluginExecutionResult(
                success=False,
                plugin_name=self.name,
                error="No math expression provided. Usage: /calc <expression>",
            )

        # Sanitize input: allow only numbers, basic operators, spaces, parentheses
        if not re.match(r"^[0-9\.\+\-\*\/\(\)\s]+$", expr):
            return PluginExecutionResult(
                success=False,
                plugin_name=self.name,
                error="Invalid characters in math expression. Only numbers and + - * / () are allowed.",
            )

        try:
            # Safe eval with no globals or builtins
            calc_res = eval(expr, {"__builtins__": None}, {})
            return PluginExecutionResult(
                success=True,
                plugin_name=self.name,
                output=f"📊 Result of `{expr}` = **{calc_res}**",
                data={"expression": expr, "result": calc_res},
            )
        except Exception as err:
            return PluginExecutionResult(
                success=False,
                plugin_name=self.name,
                error=f"Evaluation error: {str(err)}",
            )

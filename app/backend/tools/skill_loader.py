"""
app/backend/skill_loader.py
Skill 2.8 — Skill Store & Dynamic Plugin Loader for Ignite Chat.

Enables hot-loading, dynamic reloading, discovery, and isolated execution
of custom Python plugins (.py files) from the app/plugins/ directory
without restarting the desktop application or PyWebView container.

LLM Reference: See app/skills/02_core_features/SKILLS_CORE.md § 2.8
"""
from __future__ import annotations

import abc
import importlib.util
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Type

from backend.core.libraries import get_assistant_logger
from backend.core.schemas import PluginExecutionResult, PluginMetadata

logger = get_assistant_logger("skill_loader")


class BasePlugin(abc.ABC):
    """
    Abstract Protocol / Base Class that every Ignite Chat plugin must inherit from.
    """

    name: str = "base_plugin"
    version: str = "1.0.0"
    description: str = "Base plugin specification"
    author: str = "System"
    commands: List[str] = []
    enabled: bool = True

    def get_metadata(self) -> PluginMetadata:
        """Returns a validated Pydantic V2 PluginMetadata instance."""
        return PluginMetadata(
            name=self.name,
            version=self.version,
            description=self.description,
            author=self.author,
            commands=self.commands,
            enabled=self.enabled,
        )

    @abc.abstractmethod
    def execute(self, user_input: str, context: Optional[Dict[str, Any]] = None) -> PluginExecutionResult:
        """
        Execute plugin logic.

        Args:
            user_input: The user text or command parameters passed to the plugin.
            context: Optional dictionary containing runtime state (language, user name, etc.).

        Returns:
            PluginExecutionResult envelope containing success status, output text, and timing.
        """
        pass


class SkillLoader:
    """
    Manager responsible for discovering, hot-loading, reloading,
    and safely executing dynamic plugins from app/plugins/.
    """

    def __init__(self, plugins_dir: Optional[str] = None):
        if plugins_dir is None:
            # Default location: app/plugins/
            current_dir = os.path.dirname(os.path.abspath(__file__))
            app_dir = os.path.dirname(current_dir)
            plugins_dir = os.path.join(app_dir, "plugins")

        self.plugins_dir = plugins_dir
        self._loaded_plugins: Dict[str, BasePlugin] = {}
        self._ensure_plugins_dir_exists()

    def _ensure_plugins_dir_exists(self) -> None:
        """Ensure the target plugins directory exists on disk."""
        if not os.path.exists(self.plugins_dir):
            try:
                os.makedirs(self.plugins_dir, exist_ok=True)
                logger.info(f"Created plugins directory at: {self.plugins_dir}")
            except Exception as err:
                logger.error(f"Failed to create plugins directory ({self.plugins_dir}): {err}")

    def load_plugins(self) -> Dict[str, BasePlugin]:
        """
        Scan the plugins directory, discover .py modules, instantiate BasePlugin classes,
        and register them in memory. Safe against broken modules.
        """
        if not os.path.exists(self.plugins_dir):
            return {}

        discovered_count = 0
        for filename in os.listdir(self.plugins_dir):
            if filename.endswith(".py") and not filename.startswith(("_", ".")):
                file_path = os.path.join(self.plugins_dir, filename)
                plugin_name = os.path.splitext(filename)[0]
                try:
                    plugin_instance = self._load_plugin_from_file(file_path, plugin_name)
                    if plugin_instance and plugin_instance.enabled:
                        self._loaded_plugins[plugin_instance.name] = plugin_instance
                        discovered_count += 1
                        logger.info(
                            f"Successfully loaded plugin '{plugin_instance.name}' v{plugin_instance.version} "
                            f"from {filename}"
                        )
                except Exception as err:
                    logger.error(f"Failed to hot-load plugin file '{filename}': {err}", exc_info=True)

        logger.info(f"SkillLoader: Total active plugins loaded: {discovered_count}")
        return self._loaded_plugins

    def reload_plugins(self) -> Dict[str, BasePlugin]:
        """
        Hot-reload all plugins from disk without restarting the application.
        Clears current in-memory cache and re-scans the directory.
        """
        logger.info("Hot-reloading all dynamic plugins...")
        self._loaded_plugins.clear()
        return self.load_plugins()

    def _load_plugin_from_file(self, file_path: str, module_name: str) -> Optional[BasePlugin]:
        """Dynamically import a Python file using importlib and extract the BasePlugin subclass."""
        spec = importlib.util.spec_from_file_location(f"ignite_plugins.{module_name}", file_path)
        if spec is None or spec.loader is None:
            logger.warning(f"Could not create module spec for plugin: {file_path}")
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        # Inspect module for concrete subclass of BasePlugin
        for attr_name in dir(module):
            attr_val = getattr(module, attr_name)
            if (
                isinstance(attr_val, type)
                and issubclass(attr_val, BasePlugin)
                and attr_val is not BasePlugin
            ):
                instance = attr_val()
                return instance

        logger.warning(f"No concrete BasePlugin subclass found in '{file_path}'")
        return None

    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        """Retrieve a loaded plugin instance by its unique name."""
        return self._loaded_plugins.get(name)

    def list_plugins_metadata(self) -> List[PluginMetadata]:
        """Return a list of PluginMetadata for all currently active plugins."""
        return [plugin.get_metadata() for plugin in self._loaded_plugins.values() if plugin.enabled]

    def execute_plugin(self, name: str, user_input: str, context: Optional[Dict[str, Any]] = None) -> PluginExecutionResult:
        """
        Execute a plugin safely with isolated error handling and latency tracking.
        """
        plugin = self.get_plugin(name)
        if not plugin or not plugin.enabled:
            return PluginExecutionResult(
                success=False,
                plugin_name=name,
                error=f"Plugin '{name}' is not loaded or disabled.",
            )

        start_time = time.time()
        try:
            res = plugin.execute(user_input, context)
            elapsed_ms = (time.time() - start_time) * 1000.0
            if isinstance(res, PluginExecutionResult):
                if res.execution_time_ms == 0.0:
                    return PluginExecutionResult(
                        success=res.success,
                        plugin_name=res.plugin_name,
                        output=res.output,
                        data=res.data,
                        execution_time_ms=round(elapsed_ms, 2),
                        error=res.error,
                    )
                return res
            else:
                return PluginExecutionResult(
                    success=True,
                    plugin_name=name,
                    output=str(res),
                    execution_time_ms=round(elapsed_ms, 2),
                )
        except Exception as err:
            elapsed_ms = (time.time() - start_time) * 1000.0
            logger.error(f"Execution error in plugin '{name}': {err}", exc_info=True)
            return PluginExecutionResult(
                success=False,
                plugin_name=name,
                error=f"Plugin error: {str(err)}",
                execution_time_ms=round(elapsed_ms, 2),
            )

    def get_system_instruction_prompt(self) -> str:
        """
        Generate a structured prompt snippet describing available plugins for LLM system instructions.
        """
        active_plugins = self.list_plugins_metadata()
        if not active_plugins:
            return ""

        lines = ["[DYNAMIC SKILL STORE PLUGINS] Available custom tools:"]
        for meta in active_plugins:
            cmds = ", ".join(meta.commands) if meta.commands else "No slash commands"
            lines.append(f"- **{meta.name}** (v{meta.version}): {meta.description} (Commands: {cmds})")
        lines.append("If the user's prompt matches a plugin command, you can reference its capabilities.")
        return "\n".join(lines)

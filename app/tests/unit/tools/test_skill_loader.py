"""
app/tests/unit/test_skill_loader.py
Unit tests for Skill 2.8 — Skill Store & Dynamic Plugin Loader

LLM Reference: app/skills/02_core_features/SKILLS_CORE.md § 2.8
"""
import os
import shutil
import tempfile
import pytest
from pydantic import ValidationError

from backend.core.schemas import PluginExecutionResult, PluginMetadata
from backend.tools.skill_loader import BasePlugin, SkillLoader


class TestPluginMetadataAndSchemas:
    """Test Pydantic V2 schemas for Skill 2.8."""

    def test_valid_plugin_metadata(self):
        meta = PluginMetadata(
            name="test_plugin",
            version="1.2.0",
            description="A test plugin description",
            author="Developer",
            commands=["/test"],
            enabled=True,
        )
        assert meta.name == "test_plugin"
        assert meta.version == "1.2.0"
        assert meta.commands == ["/test"]
        assert meta.enabled is True

    def test_frozen_metadata_immutable(self):
        meta = PluginMetadata(name="test", description="desc")
        with pytest.raises(ValidationError):
            meta.name = "new_name"  # type: ignore

    def test_plugin_execution_result_defaults(self):
        res = PluginExecutionResult(
            success=True,
            plugin_name="test_plugin",
            output="Done!",
        )
        assert res.success is True
        assert res.output == "Done!"
        assert res.execution_time_ms == 0.0
        assert res.error is None


class DummyPlugin(BasePlugin):
    name = "dummy"
    version = "1.0.0"
    description = "Dummy test plugin"
    author = "Tester"
    commands = ["/dummy"]

    def execute(self, user_input: str, context=None) -> PluginExecutionResult:
        return PluginExecutionResult(
            success=True,
            plugin_name=self.name,
            output=f"Echo: {user_input}",
        )


class TestBasePluginProtocol:
    """Test BasePlugin class interface."""

    def test_get_metadata_returns_valid_pydantic_model(self):
        plugin = DummyPlugin()
        meta = plugin.get_metadata()
        assert isinstance(meta, PluginMetadata)
        assert meta.name == "dummy"
        assert meta.commands == ["/dummy"]

    def test_execution_returns_result(self):
        plugin = DummyPlugin()
        res = plugin.execute("Hello")
        assert res.success is True
        assert res.output == "Echo: Hello"


class TestSkillLoaderLifecycle:
    """Test SkillLoader plugin discovery, hot-reloading, and execution isolation."""

    @pytest.fixture
    def temp_plugins_dir(self):
        tmp_dir = tempfile.mkdtemp(prefix="ignite_test_plugins_")
        yield tmp_dir
        shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_discovers_and_loads_plugin_file(self, temp_plugins_dir):
        # Create a valid plugin file in temp directory
        plugin_code = """
from backend.tools.skill_loader import BasePlugin
from backend.core.schemas import PluginExecutionResult

class WeatherPlugin(BasePlugin):
    name = "weather"
    version = "2.0.0"
    description = "Fetches weather information"
    commands = ["/weather"]

    def execute(self, user_input: str, context=None) -> PluginExecutionResult:
        return PluginExecutionResult(
            success=True,
            plugin_name=self.name,
            output=f"Sunny in {user_input}"
        )
"""
        plugin_file = os.path.join(temp_plugins_dir, "weather.py")
        with open(plugin_file, "w", encoding="utf-8") as f:
            f.write(plugin_code)

        loader = SkillLoader(plugins_dir=temp_plugins_dir)
        plugins = loader.load_plugins()

        assert "weather" in plugins
        assert loader.get_plugin("weather") is not None
        metas = loader.list_plugins_metadata()
        assert len(metas) == 1
        assert metas[0].name == "weather"
        assert metas[0].version == "2.0.0"

        # Execute plugin
        res = loader.execute_plugin("weather", "Lima")
        assert res.success is True
        assert res.output == "Sunny in Lima"
        assert res.execution_time_ms >= 0.0

    def test_hot_reloading_new_plugin(self, temp_plugins_dir):
        loader = SkillLoader(plugins_dir=temp_plugins_dir)
        assert len(loader.load_plugins()) == 0

        # Dynamically add a plugin file at runtime
        plugin_code = """
from backend.tools.skill_loader import BasePlugin
from backend.core.schemas import PluginExecutionResult

class GreeterPlugin(BasePlugin):
    name = "greeter"
    description = "Greets the user"

    def execute(self, user_input: str, context=None) -> PluginExecutionResult:
        return PluginExecutionResult(success=True, plugin_name=self.name, output=f"Hello {user_input}")
"""
        with open(os.path.join(temp_plugins_dir, "greeter.py"), "w", encoding="utf-8") as f:
            f.write(plugin_code)

        # Hot-reload without restarting loader instance
        reloaded = loader.reload_plugins()
        assert "greeter" in reloaded
        res = loader.execute_plugin("greeter", "Julian")
        assert res.output == "Hello Julian"

    def test_faulty_plugin_file_isolation(self, temp_plugins_dir):
        # Create a plugin with syntax error
        broken_code = "class BrokenPlugin(BasePlugin): invalid syntax syntax error"
        with open(os.path.join(temp_plugins_dir, "broken.py"), "w", encoding="utf-8") as f:
            f.write(broken_code)

        loader = SkillLoader(plugins_dir=temp_plugins_dir)
        # Should not crash during load
        loaded = loader.load_plugins()
        assert "broken" not in loaded

    def test_plugin_runtime_exception_isolation(self, temp_plugins_dir):
        # Create a plugin that raises runtime exception during execute()
        buggy_code = """
from backend.tools.skill_loader import BasePlugin

class BuggyPlugin(BasePlugin):
    name = "buggy"
    description = "Always crashes"

    def execute(self, user_input: str, context=None):
        raise ValueError("Simulated runtime crash!")
"""
        with open(os.path.join(temp_plugins_dir, "buggy.py"), "w", encoding="utf-8") as f:
            f.write(buggy_code)

        loader = SkillLoader(plugins_dir=temp_plugins_dir)
        loader.load_plugins()

        # Should capture exception gracefully without crashing assistant
        res = loader.execute_plugin("buggy", "test")
        assert res.success is False
        assert "Simulated runtime crash!" in res.error

    def test_get_system_instruction_prompt(self, temp_plugins_dir):
        loader = SkillLoader(plugins_dir=temp_plugins_dir)
        # Initially empty prompt
        assert loader.get_system_instruction_prompt() == ""

        # Add sample plugin
        plugin_code = """
from backend.tools.skill_loader import BasePlugin

class NotePlugin(BasePlugin):
    name = "notes"
    description = "Save personal notes"
    commands = ["/note"]

    def execute(self, user_input: str, context=None):
        pass
"""
        with open(os.path.join(temp_plugins_dir, "notes.py"), "w", encoding="utf-8") as f:
            f.write(plugin_code)

        loader.load_plugins()
        prompt = loader.get_system_instruction_prompt()
        assert "[DYNAMIC SKILL STORE PLUGINS]" in prompt
        assert "notes" in prompt
        assert "/note" in prompt

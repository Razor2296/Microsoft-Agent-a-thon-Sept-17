"""Unit tests for the FastAPI hybrid backend surface."""

from server.main import ALLOWED_METHODS


def test_critical_desktop_methods_are_allowed():
    required = {
        "get_initial_state",
        "send_message_async",
        "get_generation_status",
        "set_provider",
        "set_model",
    }
    assert required.issubset(ALLOWED_METHODS)


def test_disallowed_private_methods_not_exported():
    assert "_save_conversation_history" not in ALLOWED_METHODS
    assert "__init__" not in ALLOWED_METHODS

"""ContextVar isolation for concurrent desktop identities on ACA."""

import contextvars

from backend.core.runtime_identity import get_runtime_user_name, set_runtime_user_name


def test_runtime_user_name_is_context_local():
    set_runtime_user_name(None)

    def in_context(name: str) -> str:
        set_runtime_user_name(name)
        return get_runtime_user_name()

    ctx_a = contextvars.copy_context()
    ctx_b = contextvars.copy_context()
    name_a = ctx_a.run(in_context, "Julian")
    name_b = ctx_b.run(in_context, "Maria")
    assert name_a == "Julian"
    assert name_b == "Maria"

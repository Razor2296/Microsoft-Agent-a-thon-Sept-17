"""
resolve_reply_language must honor English force_language (never remap en→es-ES).
"""
from backend.processors.base_processor import resolve_reply_language


def test_resolve_reply_language_honors_english():
    code, name = resolve_reply_language("en-US", user_input="hello there friend")
    assert code.startswith("en")
    assert "English" in name
    assert not code.lower().startswith("es")


def test_resolve_reply_language_honors_french():
    code, name = resolve_reply_language("fr-FR", user_input="bonjour")
    assert code.startswith("fr")
    assert "French" in name


def test_resolve_reply_language_honors_spanish():
    code, name = resolve_reply_language("es-MX", user_input="hola")
    assert code.startswith("es")
    assert "Spanish" in name

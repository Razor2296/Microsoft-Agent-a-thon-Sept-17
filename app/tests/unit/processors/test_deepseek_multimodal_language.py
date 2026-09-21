"""
DeepSeek multimodal must keep reply language even when Gemini captions exist.
Anti-regression: Spanish image asks must not get English privacy refusals.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import backend.processors.deepseek_processor as dp
from backend.processors.base_processor import (
    mandatory_reply_language_note,
    multimodal_describe_prompt,
)


def test_multimodal_describe_prompt_requires_spanish_narrative():
    prompt = multimodal_describe_prompt("Spanish", media="image")
    assert "Spanish" in prompt
    assert "Do not switch to English" in prompt


def test_mandatory_reply_language_note_covers_privacy_refusals_es():
    note = mandatory_reply_language_note("es-MX", "Spanish")
    assert "Español" in note or "ESPAÑOL" in note
    assert "privacidad" in note.lower()


def test_deepseek_inline_image_injects_spanish_language_guards():
    chat = dp.DeepSeekChat.__new__(dp.DeepSeekChat)
    chat.deepseek_client = MagicMock()
    chat.model_version = "deepseek-chat"
    chat.temperature = 0.7
    chat.top_p = 1.0
    chat.max_tokens = 1024
    chat.system_instruction_deepseek = "You are DeepSeek."
    chat.client = MagicMock()
    chat._accumulate_aux_tokens = MagicMock()
    chat._flush_aux_tokens = MagicMock(side_effect=lambda t: t)
    chat._should_attach_web_search = MagicMock(return_value=False)
    chat._process_urls_in_input = MagicMock(side_effect=lambda text, force_language=None: (text, []))
    chat.normalize_image_media_type = MagicMock(side_effect=lambda mime, data: (data, mime))
    chat._resize_image_data = MagicMock(side_effect=lambda data, max_dim=1024: data)

    vision_resp = SimpleNamespace(text="Una mujer sentada en una habitación iluminada.")
    chat.client.models.generate_content = MagicMock(return_value=vision_resp)

    captured = {}

    def _create(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Puedo describir la imagen, pero no identificar a la persona."
                    )
                )
            ]
        )

    chat.deepseek_client.chat.completions.create = MagicMock(side_effect=_create)

    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    files = [{"name": "foto.png", "mime_type": "image/png", "bytes": png_bytes}]

    with patch.object(dp, "USER_CLIPBOARD_TEXT", ""), patch.object(
        dp, "multimodal_describe_prompt", wraps=dp.multimodal_describe_prompt
    ) as describe_prompt:
        reply, _ = chat.generate_response_with_inline_files(
            "¿Quién es ella? descríbeme la foto",
            history=None,
            files=files,
            force_language="es-MX",
        )

    assert "persona" in reply.lower() or "imagen" in reply.lower()
    system = captured["messages"][0]["content"]
    user = captured["messages"][-1]["content"]
    assert "INSTRUCCIÓN MANDATORIA DE IDIOMA" in system
    assert "privacidad" in system.lower()
    assert "Responde enteramente en ESPAÑOL" in user
    describe_prompt.assert_called()
    assert describe_prompt.call_args.args[0] == "Spanish"

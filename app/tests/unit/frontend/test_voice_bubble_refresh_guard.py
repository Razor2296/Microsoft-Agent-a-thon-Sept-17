"""Anti-regresión: hydrate/refresh MUST NOT wipe WhatsApp voice player.

Root cause (shipped): refreshMessageAttachments rebuilt the bubble via
buildMessageAttachmentsHTML, which filters out Voice_Message_* → empty YOU
bubble (only Tokens Consumed + ✓✓).
"""
from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[3]
CHAT_JS = APP_ROOT / "frontend" / "js" / "chat.js"
API_JS = APP_ROOT / "frontend" / "js" / "api.js"


class TestVoiceBubbleRefreshGuard:
    def test_refresh_preserves_voice_or_early_returns(self):
        chat = CHAT_JS.read_text(encoding="utf-8")
        start = chat.find("window.refreshMessageAttachments")
        assert start != -1
        block = chat[start : start + 2500]
        assert "Voice_Message_" in block
        assert "buildVoicePlayerHTML" in block or "isVoice" in block
        # Must not unconditionally wipe with attachments-only rebuild for voice.
        assert "if (isVoice)" in block or "dataset.isVoice" in block

    def test_append_message_marks_voice_wrapper(self):
        chat = CHAT_JS.read_text(encoding="utf-8")
        start = chat.find("function appendMessage")
        assert start != -1
        block = chat[start : start + 8000]
        assert 'dataset.isVoice' in block
        assert "buildVoicePlayerHTML" in block

    def test_send_skips_refresh_for_voice_only(self):
        api = API_JS.read_text(encoding="utf-8")
        start = api.find("async function sendMessage")
        assert start != -1
        block = api[start : start + 14000]
        assert "needsAttachmentRefresh" in block
        assert "Voice_Message_" in block
        # Guard must gate refreshMessageAttachments
        refresh_idx = block.find("refreshMessageAttachments(msgId")
        assert refresh_idx != -1
        gate = block[max(0, refresh_idx - 200) : refresh_idx]
        assert "needsAttachmentRefresh" in gate

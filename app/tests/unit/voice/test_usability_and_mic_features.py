"""
app/tests/unit/test_usability_and_mic_features.py
Unit tests verifying mic permission caching, live transcription UI updates,
optimistic 0ms conversation clearing, WhatsApp-style input locking during LLM reasoning,
and launcher WebView2 process cleanup resilience.
"""

import os
import pytest

FRONTEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend")
)
APP_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)


class TestMicPermissionAndStreamCaching:
    def test_audio_js_defines_cached_mic_stream_and_get_audio_stream(self):
        """Verify audio.js implements cachedMicStream and getAudioStream helper to prevent repeated permission popups."""
        path = os.path.join(FRONTEND_DIR, "js", "audio.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        assert "cachedMicStream" in code, "audio.js MUST define cachedMicStream variable"
        assert "function getAudioStream()" in code, "audio.js MUST define getAudioStream helper"
        assert "ignite_mic_permission_granted" in code, "audio.js MUST set ignite_mic_permission_granted in localStorage"

    def test_audio_js_disables_tracks_instead_of_stopping(self):
        """Verify audio.js disables audio tracks (enabled = false) on stop/discard to keep the stream warm."""
        path = os.path.join(FRONTEND_DIR, "js", "audio.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        assert "track.enabled = false" in code, "audio.js MUST disable audio tracks instead of track.stop() to avoid permission prompt repetition"

    def test_audio_js_whatsapp_voice_message_architecture(self):
        """Verify audio.js packages voice recordings into Voice_Message_*.webm for WhatsApp player bubble & backend transcription."""
        path = os.path.join(FRONTEND_DIR, "js", "audio.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        assert "Voice_Message_" in code, "audio.js MUST create Voice_Message_*.webm attachment for WhatsApp-style voice messaging"
        assert "MediaRecorder" in code, "audio.js MUST use MediaRecorder to capture raw audio"
        assert "Web Audio API analyser setup failed" in code or "createAnalyser" in code, "audio.js MUST use Web Audio analyser for RMS VAD"


class TestOptimisticConversationClear:
    def test_app_js_clear_chat_action_is_optimistic(self):
        """Verify clearChatAction wipes DOM sync and sequences clear_history THEN welcome."""
        path = os.path.join(FRONTEND_DIR, "js", "app.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        pos_clear_action = code.find("clearChatAction")
        assert pos_clear_action != -1, "app.js MUST contain clearChatAction"
        clear_block = code[pos_clear_action : pos_clear_action + 3500]

        assert "chatContainer.innerHTML = ''" in clear_block, "clearChatAction MUST synchronously wipe chatContainer DOM"
        assert "totalTokens = 0" in clear_block, "clearChatAction MUST synchronously reset token count"
        assert "clear_history(clearedProvider)" in clear_block, "clearChatAction MUST call clear_history"
        assert "sendWelcomeMessage()" in clear_block, "clearChatAction MUST render welcome message"
        # Skill §12.1: welcome runs inside afterClear, chained after clear_history resolves.
        assert "afterClear" in clear_block, "clearChatAction MUST define afterClear callback for welcome"
        assert ".then(afterClear)" in clear_block, "clear_history MUST be then'd to afterClear before welcome"
        after_clear_idx = clear_block.find("const afterClear")
        clear_call_idx = clear_block.find("clear_history(clearedProvider)")
        assert after_clear_idx != -1 and clear_call_idx != -1
        assert "sendWelcomeMessage()" in clear_block[after_clear_idx:clear_call_idx], (
            "sendWelcomeMessage MUST live inside afterClear, not before clear_history call"
        )
        assert "updateTokenDisplay(clearedProvider)" in clear_block[after_clear_idx:clear_call_idx], (
            "afterClear MUST refresh token/cost display after clear_history resolves"
        )
        assert "$0.0000 USD" in clear_block, "clearChatAction MUST optimistically zero the USD cost display"

    def test_language_change_uses_is_welcome_not_missing_token_info(self):
        path = os.path.join(FRONTEND_DIR, "js", "app.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
        assert "is_welcome" in code
        assert "!history[0].token_info" not in code, (
            "Language rewrite MUST NOT key off !token_info (welcomes always have token_info)"
        )

class TestWhatsAppDisabledInputBarDuringReasoning:
    def test_state_js_disables_input_bar_when_busy_or_thinking(self):
        """Verify state.js updateInputButtonsState sets msgInput.disabled = true while LLM is reasoning."""
        path = os.path.join(FRONTEND_DIR, "js", "state.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        assert "updateInputButtonsState" in code
        assert "thinkingPlaceholder" in code
        assert "msgInput.disabled = true" in code, "state.js MUST disable msgInput while LLM is thinking"
        assert "Esperando respuesta..." in code, "state.js MUST set 'Esperando respuesta...' placeholder when LLM is thinking"
        assert "Waiting for response..." in code

    def test_state_js_restores_input_bar_when_idle(self):
        """Verify state.js updateInputButtonsState enables msgInput and restores default placeholder when LLM is idle."""
        path = os.path.join(FRONTEND_DIR, "js", "state.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        assert "msgInput.disabled = false" in code
        assert "msgInput.removeAttribute('disabled')" in code
        assert "Escribe tu mensaje..." in code
        assert "Type your message..." in code

    def test_state_machine_apply_ui_effects_disables_input_on_thinking(self):
        """Verify stateMachine.js _applyUIEffects updates inputEl.disabled = true on THINKING state."""
        path = os.path.join(FRONTEND_DIR, "js", "stateMachine.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        assert "case FSM_STATES.THINKING:" in code
        pos_thinking = code.find("case FSM_STATES.THINKING:")
        thinking_block = code[pos_thinking : pos_thinking + 600]

        assert "inputEl.disabled = true" in thinking_block, "stateMachine.js MUST disable inputEl on THINKING state"
        assert "Esperando respuesta..." in thinking_block
        assert "micBtn.disabled  = false" in thinking_block, "stateMachine.js MUST keep micBtn enabled on THINKING state for user interruption"


class TestLauncherResilienceAndWebView2Isolation:
    def test_launcher_defines_kill_orphan_processes(self):
        """Verify launcher_webview.py defines kill_orphan_launcher_processes helper."""
        path = os.path.join(APP_DIR, "launcher_webview.py")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        assert "def kill_orphan_launcher_processes()" in code, "launcher_webview.py MUST define kill_orphan_launcher_processes"
        assert "WEBVIEW2_USER_DATA_FOLDER" in code, "launcher_webview.py MUST set isolated WEBVIEW2_USER_DATA_FOLDER"
        assert "0x800700AA" in code, "launcher_webview.py MUST handle 0x800700AA resource in use exception"
        assert "--use-fake-ui-for-media-stream" in code, "launcher_webview.py MUST set --use-fake-ui-for-media-stream flag"


class TestNativeFileDownloadBridge:
    def test_api_defines_save_file_to_downloads(self):
        """Verify api.py and remote_api_proxy.py define save_file_to_downloads."""
        api_path = os.path.join(APP_DIR, "main", "api.py")
        proxy_path = os.path.join(APP_DIR, "main", "remote_api_proxy.py")

        with open(api_path, "r", encoding="utf-8") as f:
            api_code = f.read()
        with open(proxy_path, "r", encoding="utf-8") as f:
            proxy_code = f.read()

        assert "def save_file_to_downloads(" in api_code, "api.py MUST define save_file_to_downloads"
        assert "def save_file_to_downloads(" in proxy_code, "remote_api_proxy.py MUST define save_file_to_downloads"

    def test_chat_js_uses_save_file_to_downloads(self):
        """Verify chat.js downloadGeneratedImage uses save_file_to_downloads."""
        path = os.path.join(FRONTEND_DIR, "js", "chat.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        assert "save_file_to_downloads" in code, "chat.js MUST call save_file_to_downloads"

    def test_files_js_preview_download_uses_save_file_to_downloads(self):
        path = os.path.join(FRONTEND_DIR, "js", "files.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
        assert "save_file_to_downloads" in code, "files.js overlay download MUST call save_file_to_downloads"


class TestPerModelTokenAndHistoryCaching:
    def test_state_js_defines_provider_tokens(self):
        """Verify state.js initializes window.providerTokens object and updateTokenDisplay per provider."""
        path = os.path.join(FRONTEND_DIR, "js", "state.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        assert "window.providerTokens" in code, "state.js MUST initialize window.providerTokens"
        assert "function updateTokenDisplay(provider)" in code, "state.js updateTokenDisplay MUST accept provider parameter"
        assert "item.provider === targetProv" in code, (
            "updateTokenDisplay MUST show the current provider cost, not the grand total"
        )
        assert "grand_total_cost_usd.toFixed" not in code, (
            "header cost MUST not use grand_total_cost_usd (that value does not reset on clear)"
        )
        assert "applyBudgetFromStats" in code, "state.js MUST render remaining-budget alerts"
        assert "remaining_usd" in code, "state.js MUST display remaining_usd from cost stats"
        assert "res.toast_ms" in code, "budget toast duration MUST come from backend env, not a JS literal"
        assert "#e74c3c" not in code, "budget remaining color MUST use CSS classes, not hardcoded hex"

    def test_app_js_uses_cached_histories_on_switch(self):
        """Verify app.js uses window.cachedHistories on provider switch to eliminate idle loading latency."""
        path = os.path.join(FRONTEND_DIR, "js", "app.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        assert "window.cachedHistories" in code, "app.js MUST use window.cachedHistories for instant 0ms chat switching"
        assert "window.providerTokens[clearedProvider] = 0" in code, "clearChatAction MUST reset providerTokens to 0"


class TestSendButtonRobustness:
    def test_state_js_never_sets_pointer_events_none_on_send_btn(self):
        """Verify state.js sets pointerEvents = 'auto' on sendBtn so click events are never blocked."""
        path = os.path.join(FRONTEND_DIR, "js", "state.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        assert "sendBtn.style.pointerEvents = 'auto'" in code, "state.js MUST set pointerEvents = 'auto' on sendBtn"

    def test_app_js_send_btn_listener_heals_and_sends(self):
        """Verify app.js send-btn listener calls healStuckSendState and handles in-flight interruption."""
        path = os.path.join(FRONTEND_DIR, "js", "app.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        pos_send = code.find("document.getElementById('send-btn').addEventListener")
        assert pos_send != -1, "app.js MUST contain send-btn click listener"
        send_block = code[pos_send : pos_send + 1200]

        assert "healStuckSendState()" in send_block, "send-btn click listener MUST call healStuckSendState()"
        assert "sendMessage()" in send_block, "send-btn click listener MUST call sendMessage()"

    def test_api_js_never_disables_send_btn_on_send(self):
        """Verify api.js never sets sendBtn.disabled = true to avoid Chromium click event suppression."""
        path = os.path.join(FRONTEND_DIR, "js", "api.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        assert "sendBtn.disabled = true" not in code, "api.js MUST NOT set sendBtn.disabled = true on send"

    def test_app_js_uses_bootstrap_app_and_keydown(self):
        """Verify app.js defines bootstrapApp for resilient initialization and uses keydown for Enter key."""
        path = os.path.join(FRONTEND_DIR, "js", "app.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        assert "function bootstrapApp()" in code, "app.js MUST define bootstrapApp for event timing resilience"
        assert "msgInput.addEventListener('keydown'" in code, "app.js MUST use keydown for reliable Enter key press detection"



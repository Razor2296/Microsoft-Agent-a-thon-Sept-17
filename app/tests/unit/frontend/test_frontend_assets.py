"""
app/tests/unit/frontend/test_frontend_assets.py
Layer frontend: static assets, HTML IDs, script order, DevTools security.
"""
import os
import pytest

FRONTEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend")
)


class TestFrontendIndexHTML:
    def test_script_order_state_machine_before_audio(self):
        """Verify stateMachine.js is loaded before audio.js in index.html."""
        path = os.path.join(FRONTEND_DIR, "index.html")
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()

        pos_fsm = html.find("stateMachine.js")
        pos_audio = html.find("audio.js")

        assert pos_fsm != -1, "stateMachine.js not found in index.html"
        assert pos_audio != -1, "audio.js not found in index.html"
        assert pos_fsm < pos_audio, "stateMachine.js MUST be loaded before audio.js"

    def test_required_dom_elements_exist(self):
        """Verify essential interactive DOM elements exist in index.html."""
        path = os.path.join(FRONTEND_DIR, "index.html")
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()

        essential_ids = [
            "id=\"message-input\"",
            "id=\"send-btn\"",
            "id=\"mic-btn\"",
            "id=\"language-select\"",
            "id=\"model-select\"",
        ]
        for elem_id in essential_ids:
            assert elem_id in html, f"Missing essential element ID in HTML: {elem_id}"

    def test_left_rail_and_header_interactive_elements(self):
        """Verify all Left Rail dock buttons and Top Header action buttons have defined IDs."""
        path = os.path.join(FRONTEND_DIR, "index.html")
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()

        rail_ids = [
            "id=\"rail-chats-btn\"",
            "id=\"rail-calls-btn\"",
            "id=\"rail-status-btn\"",
            "id=\"rail-channels-btn\"",
            "id=\"rail-communities-btn\"",
            "id=\"rail-archived-btn\"",
            "id=\"rail-settings-btn\"",
            "id=\"rail-profile-avatar\"",
        ]
        for rid in rail_ids:
            assert rid in html, f"Missing rail button ID in HTML: {rid}"

        header_ids = [
            "id=\"header-video-btn\"",
            "id=\"header-call-btn\"",
            "id=\"header-search-btn\"",
            "id=\"menu-btn\"",
        ]
        for hid in header_ids:
            assert hid in html, f"Missing header action ID in HTML: {hid}"

    def test_interactive_modals_and_overlays_exist(self):
        """Verify all new feature modals and voice call overlays are declared in HTML."""
        path = os.path.join(FRONTEND_DIR, "index.html")
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()

        modal_ids = [
            "id=\"voice-call-overlay\"",
            "id=\"vision-capture-modal\"",
            "id=\"status-overlay-modal\"",
            "id=\"channels-overlay-modal\"",
            "id=\"communities-overlay-modal\"",
            "id=\"archived-overlay-modal\"",
            "id=\"profile-overlay-modal\"",
            "id=\"file-preview-overlay\"",
        ]
        for mid in modal_ids:
            assert mid in html, f"Missing modal ID in HTML: {mid}"


class TestFrontendJSFiles:
    @pytest.mark.parametrize("js_filename", [
        "translations.js",
        "state.js",
        "models.js",
        "stateMachine.js",
        "audio.js",
        "files.js",
        "chat.js",
        "aiGrid.js",
        "api.js",
        "app.js",
    ])
    def test_js_file_exists_and_non_empty(self, js_filename):
        path = os.path.join(FRONTEND_DIR, "js", js_filename)
        assert os.path.exists(path), f"Missing JS asset: {js_filename}"
        assert os.path.getsize(path) > 100, f"JS asset is empty: {js_filename}"

    @pytest.mark.parametrize("js_filename", [
        "translations.js",
        "state.js",
        "models.js",
        "stateMachine.js",
        "audio.js",
        "files.js",
        "chat.js",
        "aiGrid.js",
        "api.js",
        "app.js",
    ])
    def test_js_syntax_validity(self, js_filename):
        """Verify JS file parses without syntax errors using node."""
        import shutil
        import subprocess
        path = os.path.join(FRONTEND_DIR, "js", js_filename)
        assert os.path.exists(path)
        node_bin = shutil.which("node")
        if node_bin:
            res = subprocess.run([node_bin, "--check", path], capture_output=True, text=True)
            assert res.returncode == 0, f"JS Syntax Error in {js_filename}:\n{res.stderr}"

    def test_state_machine_js_exports(self):
        """Verify stateMachine.js contains mandatory FSM states and class definitions."""
        path = os.path.join(FRONTEND_DIR, "js", "stateMachine.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        assert "class StateMachine" in code
        assert "FSM_STATES" in code
        assert "IDLE" in code
        assert "RECORDING" in code
        assert "THINKING" in code
        assert "SPEAKING" in code
        assert "ERROR" in code
        assert "window.getProviderFSM" in code

    def test_devtools_contextmenu_disabled_in_app_js(self):
        """Verify app.js disables default contextmenu (Inspect Element / DevTools)."""
        path = os.path.join(FRONTEND_DIR, "js", "app.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        assert "contextmenu" in code, "app.js MUST contain contextmenu event listener"
        assert "preventDefault" in code, "app.js MUST prevent default on contextmenu to block DevTools"

    def test_download_generated_image_helper_and_icon_button_in_chat_js(self):
        """Verify chat.js defines window.downloadGeneratedImage and uses icon-only button."""
        path = os.path.join(FRONTEND_DIR, "js", "chat.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        assert "window.downloadGeneratedImage" in code, "chat.js MUST define window.downloadGeneratedImage"
        assert "URL.createObjectURL" in code, "downloadGeneratedImage MUST use Blob URL"
        assert "image-download-overlay-btn" in code, "chat.js MUST use image-download-overlay-btn class"
        assert "downloadGeneratedImage(this)" in code, "chat.js MUST trigger downloadGeneratedImage on button click"
        assert "<span>Descargar</span>" not in code, "chat.js MUST use icon-only design without text label"

    def test_generated_image_wrapper_css(self):
        """Verify chat.css contains styles for generated-image-wrapper and circular download button."""
        path = os.path.join(FRONTEND_DIR, "css", "chat.css")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        assert ".generated-image-wrapper" in code, "chat.css MUST contain .generated-image-wrapper"
        assert ".image-download-overlay-btn" in code, "chat.css MUST contain .image-download-overlay-btn"
        assert "border-radius: 50%" in code, "chat.css MUST style overlay button as circular"


class TestLauncherWebviewSecurity:
    def test_launcher_webview_debug_mode_disabled(self):
        """Verify launcher_webview.py sets debug=False by default to hide DevTools popup."""
        launcher_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "launcher_webview.py")
        )
        with open(launcher_path, "r", encoding="utf-8") as f:
            code = f.read()

        assert "debug=True" not in code, "launcher_webview.py MUST NOT hardcode debug=True"
        assert "debug_mode" in code or "debug=" in code, "launcher_webview.py MUST control debug mode via IGNITE_DEBUG"


class TestTranslationsIntegrity:
    def test_translations_file_structure(self):
        path = os.path.join(FRONTEND_DIR, "js", "translations.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        assert "const translations =" in code or "let translations =" in code
        assert '"es":' in code or "'es':" in code or "es:" in code
        assert '"en":' in code or "'en':" in code or "en:" in code
        for key in ("budget_remaining", "budget_remaining_hint"):
            assert f'"{key}"' in code, f"translations.js MUST include {key} for remaining-budget UI"


class TestBudgetAlertMarkup:
    def test_index_has_remaining_and_banner(self):
        path = os.path.join(FRONTEND_DIR, "index.html")
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        for elem_id in (
            'id="budget-remaining-wrap"',
            'id="budget-remaining-display"',
            'id="budget-alert-banner"',
            'id="budget-alert-banner-text"',
            'id="budget-alert-banner-dismiss"',
        ):
            assert elem_id in html, f"Missing budget UI element: {elem_id}"


class TestLongDocumentPollTimeout:
    def test_api_js_reads_poll_timeout_from_backend_state(self):
        path = os.path.join(FRONTEND_DIR, "js", "api.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
        assert "function resolveGenerationPollTimeoutMs" in code
        assert "igniteDocumentPollTimeoutMs" in code
        assert "6 * 60 * 1000" not in code

    def test_remote_bridge_uses_document_poll_fallback(self):
        path = os.path.join(FRONTEND_DIR, "js", "remoteBridge.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
        assert "igniteDocumentPollTimeoutMs" in code
        assert "cfg.timeoutMs || 120000" not in code

    def test_app_js_stores_poll_timeouts_from_initial_state(self):
        path = os.path.join(FRONTEND_DIR, "js", "app.js")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
        assert "generation_poll_timeout_ms" in code
        assert "document_poll_timeout_ms" in code

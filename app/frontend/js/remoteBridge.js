/**
 * Optional browser-side HTTP bridge for Ignite Chat.
 * Desktop remote mode normally uses Python RemotePyWebViewApi so existing
 * window.pywebview.api.* calls keep working. This module is available when
 * the UI is served without pythonnet and window.__IGNITE_REMOTE_CONFIG__ is set.
 */
(function () {
    const cfg = window.__IGNITE_REMOTE_CONFIG__ || null;
    if (!cfg || !cfg.baseUrl) {
        return;
    }
    if (window.pywebview && window.pywebview.api && window.pywebview.api.__igniteRemote) {
        return;
    }

    const timeoutMs = Number(
        cfg.timeoutMs
        || window.igniteDocumentPollTimeoutMs
        || window.igniteGenerationPollTimeoutMs
        || 1800000
    );
    const headers = {
        "Content-Type": "application/json",
        Accept: "application/json",
    };
    if (cfg.apiKey) {
        headers["X-API-Key"] = cfg.apiKey;
    }

    async function invoke(method, args) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        try {
            const res = await fetch(`${cfg.baseUrl.replace(/\/$/, "")}/api/invoke`, {
                method: "POST",
                headers,
                body: JSON.stringify({ method, args: args || [], kwargs: {} }),
                signal: controller.signal,
            });
            const data = await res.json();
            if (!res.ok || data.status === "error") {
                return { status: "error", message: data.error || data.detail || res.statusText };
            }
            return data.result;
        } finally {
            clearTimeout(timer);
        }
    }

    const api = { __igniteRemote: true };
    [
        "get_initial_state",
        "get_history",
        "set_provider",
        "set_model",
        "set_participant_model",
        "clear_history",
        "create_group",
        "delete_group",
        "send_message_async",
        "cancel_generation",
        "get_generation_status",
        "determine_voice_category",
        "generate_cartesia_tts",
        "open_external_link",
        "open_file_path",
        "save_file_to_downloads",
        "export_message_to_file",
        "translate_message",
        "summarize_chat",
        "save_welcome_message",
        "set_theme_window_size",
        "get_accumulated_cost_stats",
    ].forEach((name) => {
        api[name] = function () {
            return invoke(name, Array.prototype.slice.call(arguments));
        };
    });

    window.pywebview = window.pywebview || {};
    window.pywebview.api = api;
})();

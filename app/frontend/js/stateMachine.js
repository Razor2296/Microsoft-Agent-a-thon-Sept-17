// app/frontend/js/stateMachine.js
// Skill 1.3 — Frontend Finite State Machine (FSM)
// Controls UI lifecycle transitions for the voice and chat pipeline.
//
// States:
//   IDLE       → Ready for input. Mic button enabled, send button enabled.
//   RECORDING  → Microphone is active. Transcription in progress.
//   THINKING   → Backend is processing the request. Spinner shown.
//   SPEAKING   → TTS audio is being played back to the user.
//   ERROR      → A recoverable error occurred. Error banner shown.

"use strict";

// ─── State Definitions ────────────────────────────────────────────────────────
const FSM_STATES = Object.freeze({
    IDLE:      "IDLE",
    RECORDING: "RECORDING",
    THINKING:  "THINKING",
    SPEAKING:  "SPEAKING",
    ERROR:     "ERROR",
});

// ─── Valid Transitions ────────────────────────────────────────────────────────
const FSM_TRANSITIONS = Object.freeze({
    [FSM_STATES.IDLE]:      [FSM_STATES.RECORDING, FSM_STATES.THINKING, FSM_STATES.ERROR],
    [FSM_STATES.RECORDING]: [FSM_STATES.IDLE, FSM_STATES.THINKING, FSM_STATES.ERROR],
    [FSM_STATES.THINKING]:  [FSM_STATES.IDLE, FSM_STATES.SPEAKING, FSM_STATES.ERROR],
    // Skill §6.2: SPEAKING must go through IDLE before RECORDING (no direct barge-in jump).
    [FSM_STATES.SPEAKING]:  [FSM_STATES.IDLE, FSM_STATES.THINKING, FSM_STATES.ERROR],
    [FSM_STATES.ERROR]:     [FSM_STATES.IDLE, FSM_STATES.RECORDING, FSM_STATES.THINKING],
});

// ─── StateMachine Class ───────────────────────────────────────────────────────
class StateMachine {
    /**
     * @param {string} providerId - The provider key this FSM tracks (e.g. "Gemini")
     */
    constructor(providerId) {
        this._providerId = providerId;
        this._state = FSM_STATES.IDLE;
        this._listeners = [];
        this._history = [];
        this._errorTimer = null;
    }

    /** Returns the current state string. */
    get state() {
        return this._state;
    }

    /** Returns true only when in the given state. */
    is(stateName) {
        return this._state === stateName;
    }

    /**
     * Transition to a new state.
     * Ignores redundant same-state transitions silently.
     *
     * @param {string} nextState - Target FSM_STATES value.
     * @param {object} [meta]    - Optional metadata attached to the event.
     */
    transition(nextState, meta = {}) {
        if (this._state === nextState) return; // idempotent

        const allowed = FSM_TRANSITIONS[this._state] || [];
        if (!allowed.includes(nextState)) {
            console.warn(
                `[FSM:${this._providerId}] Invalid transition: ${this._state} → ${nextState}. Allowed: [${allowed.join(", ")}]`
            );
            return;
        }

        const prevState = this._state;
        this._state = nextState;
        this._history.push({ from: prevState, to: nextState, ts: Date.now(), ...meta });

        console.debug(`[FSM:${this._providerId}] ${prevState} → ${nextState}`);
        this._emit(prevState, nextState, meta);
        this._applyUIEffects(nextState);

        if (this._errorTimer) {
            clearTimeout(this._errorTimer);
            this._errorTimer = null;
        }
        // Auto-recover from ERROR so mic/send are never permanently locked.
        if (nextState === FSM_STATES.ERROR) {
            this._errorTimer = setTimeout(() => {
                if (this.is(FSM_STATES.ERROR)) {
                    this.reset({ reason: "auto-recover-error" });
                }
            }, 2500);
        }
    }

    /**
     * Register a callback fired on every state change.
     * @param {function} fn - Called with (prevState, nextState, meta).
     * @returns {function} Unsubscribe function.
     */
    onTransition(fn) {
        this._listeners.push(fn);
        return () => {
            this._listeners = this._listeners.filter((l) => l !== fn);
        };
    }

    /** Reset to IDLE from any state (force reset). */
    reset(meta = {}) {
        if (this._errorTimer) {
            clearTimeout(this._errorTimer);
            this._errorTimer = null;
        }
        const prevState = this._state;
        this._state = FSM_STATES.IDLE;
        this._history.push({ from: prevState, to: FSM_STATES.IDLE, forced: true, ts: Date.now(), ...meta });
        console.debug(`[FSM:${this._providerId}] FORCED RESET → IDLE`);
        this._emit(prevState, FSM_STATES.IDLE, { ...meta, forced: true });
        this._applyUIEffects(FSM_STATES.IDLE);
    }

    /** Re-apply UI for the current state (e.g. after becoming the active chat). */
    refreshUI() {
        this._applyUIEffects(this._state);
    }

    /** Returns a snapshot of the transition history (last N entries). */
    historySnapshot(limit = 20) {
        return this._history.slice(-limit);
    }

    // ─── Private ──────────────────────────────────────────────────────────────

    _emit(prevState, nextState, meta) {
        for (const fn of this._listeners) {
            try {
                fn(prevState, nextState, meta);
            } catch (err) {
                console.error(`[FSM:${this._providerId}] Listener error:`, err);
            }
        }
    }

    /**
     * Applies visual CSS-class changes to the shared chat input controls.
     * UI uses single #send-btn / #mic-btn (not per-provider IDs).
     */
    _applyUIEffects(state) {
        // Only the active provider should mutate shared controls.
        if (typeof currentProvider !== "undefined" && currentProvider !== this._providerId) {
            return;
        }

        const sendBtn = document.getElementById("send-btn");
        const micBtn  = document.getElementById("mic-btn");
        const inputEl = document.getElementById("message-input");

        switch (state) {
            case FSM_STATES.IDLE:
                if (sendBtn) { sendBtn.disabled = false; sendBtn.removeAttribute('disabled'); sendBtn.style.pointerEvents = 'auto'; }
                if (micBtn)  { micBtn.disabled  = false; micBtn.removeAttribute('disabled'); micBtn.style.pointerEvents = 'auto'; }
                if (inputEl) {
                    inputEl.disabled = false;
                    inputEl.removeAttribute('disabled');
                    const lang = (typeof currentLang !== 'undefined') ? currentLang : 'es';
                    if (inputEl.placeholder === 'Esperando respuesta...' || inputEl.placeholder === 'Waiting for response...') {
                        inputEl.placeholder = lang === 'es' ? 'Escribe tu mensaje...' : 'Type your message...';
                    }
                }
                document.body.classList.remove("fsm-recording", "fsm-thinking", "fsm-speaking", "fsm-error");
                break;

            case FSM_STATES.RECORDING:
                if (sendBtn) { sendBtn.disabled = false; sendBtn.removeAttribute('disabled'); sendBtn.style.pointerEvents = 'auto'; }
                if (micBtn)  { micBtn.disabled  = false; micBtn.removeAttribute('disabled'); micBtn.style.pointerEvents = 'auto'; }
                if (inputEl) { inputEl.disabled = false; inputEl.removeAttribute('disabled'); }
                document.body.classList.add("fsm-recording");
                document.body.classList.remove("fsm-thinking", "fsm-speaking", "fsm-error");
                break;

            case FSM_STATES.THINKING:
                if (sendBtn) { sendBtn.disabled = false; sendBtn.removeAttribute('disabled'); sendBtn.style.pointerEvents = 'auto'; }
                if (micBtn)  { micBtn.disabled  = false; micBtn.removeAttribute('disabled'); micBtn.style.pointerEvents = 'auto'; }
                if (inputEl) {
                    inputEl.disabled = true;
                    const lang = (typeof currentLang !== 'undefined') ? currentLang : 'es';
                    inputEl.placeholder = lang === 'es' ? 'Esperando respuesta...' : 'Waiting for response...';
                }
                document.body.classList.add("fsm-thinking");
                document.body.classList.remove("fsm-recording", "fsm-speaking", "fsm-error");
                break;

            case FSM_STATES.SPEAKING:
                if (sendBtn) { sendBtn.disabled = false; sendBtn.removeAttribute('disabled'); sendBtn.style.pointerEvents = 'auto'; }
                if (micBtn)  { micBtn.disabled  = false; micBtn.removeAttribute('disabled'); micBtn.style.pointerEvents = 'auto'; }
                if (inputEl) { inputEl.disabled = false; inputEl.removeAttribute('disabled'); }
                document.body.classList.add("fsm-speaking");
                document.body.classList.remove("fsm-recording", "fsm-thinking", "fsm-error");
                break;

            case FSM_STATES.ERROR:
                if (sendBtn) sendBtn.disabled = false;
                if (micBtn)  micBtn.disabled  = false;
                if (inputEl) inputEl.disabled = false;
                document.body.classList.add("fsm-error");
                document.body.classList.remove("fsm-recording", "fsm-thinking", "fsm-speaking");
                break;
        }
    }
}

// ─── Global FSM Registry ──────────────────────────────────────────────────────
window.ProviderFSM = window.ProviderFSM || {};
window.FSM_STATES  = FSM_STATES;

/**
 * Returns the FSM for a given provider, creating it if it does not yet exist.
 * @param {string} providerId
 * @returns {StateMachine}
 */
window.getProviderFSM = function (providerId) {
    if (!window.ProviderFSM[providerId]) {
        window.ProviderFSM[providerId] = new StateMachine(providerId);
    }
    return window.ProviderFSM[providerId];
};

/**
 * Convenience: transition ALL registered FSMs to IDLE.
 * Prefer syncSharedControlsForProvider on chat switch — resetting every FSM
 * while a background group is still generating freezes the shared input.
 */
window.resetAllFSMs = function () {
    for (const fsm of Object.values(window.ProviderFSM)) {
        if (!fsm.is(FSM_STATES.IDLE)) fsm.reset({ reason: "resetAllFSMs" });
    }
};

/**
 * Sync shared mic/send/input controls to the provider now on screen.
 * Background chats keep their FSM/poll state untouched.
 */
window.syncSharedControlsForProvider = function (providerId) {
    if (!providerId || typeof window.getProviderFSM !== "function") return;
    const fsm = window.getProviderFSM(providerId);
    const busy =
        typeof isProcessing !== "undefined" &&
        !!isProcessing[providerId];

    if (busy) {
        if (fsm.is(FSM_STATES.IDLE) || fsm.is(FSM_STATES.ERROR)) {
            fsm.transition(FSM_STATES.THINKING, { reason: "syncSharedControls-busy" });
        } else {
            fsm.refreshUI();
        }
        return;
    }

    if (!fsm.is(FSM_STATES.IDLE)) {
        // Do not hard-reset a chat that is recording/speaking on this provider;
        // only clear thinking leftovers from a finished background race.
        if (fsm.is(FSM_STATES.THINKING) || fsm.is(FSM_STATES.ERROR)) {
            fsm.reset({ reason: "syncSharedControls-idle" });
        } else {
            fsm.refreshUI();
        }
    } else {
        fsm.refreshUI();
    }
};

// Initialize FSMs for all base providers on script load
(function initBaseProviderFSMs() {
    const baseProviderIds = ["Gemini", "DeepSeek", "OpenAI", "Anthropic", "Perplexity", "Grok"];
    for (const id of baseProviderIds) {
        window.getProviderFSM(id);
    }
    console.debug("[FSM] Base provider FSMs initialized:", Object.keys(window.ProviderFSM));
})();

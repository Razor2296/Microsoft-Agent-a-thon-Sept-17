// app/frontend/state.js
// Global variables and helpers to manage theme, language, background, and input state

let pendingFiles = [];
let totalTokens = 0;
window.providerTokens = window.providerTokens || {
    Gemini: 0, DeepSeek: 0, OpenAI: 0, Anthropic: 0, Perplexity: 0, Grok: 0
};
let appAvatars = {};
window.customGroups = {};
let currentProvider = "Gemini";
let currentLang = "en";
let userName = "User";
let bgImageDark = null;
let bgImageLight = null;

// Dynamic provider lists and state tracking objects
let baseProviders = ["Gemini", "DeepSeek", "OpenAI", "Anthropic", "Perplexity", "Grok"];
let blockedProviders = {};
let isProcessing = {};
let pollIntervals = {};
let stepTimers = {};
let activeSteps = {};
let stepIndices = {};
let unreadCounts = {};

// Helper to dynamically register provider tracking keys if they are not already initialized
window.registerProviderState = function(p) {
    if (!p) return;
    if (blockedProviders[p] === undefined) blockedProviders[p] = false;
    if (isProcessing[p] === undefined) isProcessing[p] = false;
    if (pollIntervals[p] === undefined) pollIntervals[p] = null;
    if (stepTimers[p] === undefined) stepTimers[p] = null;
    if (activeSteps[p] === undefined) activeSteps[p] = [];
    if (stepIndices[p] === undefined) stepIndices[p] = 0;
    if (unreadCounts[p] === undefined) unreadCounts[p] = 0;
    if (window.providerTokens[p] === undefined) window.providerTokens[p] = 0;
    
    // Groups must have an FSM too; otherwise switching onto them can leave
    // shared controls stuck disabled from a previous THINKING chat.
    if (typeof window.getProviderFSM === "function") {
        window.getProviderFSM(p);
    }
};

// Function to update background image
function updateBackgroundImage() {
    const isLightMode = document.body.classList.contains('light-mode');
    const wallChoice = localStorage.getItem('custom-wallpaper') || 'classic';
    if (wallChoice === 'classic') {
        const bgImage = isLightMode ? bgImageLight : bgImageDark;
        if (bgImage) {
            document.body.style.backgroundImage = `url('${bgImage}')`;
            document.body.style.backgroundColor = '';
        } else {
            document.body.style.backgroundImage = 'none';
        }
    } else {
        document.body.style.backgroundImage = 'none';
        document.body.style.backgroundColor = wallChoice;
    }
}

// Function to update UI language
function updateLanguageUI() {
    const t = translations[currentLang];
    document.getElementById('message-input').placeholder = t.ask;
    document.getElementById('header-subtitle').textContent = t.active;

    const tokensLabel = document.querySelector('.tokens-label');
    if (tokensLabel) tokensLabel.innerHTML = `📊 ${t.tokens}`;

    const costLabel = document.querySelector('.cost-label');
    if (costLabel) costLabel.innerHTML = `💵 ${t.total_cost}`;

    const budgetLabel = document.querySelector('.budget-remaining-label');
    if (budgetLabel) budgetLabel.innerHTML = `💰 ${t.budget_remaining}`;

    const budgetHint = document.getElementById('budget-remaining-hint');
    if (budgetHint) budgetHint.textContent = t.budget_remaining_hint;

    const clearBtn = document.getElementById('clear-chat-btn');
    if (clearBtn) clearBtn.innerHTML = `<span class="icon">🗑️</span> ${t.clear}`;

    const toggleText = document.querySelector('.toggle-text');
    if (toggleText) toggleText.textContent = t.dark;

    const chooseLabel = document.querySelector('label[for="model-select"]');
    if (chooseLabel) chooseLabel.innerHTML = `${t.choose} <span class="help-icon">?</span>`;

    const providerLabel = document.getElementById('provider-label');
    if (providerLabel) providerLabel.textContent = t.provider;

    const appearanceLabel = document.querySelector('.appearance-label');
    if (appearanceLabel) appearanceLabel.innerHTML = `🎨 ${t.appearance}`;

    const dateBadge = document.querySelector('.chat-date-badge');
    if (dateBadge && (dateBadge.textContent === 'TODAY' || dateBadge.textContent === 'HOY')) {
        dateBadge.textContent = t.today;
    }

    // Translate new chats panel elements
    const chatsHeaderTitle = document.querySelector('#chats-header h2');
    if (chatsHeaderTitle) chatsHeaderTitle.textContent = t.chats_title;

    const chatsSearchInput = document.getElementById('chats-search-input');
    if (chatsSearchInput) chatsSearchInput.placeholder = t.search_placeholder;

    const filterAllBtn = document.getElementById('filter-all');
    if (filterAllBtn) filterAllBtn.textContent = t.all_filter;

    const filterUnreadBtn = document.getElementById('filter-unread');
    if (filterUnreadBtn) filterUnreadBtn.textContent = t.unread_filter;

    const msgSearchInput = document.getElementById('message-search-input');
    if (msgSearchInput) msgSearchInput.placeholder = t.search_in_chat || "Search in this chat...";

    const emojiSearchInput = document.getElementById('emoji-search');
    if (emojiSearchInput) emojiSearchInput.placeholder = t.search_emoji_placeholder || "Search emoji...";

    // Update uninitiated default last message text
    const groupProviders = Object.keys(window.customGroups || {});
    const providers = [...baseProviders, ...groupProviders];
    providers.forEach(p => {
        const msgEl = document.getElementById(`chat-item-last-msg-${p}`);
        if (msgEl) {
            const txt = msgEl.textContent;
            if (txt === "Click to start chatting" || txt === "Haz clic para chatear") {
                msgEl.textContent = currentLang === 'es' ? 'Haz clic para chatear' : 'Click to start chatting';
            }
        }
    });

    const clearChatText = document.getElementById('menu-clear-chat-text');
    if (clearChatText) clearChatText.textContent = t.clear_chat_lbl;

    const exitGroupText = document.getElementById('menu-exit-group-text');
    if (exitGroupText) exitGroupText.textContent = t.exit_group_lbl;

    updateTokenDisplay();
}

// Function to update token display & cost stats for the current or specified provider
function updateTokenDisplay(provider) {
    const targetProv = provider || currentProvider;
    const provTokens = (window.providerTokens && typeof window.providerTokens[targetProv] === 'number')
        ? window.providerTokens[targetProv]
        : 0;
    totalTokens = provTokens;

    const totalTokensDisplay = document.getElementById('total-tokens-display');
    if (totalTokensDisplay) {
        totalTokensDisplay.textContent = provTokens.toLocaleString();
    }
    const poweredByText = document.getElementById('powered-by-text');
    if (poweredByText) {
        const t = translations[currentLang] || translations['en'];
        poweredByText.textContent = t.powered_by.replace('{provider}', targetProv);
    }
    
    // Fetch the current provider's session cost (not lifetime grand total)
    // and the lifetime remaining-budget alert.
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_accumulated_cost_stats === 'function') {
        window.pywebview.api.get_accumulated_cost_stats(currentLang).then(res => {
            if (res && res.status === 'success') {
                const totalCostEl = document.getElementById('total-cost-display');
                if (totalCostEl) {
                    const rows = res.providers || [];
                    const row = rows.find(function (item) { return item.provider === targetProv; });
                    const cost = (row && typeof row.cost_usd === 'number') ? row.cost_usd : 0;
                    totalCostEl.textContent = `$${Number(cost).toFixed(4)} USD`;
                }
                applyBudgetFromStats(res);
            }
        }).catch(err => console.warn('Failed to fetch cost stats:', err));
    }
}

function bindBudgetAlertBanner() {
    const btn = document.getElementById('budget-alert-banner-dismiss');
    if (!btn || btn.dataset.bound === '1') return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', function () {
        window._budgetBannerDismissedLevel = window._lastBudgetAlertLevel || 'warn';
        const banner = document.getElementById('budget-alert-banner');
        if (banner) banner.classList.add('hidden');
    });
}

function applyBudgetFromStats(res) {
    bindBudgetAlertBanner();
    const wrap = document.getElementById('budget-remaining-wrap');
    const remainingEl = document.getElementById('budget-remaining-display');
    const banner = document.getElementById('budget-alert-banner');
    const bannerText = document.getElementById('budget-alert-banner-text');
    if (!res || res.status !== 'success' || !res.budget_enabled) {
        if (wrap) wrap.style.display = 'none';
        if (banner) banner.classList.add('hidden');
        return;
    }
    if (wrap) wrap.style.display = 'block';
    const remaining = typeof res.remaining_usd === 'number' ? res.remaining_usd : 0;
    const level = res.alert_level || 'ok';
    window._lastBudgetAlertLevel = level;
    if (remainingEl) {
        remainingEl.textContent = `$${Number(remaining).toFixed(4)} USD`;
        remainingEl.classList.remove(
            'budget-remaining-ok',
            'budget-remaining-warn',
            'budget-remaining-critical',
            'budget-remaining-exhausted'
        );
        remainingEl.classList.add('budget-remaining-' + level);
    }
    if (banner && bannerText) {
        if (level === 'ok' || level === 'disabled' || !res.alert_message) {
            banner.classList.add('hidden');
        } else {
            bannerText.textContent = res.alert_message;
            banner.className = 'budget-alert-banner budget-alert-' + level;
            if (window._budgetBannerDismissedLevel === level) {
                banner.classList.add('hidden');
            } else {
                banner.classList.remove('hidden');
            }
        }
    }
    if (res.budget_notify && res.alert_message && typeof showTemporaryToast === 'function') {
        const toastMs = Number(res.toast_ms);
        showTemporaryToast(res.alert_message, Number.isFinite(toastMs) && toastMs > 0 ? toastMs : undefined, { multiline: true });
    }
}

// Function to update visibility of send/microphone buttons
function updateInputButtonsState() {
    const msgInput = document.getElementById('message-input');
    if (!msgInput) return;
    const sendBtn = document.getElementById('send-btn');
    const micBtn = document.getElementById('mic-btn');
    if (!sendBtn) return;

    const hasContent = msgInput.value.trim() !== '' || pendingFiles.length > 0;
    sendBtn.classList.toggle('active', hasContent);

    const busy = typeof isProcessing !== 'undefined' && !!isProcessing[currentProvider];
    const blocked =
        typeof blockedProviders !== 'undefined' && !!blockedProviders[currentProvider];
    let fsmBlocksSend = false;
    if (window.getProviderFSM && window.FSM_STATES) {
        const fsm = window.getProviderFSM(currentProvider);
        if (
            fsm &&
            (fsm.is(window.FSM_STATES.THINKING) || fsm.is(window.FSM_STATES.RECORDING))
        ) {
            fsmBlocksSend = true;
        }
    }

    // Heal THINKING leftovers when nothing is actually processing
    if (
        !busy &&
        fsmBlocksSend &&
        window.getProviderFSM &&
        window.FSM_STATES
    ) {
        const fsm = window.getProviderFSM(currentProvider);
        if (fsm && fsm.is(window.FSM_STATES.THINKING)) {
            fsm.reset({ reason: 'heal-thinking-without-processing' });
            fsmBlocksSend = false;
        }
    }

    // NEVER set disabled = true on DOM elements to avoid Chromium event suppression!
    sendBtn.disabled = false;
    sendBtn.removeAttribute('disabled');
    sendBtn.style.pointerEvents = 'auto';
    sendBtn.style.opacity = hasContent ? '1' : '0.5';

    if (msgInput) {
        const defaultPlaceholder = currentLang === 'es' ? 'Escribe tu mensaje...' : 'Type your message...';
        const thinkingPlaceholder = currentLang === 'es' ? 'Esperando respuesta...' : 'Waiting for response...';
        if (busy || fsmBlocksSend) {
            msgInput.disabled = true;
            msgInput.placeholder = thinkingPlaceholder;
        } else if (!blocked) {
            msgInput.disabled = false;
            msgInput.removeAttribute('disabled');
            msgInput.placeholder = defaultPlaceholder;
        }
    }

    // mic-btn is always enabled and visible for user voice interruption
    if (micBtn) {
        micBtn.disabled = false;
        micBtn.removeAttribute('disabled');
        micBtn.style.pointerEvents = 'auto';
        micBtn.style.opacity = '1';
        micBtn.style.display = 'flex';
    }
}

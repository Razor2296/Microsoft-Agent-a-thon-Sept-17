// Optional multi-panel AI grid for group chats.
// Default UX remains the WhatsApp single-thread #chat-container.

window.aiGridEnabled = false;

// Function to check if the current provider is a group
function isCurrentGroupChat() {
    return !!(currentProvider && String(currentProvider).startsWith('group_'));
}

// Function to get the group participants for the grid
function getGroupParticipantsForGrid() {
    if (!isCurrentGroupChat()) return [];
    const group = window.customGroups && window.customGroups[currentProvider];
    if (group && Array.isArray(group.participants)) return group.participants.slice();
    return [];
}

// Function to sync the AI grid toggle visibility
function syncAiGridToggleVisibility() {
    const btn = document.getElementById('ai-grid-toggle');
    if (!btn) return;
    const show = isCurrentGroupChat();
    btn.style.display = show ? 'inline-flex' : 'none';
    if (!show && window.aiGridEnabled) {
        setAiGridEnabled(false);
    } else {
        btn.classList.toggle('active', !!window.aiGridEnabled);
        btn.title = window.aiGridEnabled
            ? (currentLang === 'es' ? 'Vista chat' : 'Chat view')
            : (currentLang === 'es' ? 'Vista panel' : 'Panel view');
    }
}

// Function to set the AI grid enabled state
function setAiGridEnabled(enabled) {
    window.aiGridEnabled = !!enabled && isCurrentGroupChat();
    document.body.classList.toggle('ai-grid-mode', window.aiGridEnabled);
    const btn = document.getElementById('ai-grid-toggle');
    if (btn) btn.classList.toggle('active', window.aiGridEnabled);
    const chat = document.getElementById('chat-container');
    const grid = document.getElementById('ai-grid');
    if (window.aiGridEnabled) {
        if (chat) chat.classList.add('ai-grid-hidden');
        if (grid) {
            grid.classList.remove('hidden');
            renderAiGridShell(getGroupParticipantsForGrid());
        }
    } else {
        if (chat) chat.classList.remove('ai-grid-hidden');
        if (grid) grid.classList.add('hidden');
    }
    syncAiGridToggleVisibility();
}

// Function to render the AI grid shell
function renderAiGridShell(participants) {
    const grid = document.getElementById('ai-grid');
    if (!grid) return;
    const parts = participants && participants.length
        ? participants
        : getGroupParticipantsForGrid();
    if (!parts.length) {
        grid.innerHTML = `<div class="ai-grid-empty">${currentLang === 'es' ? 'Sin participantes' : 'No participants'}</div>`;
        return;
    }
    grid.innerHTML = parts.map((p) => `
        <section class="ai-grid-panel" data-provider="${p}">
            <header class="ai-grid-panel-header">
                <div class="ai-grid-panel-title">${p}</div>
                <div class="ai-grid-panel-badge" data-role="badge">Idle</div>
            </header>
            <div class="ai-grid-panel-body" data-role="body">
                <div class="ai-grid-placeholder">${currentLang === 'es' ? 'Esperando respuesta...' : 'Waiting for reply...'}</div>
            </div>
            <footer class="ai-grid-panel-footer" data-role="tokens"></footer>
        </section>
    `).join('');
}

// Function to update the AI grid from the status
function updateAiGridFromStatus(status, sentProvider) {
    if (!window.aiGridEnabled) return;
    if (!sentProvider || sentProvider !== currentProvider || !isCurrentGroupChat()) return;
    const grid = document.getElementById('ai-grid');
    if (!grid) return;

    const participants = getGroupParticipantsForGrid();
    if (!grid.querySelector('.ai-grid-panel') && participants.length) {
        renderAiGridShell(participants);
    }

    const respondentRaw = status && status.current_respondent ? String(status.current_respondent) : '';
    const generating = new Set(
        respondentRaw.split(',').map((s) => s.trim()).filter(Boolean)
    );
    const steps = (status && status.steps) || [];

    grid.querySelectorAll('.ai-grid-panel').forEach((panel) => {
        const provider = panel.dataset.provider;
        const badge = panel.querySelector('[data-role="badge"]');
        if (!badge) return;
        if (generating.has(provider)) {
            const step = steps.find((s) => String(s).includes(provider)) || 'Thinking...';
            const lower = String(step).toLowerCase();
            badge.textContent = lower.includes('search')
                ? 'Searching'
                : (lower.includes('generat') || lower.includes('typing') ? 'Thinking' : 'Streaming');
            badge.dataset.state = 'busy';
        } else if (status && status.status === 'done') {
            badge.textContent = 'Done';
            badge.dataset.state = 'done';
        } else if (status && (status.status === 'processing' || status.status === 'queued')) {
            badge.textContent = 'Queued';
            badge.dataset.state = 'queued';
        } else {
            badge.textContent = 'Idle';
            badge.dataset.state = 'idle';
        }
    });
}

// Function to update the AI grid reply
function updateAiGridReply(provider, replyText, tokenInfo) {
    if (!window.aiGridEnabled || !isCurrentGroupChat()) return;
    const panel = document.querySelector(`#ai-grid .ai-grid-panel[data-provider="${provider}"]`);
    if (!panel) return;
    const body = panel.querySelector('[data-role="body"]');
    const tokens = panel.querySelector('[data-role="tokens"]');
    const badge = panel.querySelector('[data-role="badge"]');
    if (body) {
        let html = replyText || '';
        try {
            if (window.marked && window.marked.parse) html = window.marked.parse(replyText || '');
        } catch (e) {
            html = (replyText || '').replace(/\n/g, '<br>');
        }
        body.innerHTML = html;
        if (typeof enhanceCodeBlocks === 'function') {
            try { enhanceCodeBlocks(body); } catch (e) { }
        }
    }
    if (badge) {
        badge.textContent = 'Done';
        badge.dataset.state = 'done';
    }
    if (tokens && tokenInfo) {
        const total = (tokenInfo.candidates_tokens || 0) + (tokenInfo.thinking_tokens || 0) + (tokenInfo.prompt_tokens || 0);
        tokens.textContent = total ? `${total} tokens` : '';
    }
}

// Function to initialize the AI grid controls
function initAiGridControls() {
    const btn = document.getElementById('ai-grid-toggle');
    if (!btn || btn.dataset.bound === '1') return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', (e) => {
        e.preventDefault();
        if (!isCurrentGroupChat()) return;
        setAiGridEnabled(!window.aiGridEnabled);
    });
    syncAiGridToggleVisibility();
}

document.addEventListener('DOMContentLoaded', initAiGridControls);
window.syncAiGridToggleVisibility = syncAiGridToggleVisibility;
window.setAiGridEnabled = setAiGridEnabled;
window.updateAiGridFromStatus = updateAiGridFromStatus;
window.updateAiGridReply = updateAiGridReply;
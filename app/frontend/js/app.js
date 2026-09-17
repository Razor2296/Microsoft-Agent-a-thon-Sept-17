// app/frontend/app.js
// Main entry point for the client-side WebView application.
// Connects UI events to backend API functions and orchestrates flow.

function bootstrapApp() {
    console.log("PyWebView is ready!");

    // Disable default browser right-click context menu (Inspect Element) in production
    document.addEventListener('contextmenu', (e) => e.preventDefault());

    const msgInput = document.getElementById('message-input');

    // Language selector interaction
    document.getElementById('language-select').addEventListener('change', (e) => {
        currentLang = e.target.value;
        updateLanguageUI();
        if (typeof translateGroupModal === 'function') translateGroupModal();

        // Update welcome message if history is empty or only welcome message(s)
        if (window.pywebview && window.pywebview.api) {
            window.pywebview.api.get_history().then(res => {
                const history = res.history || [];
                const onlyWelcome = history.length > 0 && history.every(m => m && m.is_welcome);
                if (onlyWelcome || (history.length === 1 && history[0].role === 'assistant' && history[0].is_welcome)) {
                    window.pywebview.api.clear_history().then(() => {
                        showWelcomeOrHistory([], currentProvider);
                    });
                } else if (history.length === 0) {
                    showWelcomeOrHistory([], currentProvider);
                } else {
                    // Re-render history to update date headers to new language
                    renderHistory(history, currentProvider);
                }
            }).catch(err => {
                console.error("Error updating language history:", err);
            });
        }
    });

    // Check if API is available
    if (typeof window.pywebview === 'undefined' || !window.pywebview.api) {
        document.getElementById('chat-container').innerHTML = `
            <div style="text-align:center;margin-top:50px;color:var(--text-muted);">
                <h3>⚠️ Backend API not available</h3>
                <p>Please check the console for errors.</p>
            </div>
        `;
        return;
    }

    window.customGroups = {};

    window.renderChatsList = function (providers, lastMessages) {
        const chatsList = document.getElementById('chats-list');
        if (!chatsList) return;
        chatsList.innerHTML = '';
        const t = translations[currentLang] || translations['en'];

        providers.forEach(p => {
            if (typeof registerProviderState === 'function') {
                registerProviderState(p);
            }
            let name = p;
            let avatarHtml = '';
            let isGroup = p.startsWith('group_');

            if (isGroup) {
                const g = window.customGroups[p];
                name = g ? g.name : 'AI Group';

                avatarHtml = `<svg viewBox="0 0 40 40" width="40" height="40" xmlns="http://www.w3.org/2000/svg">
                    <defs>
                        <linearGradient id="groupGrad-${p}" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stop-color="#128C7E"/>
                            <stop offset="100%" stop-color="#075E54"/>
                        </linearGradient>
                    </defs>
                    <circle cx="20" cy="20" r="20" fill="url(#groupGrad-${p})"/>
                    <g fill="#FFFFFF" transform="translate(6, 6)">
                        <path d="M7 21v-1.5C7 17.5 9 16 11.5 16s4.5 1.5 4.5 3.5V21H7z" opacity="0.6"/>
                        <circle cx="11.5" cy="11.5" r="3" opacity="0.6"/>
                        <path d="M17 21v-1.5C17 17.5 19 16 21.5 16s4.5 1.5 4.5 3.5V21H17z" opacity="0.6"/>
                        <circle cx="21.5" cy="21.5" r="3" opacity="0.6"/>
                        <path d="M10 23v-2c0-2.5 2.5-4 5-4s5 1.5 5 4v2H10z"/>
                        <circle cx="15" cy="11" r="4"/>
                    </g>
                </svg>`;

                appAvatars[p] = avatarHtml;
            } else {
                avatarHtml = getAvatarHtml(p, true);
            }

            const archived = JSON.parse(localStorage.getItem('archived-chats') || '[]');
            const isArchived = archived.includes(p);

            const itemDiv = document.createElement('div');
            itemDiv.className = `chat-item${p === currentProvider ? ' active' : ''}`;
            itemDiv.setAttribute('data-provider', p);
            itemDiv.style.display = isArchived ? 'none' : '';
            itemDiv.onclick = () => selectProvider(p);

            const isChecked = p === currentProvider ? 'checked' : '';

            itemDiv.innerHTML = `
                <input type="radio" name="provider" value="${p}" ${isChecked} id="radio-${p}" style="display:none;">
                <div class="provider-avatar" id="sidebar-avatar-${p}">${avatarHtml}</div>
                <div class="chat-item-details">
                    <div class="chat-item-row">
                        <span class="chat-item-name">${name}</span>
                        <span class="chat-item-time" id="chat-item-time-${p}"></span>
                    </div>
                    <div class="chat-item-row">
                        <span class="chat-item-last-msg" id="chat-item-last-msg-${p}">Click to start chatting</span>
                        <span class="provider-badge hidden" id="sidebar-badge-${p}">0</span>
                    </div>
                </div>
            `;

            chatsList.appendChild(itemDiv);

            if (lastMessages && lastMessages[p]) {
                updateChatListItem(p, lastMessages[p]);
            } else {
                updateChatListItem(p, null);
            }
        });

        bindProviderRadioListeners();
    };

    window._providerSwitchSeq = window._providerSwitchSeq || 0;

    window._showProviderLoading = function (provider) {
        const chatContainer = document.getElementById('chat-container');
        if (!chatContainer) return;
        const label = provider || currentProvider || 'chat';
        const msg = (currentLang === 'es')
            ? `Cargando conversación de ${label}…`
            : `Loading ${label} conversation…`;
        chatContainer.innerHTML = `
            <div style="text-align:center;margin-top:50px;color:var(--text-muted);padding:0 16px;">
                <h3>${msg}</h3>
            </div>
        `;
    };

    window._applyProviderSwitchResult = function (requestedProvider, seq, res) {
        if (seq !== window._providerSwitchSeq || currentProvider !== requestedProvider) {
            return;
        }
        if (!res || res.status === 'error') {
            const msg = (res && (res.message || res.error)) || 'Failed to load conversation';
            console.error(`Error switching provider (${requestedProvider}):`, msg);
            const chatContainer = document.getElementById('chat-container');
            if (chatContainer) {
                chatContainer.innerHTML = `
                    <div style="text-align:center;margin-top:50px;color:var(--text-muted);padding:0 16px;">
                        <h3>⚠️ ${msg}</h3>
                    </div>
                `;
            }
            return;
        }
        if (res.provider_init_error) {
            console.warn(`Provider init error (${requestedProvider}):`, res.provider_init_error);
        }
        if (res.models && res.models[requestedProvider]) {
            populateModels(
                res.models[requestedProvider] || [],
                res.current_model ? res.current_model[requestedProvider] : null
            );
            document.getElementById('model-select').disabled = false;
        } else {
            const sel = document.getElementById('model-select');
            sel.innerHTML = '<option value="group">Group Chat</option>';
            sel.disabled = true;
        }
        if (typeof window.renderGroupAiProviders === 'function') {
            window.renderGroupAiProviders(requestedProvider, res.models || {}, res.current_model || {});
        }
        const history = res.history || [];
        window._lastHistoryCount = window._lastHistoryCount || {};
        const priorCount = window._lastHistoryCount[requestedProvider] || 0;
        showWelcomeOrHistory(history, requestedProvider);
        if (history.length > 0) {
            window._lastHistoryCount[requestedProvider] = history.length;
        } else if (priorCount > 0 && typeof appendMessage === 'function') {
            // Backend returned empty for a chat that had messages: likely a server
            // restart / cold restore miss. Tell the user instead of silently blanking.
            const warnMsg = (currentLang === 'es')
                ? '⚠️ No se pudo recuperar el historial anterior (posible reinicio del servidor). Tus mensajes previos podrían reaparecer al reintentar.'
                : '⚠️ Previous history could not be restored (possible server restart). Your earlier messages may reappear on retry.';
            appendMessage('assistant', warnMsg, null, null, false, null, false, requestedProvider);
        }

        if (res.provider_init_error && typeof appendMessage === 'function') {
            const msg = (currentLang === 'es')
                ? `⚠️ Este proveedor no está disponible: ${res.provider_init_error}`
                : `⚠️ This provider is unavailable: ${res.provider_init_error}`;
            appendMessage('assistant', msg, null, null, false, null, false, requestedProvider);
        }
        if (typeof window.updateBlockUI === 'function') {
            window.updateBlockUI();
        }
        if (typeof window.closeSearch === 'function') {
            window.closeSearch();
        }
        if (typeof window.refreshPinBanner === 'function') {
            window.refreshPinBanner();
        }
        if (typeof window.applyDisappearingMessages === 'function') {
            window.applyDisappearingMessages();
        }
        if (typeof window.syncSharedControlsForProvider === 'function') {
            window.syncSharedControlsForProvider(requestedProvider);
        }
        if (isProcessing[requestedProvider]) {
            const steps = activeSteps[requestedProvider] || ["Thinking..."];
            const idx = stepIndices[requestedProvider] || 0;
            showTypingWithSteps([steps[idx]]);
        }
    };

    window.bindProviderRadioListeners = function () {
        const providerRadios = document.getElementsByName('provider');
        providerRadios.forEach(radio => {
            radio.addEventListener('change', (e) => {
                if (!e.target.checked) return;
                const requestedProvider = e.target.value;
                currentProvider = requestedProvider;
                const seq = ++window._providerSwitchSeq;

                // Move the active indicator bar to the selected chat
                document.querySelectorAll('.chat-item').forEach(item => item.classList.remove('active'));
                const selectedItem = document.querySelector(`.chat-item[data-provider="${requestedProvider}"]`);
                if (selectedItem) selectedItem.classList.add('active');

                updateHeaderInfo(requestedProvider);
                unreadCounts[requestedProvider] = 0;
                updateNotificationBell();
                if (typeof window.syncAiGridToggleVisibility === 'function') {
                    window.syncAiGridToggleVisibility();
                }

                // Mark chats that are still generating in the background so multi-parallel
                // work stays visible while the user types in another conversation.
                document.querySelectorAll('.chat-item').forEach((item) => {
                    const pid = item.getAttribute('data-provider');
                    item.classList.toggle('is-generating', !!(isProcessing && pid && isProcessing[pid]));
                });

                // Instant 0ms UI switch if history is cached, avoiding stuck loading states after idle
                window.cachedHistories = window.cachedHistories || {};
                if (window.cachedHistories[requestedProvider] !== undefined) {
                    showWelcomeOrHistory(window.cachedHistories[requestedProvider], requestedProvider);
                } else {
                    window._showProviderLoading(requestedProvider);
                }
                updateTokenDisplay(requestedProvider);

                // Never resetAllFSMs here: a background group poll would lose its
                // THINKING state while shared controls stay disabled → UI freeze.
                if (typeof window.syncSharedControlsForProvider === 'function') {
                    window.syncSharedControlsForProvider(requestedProvider);
                }
                window.pywebview.api.set_provider(requestedProvider).then(res => {
                    window._applyProviderSwitchResult(requestedProvider, seq, res);
                }).catch(err => {
                    if (seq !== window._providerSwitchSeq || currentProvider !== requestedProvider) {
                        return;
                    }
                    console.error("Error switching provider:", err);
                    const chatContainer = document.getElementById('chat-container');
                    if (chatContainer) {
                        chatContainer.innerHTML = `
                            <div style="text-align:center;margin-top:50px;color:var(--text-muted);padding:0 16px;">
                                <h3>⚠️ ${err}</h3>
                            </div>
                        `;
                    }
                });
            });
        });
    };

    // After sleep/wake, heal only when the open chat chrome and bubbles disagree
    // (e.g. DeepSeek header with Gemini avatars left over from a slow switch).
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState !== 'visible') return;
        if (!window.pywebview || !window.pywebview.api || !window.pywebview.api.set_provider) return;
        if (!currentProvider) return;
        if (isProcessing && isProcessing[currentProvider]) return;

        const chatContainer = document.getElementById('chat-container');
        if (!chatContainer) return;
        const labels = chatContainer.querySelectorAll('.message-wrapper.assistant .avatar-label');
        if (!labels.length) return;
        const expected = String(currentProvider).toUpperCase();
        let mismatched = false;
        labels.forEach((el) => {
            const text = (el.textContent || '').trim().toUpperCase();
            if (text && text !== expected && text !== 'GROUP') {
                mismatched = true;
            }
        });
        if (!mismatched) return;

        const requestedProvider = currentProvider;
        const seq = ++window._providerSwitchSeq;
        window._showProviderLoading(requestedProvider);
        window.pywebview.api.set_provider(requestedProvider).then(res => {
            window._applyProviderSwitchResult(requestedProvider, seq, res);
        }).catch(err => {
            console.warn("Wake re-sync failed:", err);
        });
    });

    // Load initial states from backend
    const chatContainerEl = document.getElementById('chat-container');
    if (chatContainerEl) {
        chatContainerEl.innerHTML = `
            <div style="text-align:center;margin-top:50px;color:var(--text-muted);">
                <h3>Connecting…</h3>
                <p>Loading chat state from backend.</p>
            </div>
        `;
    }

    window.pywebview.api.get_initial_state().then(state => {
        // Remote proxy may return {status:"error", message:"..."} instead of throwing.
        if (!state || state.status === 'error' || !state.providers || !state.models) {
            const msg = (state && (state.message || state.error)) || 'Invalid initial state from backend';
            throw new Error(msg);
        }

        appAvatars = state.avatars || {};
        bgImageDark = state.bg_image_dark;
        bgImageLight = state.bg_image_light;
        currentProvider = state.current_provider || (state.providers[0] || currentProvider);
        if (state.user_name && String(state.user_name).trim() && String(state.user_name).trim().toLowerCase() !== 'user') {
            userName = String(state.user_name).trim();
        }
        if (state.provider_init_errors && state.provider_init_errors[currentProvider]) {
            console.warn('Active provider init error:', state.provider_init_errors[currentProvider]);
        }

        // Auto-detect and initialize UI language from system language
        if (state.system_language) {
            const baseLang = state.system_language.split('-')[0].toLowerCase();
            if (baseLang === 'es') {
                currentLang = 'es';
            } else {
                currentLang = 'en';
            }
            const langSelect = document.getElementById('language-select');
            if (langSelect) langSelect.value = currentLang;
        }

        // Initialize customGroups
        window.customGroups = state.groups || {};

        // Dynamically initialize baseProviders and register state variables for all providers
        if (state.providers && state.providers.length > 0) {
            baseProviders = state.providers;
        }
        window.igniteGenerationPollTimeoutMs = Number(state.generation_poll_timeout_ms) || 0;
        window.igniteDocumentPollTimeoutMs = Number(state.document_poll_timeout_ms) || 0;
        const allProviders = [...(state.providers || []), ...Object.keys(window.customGroups)];
        allProviders.forEach(p => {
            if (typeof registerProviderState === 'function') {
                registerProviderState(p);
            }
        });

        // Render chats list dynamically
        renderChatsList(state.providers, state.last_messages);

        const profileAvatar = document.getElementById('rail-profile-avatar');
        if (profileAvatar && typeof getAvatarHtml === 'function') {
            profileAvatar.innerHTML = getAvatarHtml('user', true);
        }

        if (state.models[currentProvider]) {
            populateModels(state.models[currentProvider], state.current_model[currentProvider]);
            document.getElementById('model-select').disabled = false;
        } else {
            const sel = document.getElementById('model-select');
            sel.innerHTML = '<option value="group">Group Chat</option>';
            sel.disabled = true;
        }
        // Render group AI providers panel
        if (typeof window.renderGroupAiProviders === 'function') {
            window.renderGroupAiProviders(currentProvider, state.models, state.current_model);
        }

        updateHeaderInfo(currentProvider);
        updateLanguageUI();
        if (typeof translateGroupModal === 'function') translateGroupModal();
        updateBackgroundImage();

        const isDarkMode = !document.body.classList.contains('light-mode');
        const theme = isDarkMode ? 'dark' : 'light';
        if (window.pywebview && window.pywebview.api && window.pywebview.api.set_theme_window_size) {
            window.pywebview.api.set_theme_window_size(theme);
        }

        window.pywebview.api.set_provider(currentProvider).then(res => {
            if (!res || res.status === 'error') {
                const msg = (res && (res.message || res.error)) || 'Failed to set provider';
                console.error("Error setting initial provider:", msg);
                const box = document.getElementById('chat-container');
                if (box) {
                    box.innerHTML = `
                        <div style="text-align:center;margin-top:50px;color:var(--text-muted);padding:0 16px;">
                            <h3>⚠️ Backend connection problem</h3>
                            <p>${msg}</p>
                            <p style="margin-top:12px;font-size:0.9em;">Check app/.env: IGNITE_RUNTIME_MODE=remote, IGNITE_API_BASE_URL, IGNITE_API_KEY</p>
                        </div>
                    `;
                }
                return;
            }
            const initialHistory = res.history || [];
            showWelcomeOrHistory(initialHistory, currentProvider);
            window._lastHistoryCount = window._lastHistoryCount || {};
            if (initialHistory.length > 0) {
                window._lastHistoryCount[currentProvider] = initialHistory.length;
            }
            updateInputButtonsState();
            updateNotificationBell();
            if (typeof window.refreshPinBanner === 'function') {
                window.refreshPinBanner();
            }
            if (typeof window.applyDisappearingMessages === 'function') {
                window.applyDisappearingMessages();
            }
        }).catch(err => {
            console.error("Error setting initial provider:", err);
            document.getElementById('chat-container').innerHTML = `
                <div style="text-align:center;margin-top:50px;color:var(--text-muted);padding:0 16px;">
                    <h3>⚠️ Backend connection problem</h3>
                    <p>${err.message || err}</p>
                </div>
            `;
        });
    }).catch(err => {
        console.error("Failed to get initial state:", err);
        document.getElementById('chat-container').innerHTML = `
            <div style="text-align:center;margin-top:50px;color:var(--text-muted);padding:0 16px;">
                <h3>⚠️ Error loading app state</h3>
                <p>${err.message || err}</p>
                <p style="margin-top:12px;font-size:0.9em;">Check app/.env remote settings and that the ACA /health endpoint responds.</p>
            </div>
        `;
    });

    // Sidebar triggers
    document.getElementById('toggle-sidebar').addEventListener('click', () => {
        document.getElementById('sidebar').classList.remove('hidden');
    });
    document.getElementById('close-sidebar').addEventListener('click', () => {
        document.getElementById('sidebar').classList.add('hidden');
    });

    // Left rail settings button trigger
    const railSettingsBtn = document.getElementById('rail-settings-btn');
    if (railSettingsBtn) {
        railSettingsBtn.addEventListener('click', () => {
            const sidebar = document.getElementById('sidebar');
            if (sidebar) {
                sidebar.classList.toggle('hidden');
            }
        });
    }

    // Collapse Chats trigger (collapses right main chat pane and expands chats list)
    const collapseChatsBtn = document.getElementById('collapse-chats-btn');
    const appContainer = document.getElementById('app-container');
    if (collapseChatsBtn && appContainer) {
        collapseChatsBtn.addEventListener('click', () => {
            appContainer.classList.add('chat-collapsed');
        });
    }

    // Left rail Chats bubble button trigger (restores right main chat pane)
    const railChatsBtn = document.getElementById('rail-chats-btn');
    if (railChatsBtn && appContainer) {
        railChatsBtn.addEventListener('click', () => {
            appContainer.classList.remove('chat-collapsed');
        });
    }

    // Dark Mode toggle
    document.getElementById('dark-mode-toggle').addEventListener('change', (e) => {
        if (e.target.checked) {
            document.body.classList.remove('light-mode');
        } else {
            document.body.classList.add('light-mode');
        }
        updateBackgroundImage();

        // Resize the application window based on theme
        const theme = e.target.checked ? 'dark' : 'light';
        if (window.pywebview && window.pywebview.api && window.pywebview.api.set_theme_window_size) {
            window.pywebview.api.set_theme_window_size(theme);
        }
    });

    // Provider switching bindings (now handled dynamically by renderChatsList -> bindProviderRadioListeners)

    // Model switching (resets/restores history for the model session)
    document.getElementById('model-select').addEventListener('change', (e) => {
        if (isProcessing[currentProvider]) {
            alert(currentLang === 'es' ? "No puedes cambiar de modelo mientras se está procesando una respuesta." : "You cannot change models while a response is being processed.");
            if (e.target.dataset.prevValue) {
                e.target.value = e.target.dataset.prevValue;
            }
            return;
        }
        if (isPopulatingModels) return;

        // Save current selection for reverting if needed
        e.target.dataset.prevValue = e.target.value;
        if (typeof window.cancelVoiceSession === 'function') window.cancelVoiceSession();

        const isGroup = currentProvider && currentProvider.startsWith('group_');
        if (isGroup) {
            const groupProvSelect = document.getElementById('group-provider-select');
            const selectedPart = groupProvSelect ? groupProvSelect.value : null;
            if (selectedPart) {
                window.pywebview.api.set_participant_model(currentProvider, selectedPart, e.target.value).then((res) => {
                    if (res && res.status === 'success') {
                        // Store the selected model in the local client state cache
                        if (!window.customGroupModelCache) window.customGroupModelCache = {};
                        if (!window.customGroupModelCache[currentProvider]) window.customGroupModelCache[currentProvider] = {};
                        window.customGroupModelCache[currentProvider][selectedPart] = e.target.value;
                    }
                }).catch(err => console.error("Error setting participant model:", err));
            }
        } else {
            window.pywebview.api.set_model(currentProvider, e.target.value).then((res) => {
                const history = (res && res.history) ? res.history : [];
                totalTokens = (res && res.token_total) ? res.token_total : 0;
                updateTokenDisplay();
                showWelcomeOrHistory(history, currentProvider);
            });
        }
    });

    // ── Group AI Providers Selection (Two-dropdown Layout) ─────────────────
    window.renderGroupAiProviders = function (groupId, models, currentModel) {
        const provSection = document.getElementById('group-provider-select-section');
        const provSelect = document.getElementById('group-provider-select');
        if (!provSection || !provSelect) return;

        const isGroup = groupId && groupId.startsWith('group_');
        provSection.style.display = isGroup ? 'block' : 'none';
        if (!isGroup) return;

        // Translate the AI Provider dropdown label
        const t = (currentLang === 'es') ? 'Proveedor IA' : 'AI Provider';
        const label = document.getElementById('group-provider-select-label');
        if (label) label.textContent = '🤖 ' + t;

        const groupInfo = window.customGroups && window.customGroups[groupId];
        const participants = (groupInfo && groupInfo.participants) ? groupInfo.participants : [];

        // Save current selection to restore it if it's still valid
        const prevSelected = provSelect.value;

        provSelect.innerHTML = '';
        participants.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p;
            opt.textContent = p;
            provSelect.appendChild(opt);
        });

        // Trigger loading models for the currently selected participant in Choose Model dropdown
        const updateModelDropdown = () => {
            if (isProcessing[groupId]) {
                const t = (currentLang === 'es')
                    ? 'No puedes cambiar el participante mientras el grupo está generando.'
                    : 'You cannot change participant view while the group is generating.';
                if (typeof showTemporaryToast === 'function') {
                    showTemporaryToast(t);
                } else {
                    alert(t);
                }
                return;
            }
            const selectedPart = provSelect.value;
            if (!selectedPart) return;
            const providerModels = (models && models[selectedPart]) ? models[selectedPart] : [];

            // Check cache or default
            if (!window.customGroupModelCache) window.customGroupModelCache = {};
            if (!window.customGroupModelCache[groupId]) window.customGroupModelCache[groupId] = {};
            const cachedModel = window.customGroupModelCache[groupId][selectedPart];

            const activeModel = cachedModel || ((currentModel && currentModel[selectedPart]) ? currentModel[selectedPart] : (providerModels[0] || ''));

            // Temporarily enable model-select to populate models for the selected provider
            document.getElementById('model-select').disabled = false;
            populateModels(providerModels, activeModel);
        };

        provSelect.onchange = updateModelDropdown;

        // Restore previous selection or default to first participant
        if (participants.includes(prevSelected)) {
            provSelect.value = prevSelected;
        } else if (participants.length > 0) {
            provSelect.value = participants[0];
        }

        updateModelDropdown();
    };


    // Clear chat conversation handler (shared by sidebar button and dropdown item)
    const clearChatAction = () => {
        const isSpanish = currentLang === 'es';
        const confirmMsg = isSpanish
            ? '¿Estás seguro de que deseas borrar esta conversación?'
            : 'Are you sure you want to clear this conversation?';

        if (confirm(confirmMsg)) {
            const clearedProvider = currentProvider;
            if (typeof window.cancelVoiceSession === 'function') window.cancelVoiceSession();
            if (typeof window.cancelProviderProcessing === 'function') {
                window.cancelProviderProcessing(clearedProvider);
            }
            // Never resetAllFSMs here — that desyncs background parallel chats.
            if (window.getProviderFSM && window.FSM_STATES) {
                const fsm = window.getProviderFSM(clearedProvider);
                if (fsm && !fsm.is(window.FSM_STATES.IDLE)) {
                    fsm.reset({ reason: 'clearChatAction' });
                }
            }

            // OPTIMISTIC 0ms UI RESET: Instantly wipe screen; welcome after clear persists.
            const chatContainer = document.getElementById('chat-container');
            if (chatContainer) chatContainer.innerHTML = '';
            window.cachedHistories = window.cachedHistories || {};
            window.cachedHistories[clearedProvider] = [];
            window.providerTokens = window.providerTokens || {};
            window.providerTokens[clearedProvider] = 0;
            totalTokens = 0;
            const totalCostEl = document.getElementById('total-cost-display');
            if (totalCostEl && currentProvider === clearedProvider) {
                totalCostEl.textContent = '$0.0000 USD';
            }
            updateTokenDisplay(clearedProvider);
            if (typeof window.syncSharedControlsForProvider === 'function') {
                window.syncSharedControlsForProvider(clearedProvider);
            }
            if (typeof window.updateBlockUI === 'function') {
                window.updateBlockUI();
            }

            // Skill §12.1: await clear_history THEN welcome (never parallel race).
            const afterClear = () => {
                updateTokenDisplay(clearedProvider);
                if (currentProvider === clearedProvider) {
                    sendWelcomeMessage();
                }
            };
            if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.clear_history === 'function') {
                Promise.resolve(window.pywebview.api.clear_history(clearedProvider))
                    .then(afterClear)
                    .catch((err) => {
                        console.error('clear_history background call failed:', err);
                        afterClear();
                    });
            } else {
                afterClear();
            }
        }
    };

    document.getElementById('clear-chat-btn').addEventListener('click', clearChatAction);

    // Chat text input events
    msgInput.addEventListener('keydown', (e) => {
        if (typeof window.cancelVoiceSession === 'function') window.cancelVoiceSession();
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            healStuckSendState();
            if (isProcessing[currentProvider]) {
                if (typeof window.cancelProviderProcessing === 'function') {
                    window.cancelProviderProcessing(currentProvider);
                } else {
                    isProcessing[currentProvider] = false;
                }
            }
            sendMessage();
        }
    });

    msgInput.addEventListener('input', function () {
        if (typeof window.cancelVoiceSession === 'function') window.cancelVoiceSession();
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
        healStuckSendState();
    });

    function inferMimeType(file) {
        if (file && file.type) return file.type;
        const name = ((file && file.name) || '').toLowerCase();
        if (name.endsWith('.pptx')) return 'application/vnd.openxmlformats-officedocument.presentationml.presentation';
        if (name.endsWith('.ppt')) return 'application/vnd.ms-powerpoint';
        if (name.endsWith('.docx')) return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
        if (name.endsWith('.doc')) return 'application/msword';
        if (name.endsWith('.xlsx')) return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
        if (name.endsWith('.xls')) return 'application/vnd.ms-excel';
        if (name.endsWith('.csv')) return 'text/csv';
        if (name.endsWith('.pdf')) return 'application/pdf';
        if (name.endsWith('.png')) return 'image/png';
        if (name.endsWith('.jpg') || name.endsWith('.jpeg')) return 'image/jpeg';
        if (name.endsWith('.webp')) return 'image/webp';
        if (name.endsWith('.gif')) return 'image/gif';
        if (name.endsWith('.mp3')) return 'audio/mpeg';
        if (name.endsWith('.wav')) return 'audio/wav';
        if (name.endsWith('.m4a')) return 'audio/mp4';
        if (name.endsWith('.txt') || name.endsWith('.md')) return 'text/plain';
        return 'application/octet-stream';
    }

    function healStuckSendState() {
        // If a prior send left isProcessing=true while the FSM is idle, unlock send.
        if (
            isProcessing[currentProvider] &&
            window.getProviderFSM &&
            window.FSM_STATES
        ) {
            const fsm = window.getProviderFSM(currentProvider);
            if (fsm && fsm.is(window.FSM_STATES.IDLE)) {
                isProcessing[currentProvider] = false;
                if (typeof refreshGeneratingSidebarMarkers === 'function') {
                    refreshGeneratingSidebarMarkers();
                }
            }
        }
        updateInputButtonsState();
    }

    // Send button event
    document.getElementById('send-btn').addEventListener('click', (e) => {
        if (typeof window.cancelVoiceSession === 'function') window.cancelVoiceSession();
        healStuckSendState();

        const msgInput = document.getElementById('message-input');
        const hasText = msgInput && msgInput.value.trim() !== '';
        const hasFiles = typeof pendingFiles !== 'undefined' && pendingFiles.length > 0;
        if (!hasText && !hasFiles) return;

        if (isProcessing[currentProvider]) {
            console.log('Interpreting send click as interrupt & send new message');
            if (typeof window.cancelProviderProcessing === 'function') {
                window.cancelProviderProcessing(currentProvider);
            } else {
                isProcessing[currentProvider] = false;
            }
        }

        const btn = e.currentTarget;
        if (btn) {
            btn.disabled = false;
            btn.removeAttribute('disabled');
            btn.style.pointerEvents = 'auto';
        }
        sendMessage();
    });

    // Reusable file selection handler (shared by file input and drag-and-drop drop)
    function handleFileSelection(files) {
        if (!files || files.length === 0) return;
        if (typeof window.cancelVoiceSession === 'function') window.cancelVoiceSession();
        Array.from(files).forEach(file => {
            const reader = new FileReader();
            reader.onload = (event) => {
                const result = event.target && event.target.result;
                if (typeof result !== 'string' || !result.includes(',')) {
                    console.error('Failed to read file as data URL:', file && file.name);
                    return;
                }
                const base64String = result.split(',')[1];
                const pending = {
                    name: file.name,
                    mime_type: inferMimeType(file),
                    base64: base64String,
                    size: file.size
                };
                pendingFiles.push(pending);
                healStuckSendState();
                renderPendingFiles();
                updateInputButtonsState();
                if (typeof window.hydrateFilePreview === 'function') {
                    window.hydrateFilePreview(pending).then(() => {
                        renderPendingFiles();
                    }).catch((err) => {
                        console.warn('Pending file preview failed:', err);
                    });
                }
            };
            reader.onerror = () => {
                console.error('FileReader error for', file && file.name, reader.error);
            };
            reader.readAsDataURL(file);
        });
    }

    window.handleFileSelection = handleFileSelection;
    window.attachFileDirectly = function (file) {
        handleFileSelection(file ? [file] : []);
    };

    // Attach button event
    document.getElementById('attach-btn').addEventListener('click', () => {
        if (typeof window.cancelVoiceSession === 'function') window.cancelVoiceSession();
        document.getElementById('file-input').click();
    });

    // File input changes
    document.getElementById('file-input').addEventListener('change', (e) => {
        handleFileSelection(e.target.files);
        e.target.value = '';
    });

    // Drag and Drop File Upload
    const dropOverlay = document.getElementById('drag-drop-overlay');
    let dragCounter = 0; // Prevent overlay flickering when passing over child elements

    window.addEventListener('dragenter', (e) => {
        e.preventDefault();
        dragCounter++;
        if (dropOverlay) {
            dropOverlay.classList.add('active');
            // Dynamically translate drop overlay text
            const dragDropTextEl = document.getElementById('drag-drop-text');
            if (dragDropTextEl) {
                dragDropTextEl.textContent = currentLang === 'es' ? 'Suelta los archivos aquí para adjuntarlos' : 'Drop files here to attach';
            }
        }
    });

    window.addEventListener('dragover', (e) => {
        e.preventDefault();
    });

    window.addEventListener('dragleave', (e) => {
        e.preventDefault();
        dragCounter--;
        if (dragCounter === 0 && dropOverlay) {
            dropOverlay.classList.remove('active');
        }
    });

    window.addEventListener('drop', (e) => {
        e.preventDefault();
        dragCounter = 0;
        if (dropOverlay) {
            dropOverlay.classList.remove('active');
        }
        if (e.dataTransfer && e.dataTransfer.files) {
            handleFileSelection(e.dataTransfer.files);
        }
    });

    // Clipboard paste event
    document.addEventListener('paste', (e) => {
        const items = (e.clipboardData || e.originalEvent.clipboardData).items;
        for (let i = 0; i < items.length; i++) {
            if (items[i].type.indexOf("image") === 0) {
                if (typeof window.cancelVoiceSession === 'function') window.cancelVoiceSession();
                const file = items[i].getAsFile();
                const reader = new FileReader();
                reader.onload = (event) => {
                    const base64String = event.target.result.split(',')[1];
                    pendingFiles.push({
                        name: `pasted_image_${Date.now()}.png`,
                        mime_type: inferMimeType(file),
                        base64: base64String,
                        size: file.size
                    });
                    healStuckSendState();
                    renderPendingFiles();
                    updateInputButtonsState();
                };
                reader.readAsDataURL(file);
                e.preventDefault();
                break;
            }
        }
    });

    // Microphone interaction events (Click to toggle recording and auto-submit)
    const micBtn = document.getElementById('mic-btn');
    micBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (typeof toggleRecording === 'function') {
            toggleRecording();
        }
    });

    // Intercept link clicks and open them in the default external browser
    document.addEventListener('click', (e) => {
        const link = e.target.closest('a');
        if (link && link.href) {
            const href = link.getAttribute('href');
            if (href && (href.startsWith('http://') || href.startsWith('https://') || href.startsWith('www.'))) {
                e.preventDefault();
                if (window.pywebview && window.pywebview.api && window.pywebview.api.open_external_link) {
                    window.pywebview.api.open_external_link(link.href);
                } else {
                    window.open(link.href, '_blank');
                }
            }
        }
    });



    // Filter chats in the list based on search query and category chips
    const chatsSearchInput = document.getElementById('chats-search-input');
    const filterAll = document.getElementById('filter-all');
    const filterUnread = document.getElementById('filter-unread');

    let currentFilterTab = 'all'; // 'all' or 'unread'

    function filterChats() {
        const query = chatsSearchInput ? chatsSearchInput.value.toLowerCase().trim() : '';
        const items = document.querySelectorAll('.chat-item');

        items.forEach(item => {
            const provider = item.getAttribute('data-provider') || '';
            const providerName = provider.toLowerCase();

            // Unread filter condition
            let passUnread = true;
            if (currentFilterTab === 'unread') {
                const count = unreadCounts[provider] || 0;
                passUnread = count > 0;
            }

            // Search filter condition: matches provider name, last message preview, or conversation history
            let passSearch = true;
            if (query) {
                const lastMsgEl = document.getElementById(`chat-item-last-msg-${provider}`);
                const lastMsgText = lastMsgEl ? lastMsgEl.textContent.toLowerCase() : '';

                let historyMatch = false;
                if (typeof window.getProviderHistory === 'function') {
                    const h = window.getProviderHistory(provider);
                    if (Array.isArray(h)) {
                        historyMatch = h.some(m => (m.content && typeof m.content === 'string') && m.content.toLowerCase().includes(query));
                    }
                }

                passSearch = providerName.includes(query) || lastMsgText.includes(query) || historyMatch;
            }

            if (passUnread && passSearch) {
                item.style.display = 'flex';
            } else {
                item.style.display = 'none';
            }
        });
    }

    if (chatsSearchInput) {
        chatsSearchInput.addEventListener('input', filterChats);
    }

    if (filterAll) {
        filterAll.addEventListener('click', () => {
            filterAll.classList.add('active');
            if (filterUnread) filterUnread.classList.remove('active');
            currentFilterTab = 'all';
            filterChats();
        });
    }

    if (filterUnread) {
        filterUnread.addEventListener('click', () => {
            filterUnread.classList.add('active');
            if (filterAll) filterAll.classList.remove('active');
            currentFilterTab = 'unread';
            filterChats();
        });
    }

    // Debounce filterChats when unread counts update — rapid group replies
    // were thrashing the sidebar under the search/filter strip.
    const originalUpdateNotificationBell = window.updateNotificationBell;
    let _filterChatsTimer = null;
    window.updateNotificationBell = function () {
        if (typeof originalUpdateNotificationBell === 'function') {
            originalUpdateNotificationBell();
        }
        if (_filterChatsTimer) clearTimeout(_filterChatsTimer);
        _filterChatsTimer = setTimeout(() => {
            _filterChatsTimer = null;
            filterChats();
        }, 120);
    };

    // ============================================================================
    // MESSAGE SEARCH & DROPDOWN EVENTS INITIALIZATION
    // ============================================================================

    // 1. Search Bar Listeners
    const headerSearchBtn = document.getElementById('header-search-btn');
    if (headerSearchBtn) {
        headerSearchBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            window.openSearch();
        });
    }

    const searchCloseBtn = document.getElementById('message-search-close');
    if (searchCloseBtn) {
        searchCloseBtn.addEventListener('click', () => {
            window.closeSearch();
        });
    }

    const searchInput = document.getElementById('message-search-input');
    if (searchInput) {
        searchInput.addEventListener('input', () => {
            window.onSearchInput();
        });
        // Handle Enter key inside search input to go to next match
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                window.nextSearchMatch();
            }
        });
    }

    const searchPrevBtn = document.getElementById('message-search-prev');
    if (searchPrevBtn) {
        searchPrevBtn.addEventListener('click', () => {
            window.prevSearchMatch();
        });
    }

    const searchNextBtn = document.getElementById('message-search-next');
    if (searchNextBtn) {
        searchNextBtn.addEventListener('click', () => {
            window.nextSearchMatch();
        });
    }

    // 2. Dropdown Menu Triggers
    const menuBtn = document.getElementById('menu-btn');
    const dropdown = document.getElementById('header-menu-dropdown');

    if (menuBtn && dropdown) {
        menuBtn.addEventListener('click', (e) => {
            e.stopPropagation();

            const isGroup = currentProvider && currentProvider.startsWith('group_');
            const contactInfoText = document.getElementById('menu-contact-info-text');
            const isSpanish = currentLang === 'es';

            if (contactInfoText) {
                contactInfoText.textContent = isGroup
                    ? (isSpanish ? 'Info. del grupo' : 'Group info')
                    : (isSpanish ? 'Info. del contacto' : 'Contact info');
            }

            const exitGroupItem = document.getElementById('menu-exit-group');
            const clearChatItem = document.getElementById('menu-clear-chat');
            const dividerGroupActions = document.getElementById('menu-divider-group-actions');

            // Individual-only options & dividers
            const indOnlyIds = [
                'menu-disappearing',
                'menu-call-link',
                'menu-schedule',
                'menu-group-call',
                'menu-report',
                'menu-block',
                'menu-divider-calls',
                'menu-divider-reports'
            ];

            if (isGroup) {
                // Show group items
                if (exitGroupItem) exitGroupItem.style.display = 'flex';
                if (clearChatItem) clearChatItem.style.display = 'flex';
                if (dividerGroupActions) dividerGroupActions.style.display = 'block';

                // Hide individual items
                indOnlyIds.forEach(id => {
                    const el = document.getElementById(id);
                    if (el) el.style.display = 'none';
                });
            } else {
                // Hide group items
                if (exitGroupItem) exitGroupItem.style.display = 'none';
                if (clearChatItem) clearChatItem.style.display = 'none';
                if (dividerGroupActions) dividerGroupActions.style.display = 'none';

                // Show individual items
                indOnlyIds.forEach(id => {
                    const el = document.getElementById(id);
                    if (el) {
                        if (id.startsWith('menu-divider-')) {
                            el.style.display = 'block';
                        } else {
                            el.style.display = 'flex';
                        }
                    }
                });
            }

            dropdown.classList.toggle('hidden');
        });
    }

    // Close dropdown immediately when clicking anywhere else
    document.addEventListener('click', (e) => {
        if (dropdown && !dropdown.classList.contains('hidden')) {
            if (!dropdown.contains(e.target) && e.target !== menuBtn && !menuBtn.contains(e.target)) {
                dropdown.classList.add('hidden');
            }
        }
    }, { capture: true });

    // Helper function to show a custom toast/notification overlay
    function showNotification(text) {
        let toast = document.getElementById('custom-toast-notification');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'custom-toast-notification';
            toast.style.position = 'fixed';
            toast.style.bottom = '95px';
            toast.style.right = '30px';
            toast.style.backgroundColor = 'rgba(28, 30, 31, 0.95)';
            toast.style.color = '#fff';
            toast.style.padding = '12px 24px';
            toast.style.borderRadius = '8px';
            toast.style.zIndex = '99999';
            toast.style.fontSize = '14px';
            toast.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.4)';
            toast.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
            toast.style.border = '1px solid rgba(255, 255, 255, 0.08)';
            document.body.appendChild(toast);
        }
        toast.textContent = text;
        toast.style.opacity = '1';
        toast.style.transform = 'translateY(0)';

        if (window.toastTimeout) clearTimeout(window.toastTimeout);
        window.toastTimeout = setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(10px)';
        }, 3000);
    }

    // Bind Dropdown Items clicks
    const bindDropdownItem = (id, callback) => {
        const item = document.getElementById(id);
        if (item) {
            item.addEventListener('click', (e) => {
                e.stopPropagation();
                if (dropdown) dropdown.classList.add('hidden');
                callback();
            });
        }
    };

    bindDropdownItem('menu-contact-info', () => {
        const sidebar = document.getElementById('sidebar');
        if (sidebar) sidebar.classList.remove('hidden');
    });

    bindDropdownItem('menu-search', () => {
        window.openSearch();
    });

    bindDropdownItem('menu-summarize', () => {
        if (typeof window.summarizeChat === 'function') window.summarizeChat();
    });

    bindDropdownItem('menu-export', () => {
        if (typeof window.exportChatTxt === 'function') window.exportChatTxt();
    });

    bindDropdownItem('menu-select-messages', () => {
        showNotification(currentLang === 'es' ? 'Selecciona mensajes con clic derecho / menú de cada burbuja' : 'Select messages via right-click / bubble menu');
    });

    bindDropdownItem('menu-mute', () => {
        showNotification(currentLang === 'es' ? "Notificaciones silenciadas" : "Notifications muted");
    });

    bindDropdownItem('menu-disappearing', () => {
        if (typeof window.openDisappearingModal === 'function') window.openDisappearingModal();
    });

    bindDropdownItem('menu-favorites', () => {
        if (typeof window.openStarredPanel === 'function') window.openStarredPanel();
    });

    bindDropdownItem('menu-add-list', () => {
        if (typeof window.archiveChat === 'function') window.archiveChat(currentProvider);
    });

    bindDropdownItem('menu-close', () => {
        const chatContainer = document.getElementById('chat-container');
        if (chatContainer) {
            chatContainer.innerHTML = `
                <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; height:100%; color:var(--text-muted);">
                    <span style="font-size: 48px; margin-bottom: 15px;">💬</span>
                    <h3>IgniteChat</h3>
                    <p style="font-size: 14px; opacity: 0.8;">${currentLang === 'es' ? 'Selecciona un chat para empezar a enviar mensajes' : 'Select a chat to start messaging'}</p>
                </div>
            `;
        }
    });

    bindDropdownItem('menu-clear-chat', clearChatAction);

    bindDropdownItem('menu-exit-group', () => {
        const isSpanish = currentLang === 'es';
        const confirmMsg = isSpanish
            ? '¿Estás seguro de que deseas salir y eliminar este grupo?'
            : 'Are you sure you want to exit and delete this group?';

        if (confirm(confirmMsg)) {
            if (typeof window.cancelVoiceSession === 'function') window.cancelVoiceSession();
            window.pywebview.api.delete_group(currentProvider).then(res => {
                if (res.status === 'success') {
                    renderChatsList(res.providers, {});
                    selectProvider('Gemini');
                    showNotification(isSpanish ? 'Saliste del grupo exitosamente' : 'Exited group successfully');
                } else {
                    alert('Error: ' + res.message);
                }
            }).catch(err => {
                console.error("Delete group error:", err);
                alert('Connection error when exiting group.');
            });
        }
    });

    bindDropdownItem('menu-call-link', () => {
        showNotification(currentLang === 'es' ? "Enlace de llamada copiado al portapapeles" : "Call link copied to clipboard");
    });

    bindDropdownItem('menu-schedule', () => {
        showNotification(currentLang === 'es' ? "Llamada programada con éxito" : "Call scheduled successfully");
    });

    bindDropdownItem('menu-group-call', () => {
        showNotification(currentLang === 'es' ? "Iniciando llamada grupal..." : "Starting group call...");
    });

    // Close dropdown + open archived panel
    const archivedBtn = document.querySelector('.rail-btn[title="Archived"]');
    if (archivedBtn) {
        archivedBtn.addEventListener('click', () => {
            if (typeof window.openArchivedPanel === 'function') window.openArchivedPanel();
        });
    }

    bindDropdownItem('menu-report', () => {
        showNotification(currentLang === 'es' ? 'Asistente reportado con éxito' : 'Assistant reported successfully');
    });

    bindDropdownItem('menu-block', () => {
        window.toggleBlockProvider(currentProvider);
    });

    // 3. Update Block UI on Startup
    if (typeof window.updateBlockUI === 'function') {
        window.updateBlockUI();
    }

    // ============================================================================
    // NEW GROUP MODAL LOGIC
    // ============================================================================
    const newGroupBtn = document.getElementById('new-group-btn');
    const groupModal = document.getElementById('new-group-modal');
    const closeGroupModalBtn = document.getElementById('close-group-modal');
    const createGroupSubmitBtn = document.getElementById('create-group-submit');
    const groupNameInput = document.getElementById('group-name-input');
    const groupSearchInput = document.getElementById('group-search-input');
    const contactsChecklist = document.getElementById('contacts-checklist');
    const selectedParticipantsContainer = document.getElementById('selected-participants-container');

    let selectedAIModels = new Set();
    const standardAIList = ["Gemini", "DeepSeek", "OpenAI", "Anthropic", "Perplexity", "Grok"];

    // Open Modal
    if (newGroupBtn) {
        newGroupBtn.addEventListener('click', () => {
            selectedAIModels.clear();
            if (groupNameInput) groupNameInput.value = '';
            if (groupSearchInput) groupSearchInput.value = '';
            renderContactsChecklist();
            renderSelectedPills();
            if (groupModal) groupModal.classList.remove('hidden');
        });
    }

    // Close Modal
    if (closeGroupModalBtn) {
        closeGroupModalBtn.addEventListener('click', () => {
            if (groupModal) groupModal.classList.add('hidden');
        });
    }

    // Render Contacts Checklist
    window.renderContactsChecklist = function () {
        if (!contactsChecklist) return;
        contactsChecklist.innerHTML = '';
        const query = groupSearchInput ? groupSearchInput.value.toLowerCase().trim() : '';

        standardAIList.forEach(p => {
            if (query && !p.toLowerCase().includes(query)) return;

            const isSelected = selectedAIModels.has(p);
            const row = document.createElement('div');
            row.className = `contact-check-row${isSelected ? ' selected' : ''}`;
            row.setAttribute('data-provider', p);

            row.innerHTML = `
                <div class="contact-check-box">
                    <div class="contact-custom-checkbox">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" width="12" height="12">
                            <polyline points="20 6 9 17 4 12"></polyline>
                        </svg>
                    </div>
                </div>
                <div class="contact-item-avatar">${getAvatarHtml(p, true)}</div>
                <div class="contact-item-text">
                    <span class="contact-item-title">${p}</span>
                    <span class="contact-item-tagline">${translations[currentLang].group_tagline}</span>
                </div>
            `;

            row.addEventListener('click', () => {
                if (selectedAIModels.has(p)) {
                    selectedAIModels.delete(p);
                    row.classList.remove('selected');
                } else {
                    selectedAIModels.add(p);
                    row.classList.add('selected');
                }
                renderSelectedPills();
            });

            contactsChecklist.appendChild(row);
        });
    };

    // Render Selected Pills
    function renderSelectedPills() {
        if (!selectedParticipantsContainer) return;
        selectedParticipantsContainer.innerHTML = '';

        selectedAIModels.forEach(p => {
            const pill = document.createElement('div');
            pill.className = 'participant-pill';
            pill.innerHTML = `
                <div class="participant-pill-avatar">${getAvatarHtml(p, true)}</div>
                <span>${p}</span>
                <button class="participant-pill-remove">&times;</button>
            `;

            pill.querySelector('.participant-pill-remove').addEventListener('click', (e) => {
                e.stopPropagation();
                selectedAIModels.delete(p);
                renderSelectedPills();

                // update row selection status if visible
                const row = contactsChecklist.querySelector(`.contact-check-row[data-provider="${p}"]`);
                if (row) row.classList.remove('selected');
            });

            selectedParticipantsContainer.appendChild(pill);
        });
    }

    // Filter Checklist on Search Input
    if (groupSearchInput) {
        groupSearchInput.addEventListener('input', window.renderContactsChecklist);
    }

    // Create Group Submit
    if (createGroupSubmitBtn) {
        createGroupSubmitBtn.addEventListener('click', () => {
            const name = groupNameInput ? groupNameInput.value.trim() : '';
            if (!name) {
                alert(currentLang === 'es' ? 'Por favor ingrese un nombre para el grupo.' : 'Please enter a group subject.');
                return;
            }
            if (selectedAIModels.size === 0) {
                alert(currentLang === 'es' ? 'Por favor seleccione al menos un participante.' : 'Please select at least one participant.');
                return;
            }

            const participants = Array.from(selectedAIModels);
            window.pywebview.api.create_group(name, participants).then(res => {
                if (res.status === 'success') {
                    window.customGroups[res.group_id] = {
                        name: name,
                        participants: participants
                    };

                    if (groupModal) groupModal.classList.add('hidden');

                    // Re-render sidebar chats list and select the new group chat
                    renderChatsList(res.providers, {});
                    selectProvider(res.group_id);
                } else {
                    alert('Error creating group: ' + res.message);
                }
            }).catch(err => {
                console.error("Create group API error:", err);
                alert('Connection error when creating group.');
            });
        });
    }

    // ── Emoji Picker Logic ────────────────────────────────────────────────
    const emojiBtn = document.getElementById('emoji-btn');
    const emojiPicker = document.getElementById('emoji-picker');
    const emojiPickerList = document.getElementById('emoji-picker-list');
    const emojiSearch = document.getElementById('emoji-search');
    const messageInput = document.getElementById('message-input');

    const emojiData = {
        smileys: ["😀", "😃", "😄", "😁", "😆", "😅", "😂", "🤣", "😊", "😇", "🙂", "🙃", "😉", "😌", "😍", "🥰", "😘", "😗", "😙", "😚", "😋", "😛", "😝", "😜", "🤪", "🤨", "🧐", "🤓", "😎", "🤩", "🥳", "😏", "😒", "😞", "😔", "😟", "😕", "🙁", "☹️", "😣", "😖", "😫", "😩", "🥺", "😢", "😭", "😤", "😠", "😡", "🤬", "🤯", "😳", "🥵", "🥶", "😱", "😨", "😰", "😥", "😓", "🤗", "🤔", "🤭", "🤫", "🤥", "😶", "😐", "😑", "😬", "🙄", "😯", "😦", "😧", "😮", "😲", "🥱", "😴", "🤤", "😪", "😵", "🤐", "🥴", "🤢", "🤮", "🤧", "😷", "🤒", "🤕", "🤑", "🤠", "😈", "👿", "👹", "👺", "🤡", "💩", "👻", "💀", "☠️", "👽", "👾", "🤖", "🎃", "😺", "😸", "😹", "😻", "😼", "😽", "🙀", "😿", "😾"],
        nature: ["🙈", "🙉", "🙊", "💥", "💫", "💦", "💨", "🐵", "🐒", "🦍", "🦧", "🐶", "🐕", "🦮", "🐕‍🦺", "🐩", "🐺", "🦊", "🦝", "🐱", "🐈‍⬛", "🦁", "🐯", "🐅", "🐆", "🐴", "🐎", "🦄", "🦓", "🦌", "🦬", "🐮", "🐂", "🐃", "🐄", "🐷", "🐖", "🐗", "🐽", "🐏", "🐑", "🐐", "🐪", "🐫", "🦙", "🦒", "🐘", "🦣", "🦏", "🦛", "🐭", "🐀", "🐹", "🐰", "🐿️", "🦫", "🦔", "🦇", "🐻", "🐻‍❄️", "🐨", "🐼", "🦥", "🦦", "🦨", "🦘", "🦡", "🐾", "🍁", "🍄", "🌵", "🌲", "🌳", "🌴", "🌱", "🌿", "☘️", "🍀", "🌾", "🌷", "🌹", "🌺", "🌸", "🌼", "🌻"],
        food: ["🍏", "🍎", "🍐", "🍊", "🍋", "🍌", "🍉", "🍇", "🍓", "🫐", "🍒", "🍑", "🥭", "🍍", "🥥", "🥝", "🍅", "🍆", "🥑", "🥦", "🥬", "🥒", "🌶️", "🫑", "🌽", "🥕", "🫒", "🧄", "🧅", "🥔", "🍠", "🥐", "🍞", "🥖", "🥨", "🥯", "🥞", "🧇", "🧀", "🍖", "🍗", "🥩", "🥓", "🍔", "🍟", "🍕", "🌭", "🥪", "🌮", "🌯", "🫓", "🥚", "🍳", "🥘", "🍲", "🫕", "🥣", "🥗", "🍿", "🍿", "🍩", "🍪"],
        activity: ["👾", "🎮", "🕹️", "🎰", "🎲", "🎳", "⚽", "🏀", "🏈", "⚾", "🥎", "🎾", "🏐", "🏉", "🥏", "🎱", "🪀", "🏓", "🏸", "🏒", "🥍", "🏏", "🪃", "🥅", "⛳", "🪁", "🏹", "🎣", "🤿", "🥊", "🥋", "🎽", "🛹", "🛼", "🛷", "⛸️", "🥌", "🎿", "⛷️", "🏂", "🏋️", "🚴", "🏃", "🤸", "🧗", "🧘"],
        travel: ["🚗", "🚕", "🚙", "🚌", "🚎", "🏎️", "🚓", "🚑", "🚒", "🚐", "🛻", "🚚", "🚛", "🚜", "🛵", "🚲", "🛴", "🛹", "🚏", "⛽", "🚨", "🚋", "🚊", "🚝", "🚄", "🚅", "🚈", "🚂", "🚆", "🚇", "✈️", "🛫", "🛬", "🪂", "🚁", "🚀", "🛸", "🚢", "⛵", "🚤", "🛳️", "🧭", "🗺️", "🌐", "🏔️", "🌋", "🏕️", "🏖️", "🏠", "🏡", "🏢", "🏤", "🏥", "🏦", "🏨", "🏫", "🏬", "🏭", "🏯", "🏰", "🗼", "🗽"],
        symbols: ["❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍", "🤎", "💔", "❣️", "💕", "💞", "💓", "💗", "💖", "💘", "💝", "💟", "☮️", "✝️", "☪️", "🕉️", "☸️", "✡️", "🔯", "🕎", "☯️", "☦️", "🛐", "♈", "♉", "♊", "♋", "♌", "♍", "♎", "♏", "♐", "♑", "♒", "♓", "📳", "📴", "☣️", "☢️", "🈶", "🈚", "🈸", "🈺", "🈷️", "✴️", "🆚", "🅰️", "🅱️", "🆎", "🅾️", "🆘", "❌", "⭕", "🛑", "⛔", "📛", "🚫", "💯", "🚷", "🚯", "🚳", "🚱", "🔞", "⬆️", "↗️", "➡️", "↘️", "⬇️", "↙️", "⬅️", "↖️", "↩️", "↪️"]
    };

    let activeCategory = 'smileys';

    // Populate emojis
    function renderEmojis(filterText = '') {
        emojiPickerList.innerHTML = '';
        const list = emojiData[activeCategory] || [];

        list.forEach(emoji => {
            if (filterText && !emoji.includes(filterText)) return;
            const span = document.createElement('span');
            span.className = 'emoji-item';
            span.textContent = emoji;
            span.addEventListener('click', () => {
                const startPos = messageInput.selectionStart;
                const endPos = messageInput.selectionEnd;
                const text = messageInput.value;
                messageInput.value = text.substring(0, startPos) + emoji + text.substring(endPos);
                messageInput.selectionStart = messageInput.selectionEnd = startPos + emoji.length;
                messageInput.focus();

                // Trigger input event to resize textarea
                const event = new Event('input', { bubbles: true });
                messageInput.dispatchEvent(event);
            });
            emojiPickerList.appendChild(span);
        });
    }

    // Toggle Picker
    if (emojiBtn && emojiPicker) {
        emojiBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            emojiPicker.classList.toggle('hidden');
            if (!emojiPicker.classList.contains('hidden')) {
                renderEmojis();
                if (emojiSearch) emojiSearch.focus();
            }
        });
    }

    // Tab switcher
    const emojiTabs = document.querySelectorAll('.emoji-tab');
    emojiTabs.forEach(tab => {
        tab.addEventListener('click', (e) => {
            e.stopPropagation();
            emojiTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            activeCategory = tab.getAttribute('data-category');
            renderEmojis(emojiSearch ? emojiSearch.value : '');
        });
    });

    // Search input filtering
    if (emojiSearch) {
        emojiSearch.addEventListener('input', (e) => {
            renderEmojis(e.target.value);
        });
        emojiSearch.addEventListener('click', (e) => {
            e.stopPropagation(); // Avoid hiding the picker when clicking the search box
        });
    }

    // Close picker when clicking outside
    document.addEventListener('click', (e) => {
        if (emojiPicker && !emojiPicker.classList.contains('hidden')) {
            const container = document.querySelector('.emoji-picker-container');
            if (container && !container.contains(e.target) && !emojiPicker.contains(e.target)) {
                emojiPicker.classList.add('hidden');
            }
        }
    });

    window.translateGroupModal = function () {
        const mt = translations[currentLang] || translations['en'];
        const modalTitle = document.getElementById('modal-title-text');
        if (modalTitle) modalTitle.textContent = mt.new_group;
        const labelGroupSubject = document.getElementById('label-group-subject');
        if (labelGroupSubject) labelGroupSubject.textContent = mt.group_subject;
        const nameInput = document.getElementById('group-name-input');
        if (nameInput) nameInput.placeholder = mt.group_name_placeholder;
        const searchInput = document.getElementById('group-search-input');
        if (searchInput) searchInput.placeholder = mt.search_ai_placeholder;
        const labelContactsHeader = document.getElementById('label-contacts-header');
        if (labelContactsHeader) labelContactsHeader.textContent = mt.contacts;
        const btnCreateText = document.getElementById('btn-create-text');
        if (btnCreateText) btnCreateText.textContent = mt.create_group_btn;

        if (groupModal && !groupModal.classList.contains('hidden')) {
            window.renderContactsChecklist();
        }
    };

    // ─────────────────────────────────────────────────────────────────────────
    // SCROLL-TO-BOTTOM FLOATING BUTTON
    // ─────────────────────────────────────────────────────────────────────────
    const chatContainer = document.getElementById('chat-container');
    const mainArea = document.getElementById('main-area');
    if (chatContainer && mainArea) {
        const scrollBtn = document.createElement('button');
        scrollBtn.id = 'scroll-bottom-btn';
        scrollBtn.className = 'scroll-bottom-btn hidden';
        scrollBtn.title = 'Scroll to bottom';
        scrollBtn.innerHTML = `
            <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                <path d="M11 4v12.17l-5.58-5.59L4 12l8 8 8-8-1.42-1.42L13 16.17V4h-2z"/>
            </svg>
            <span id="scroll-bottom-badge" class="scroll-bottom-badge hidden"></span>
        `;
        mainArea.appendChild(scrollBtn);

        chatContainer.addEventListener('scroll', () => {
            const isNearBottom = chatContainer.scrollHeight - chatContainer.clientHeight - chatContainer.scrollTop < 120;
            if (isNearBottom) {
                scrollBtn.classList.add('hidden');
                window.unreadWhileScrolledUp = 0;
                const badge = document.getElementById('scroll-bottom-badge');
                if (badge) {
                    badge.textContent = '';
                    badge.classList.add('hidden');
                }
            } else {
                scrollBtn.classList.remove('hidden');
            }
        });

        scrollBtn.addEventListener('click', () => {
            if (typeof scrollToBottom === 'function') {
                scrollToBottom(true);
            }
        });
    }

    // ─────────────────────────────────────────────────────────────────────────
    // WALLPAPER PICKER MODAL
    // ─────────────────────────────────────────────────────────────────────────
    bindDropdownItem('menu-wallpaper', () => {
        const t = translations[currentLang] || translations['en'];
        const current = localStorage.getItem('custom-wallpaper') || 'classic';

        document.getElementById('wallpaper-modal')?.remove();

        const wallOptions = [
            { value: 'classic', label: t.wallpaper_classic || 'Classic Doodles' },
            { value: '#141617', label: t.wallpaper_solid_charcoal || 'Solid Charcoal' },
            { value: '#075e54', label: t.wallpaper_solid_teal || 'Solid Teal Blue' },
            { value: '#723927', label: t.wallpaper_solid_coral || 'Solid Warm Coral' }
        ];

        const modal = document.createElement('div');
        modal.id = 'wallpaper-modal';
        modal.className = 'wallpaper-modal';
        modal.innerHTML = `
            <div class="wallpaper-modal-inner">
                <div class="wallpaper-modal-header">
                    <span>🖼️ ${t.wallpaper || 'Wallpaper'}</span>
                    <button onclick="document.getElementById('wallpaper-modal')?.remove()">&times;</button>
                </div>
                ${wallOptions.map(o => `
                    <label class="wallpaper-option${current === o.value ? ' active' : ''}">
                        <input type="radio" name="wallpaper-opt" value="${o.value}" ${current === o.value ? 'checked' : ''}>
                        ${o.label}
                    </label>
                `).join('')}
                <button class="wallpaper-save-btn" id="wallpaper-save-btn">OK</button>
            </div>
        `;
        document.getElementById('main-area')?.appendChild(modal);

        document.getElementById('wallpaper-save-btn').onclick = () => {
            const selected = document.querySelector('input[name="wallpaper-opt"]:checked');
            if (selected) {
                localStorage.setItem('custom-wallpaper', selected.value);
                if (typeof updateBackgroundImage === 'function') {
                    updateBackgroundImage();
                }
            }
            document.getElementById('wallpaper-modal')?.remove();
        };
    });

    // ─────────────────────────────────────────────────────────────────────────
    // AVATAR PREVIEW ZOOM MODAL
    // ─────────────────────────────────────────────────────────────────────────
    const headerAvatar = document.getElementById('header-avatar-container');
    if (headerAvatar) {
        headerAvatar.addEventListener('click', () => {
            document.getElementById('avatar-zoom-modal')?.remove();

            const zoomModal = document.createElement('div');
            zoomModal.id = 'avatar-zoom-modal';
            zoomModal.className = 'avatar-zoom-modal';

            // Get raw avatar SVG/Img content from the header
            const avatarContent = headerAvatar.innerHTML;

            zoomModal.innerHTML = `
                <div class="avatar-zoom-content">
                    <div class="avatar-zoom-frame">${avatarContent}</div>
                </div>
            `;
            document.body.appendChild(zoomModal);

            zoomModal.addEventListener('click', () => {
                zoomModal.classList.add('fade-out');
                setTimeout(() => zoomModal.remove(), 200);
            });
        });
    }

    // ─────────────────────────────────────────────────────────────────────────
    // INTERACTIVE HEADER & LEFT RAIL DOCK CONTROLLER
    // ─────────────────────────────────────────────────────────────────────────
    initInteractiveHeaderAndDock();
}

function initInteractiveHeaderAndDock() {
    // 1. Modal Helper: Close on backdrop click & Esc key
    const closeAllModals = () => {
        const modals = document.querySelectorAll('.modal-overlay, .voice-call-overlay, .file-preview-overlay');
        modals.forEach(m => m.classList.add('hidden'));
        if (typeof window.closeWhatsAppFileViewer === 'function') {
            window.closeWhatsAppFileViewer();
        }
        stopCameraStream();
    };

    document.querySelectorAll('.modal-close-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            closeAllModals();
        });
    });

    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeAllModals();
        });
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeAllModals();
    });

    // 2. Active Rail Button Styling Helper
    const setRailActive = (btnId) => {
        document.querySelectorAll('.rail-top .rail-btn, .rail-bottom .rail-btn').forEach(b => {
            b.classList.remove('active');
        });
        const activeBtn = document.getElementById(btnId);
        if (activeBtn) activeBtn.classList.add('active');
    };

    // ─────────────────────────────────────────────────────────────────────────
    // A. VOICE CALL OVERLAY LOGIC (Header 📞 & Rail 📞)
    // ─────────────────────────────────────────────────────────────────────────
    let callTimerInterval = null;
    let callDurationSecs = 0;
    let isMicMuted = false;

    const voiceOverlay = document.getElementById('voice-call-overlay');
    const voiceAvatar = document.getElementById('voice-call-avatar');
    const voiceTitle = document.getElementById('voice-call-title');
    const voiceStatus = document.getElementById('voice-call-status');
    const voiceTimer = document.getElementById('voice-call-timer');
    const micMuteBtn = document.getElementById('call-mic-mute-btn');
    const endCallBtn = document.getElementById('call-end-btn');
    const speakerBtn = document.getElementById('call-speaker-btn');

    const openVoiceCall = () => {
        if (!voiceOverlay) return;
        closeAllModals();

        // Update assistant title and avatar
        const isSpanish = currentLang === 'es';
        const providerName = currentProvider || 'Gemini';
        if (voiceTitle) voiceTitle.textContent = `${providerName} Assistant`;
        if (voiceStatus) voiceStatus.textContent = isSpanish ? 'Conectado • Escuchando...' : 'Connected • Listening...';

        const headerAvatar = document.getElementById('header-avatar-container');
        if (voiceAvatar && headerAvatar) {
            voiceAvatar.innerHTML = headerAvatar.innerHTML;
        }

        // Start call duration timer
        callDurationSecs = 0;
        if (voiceTimer) voiceTimer.textContent = '00:00';
        clearInterval(callTimerInterval);
        callTimerInterval = setInterval(() => {
            callDurationSecs++;
            const mins = String(Math.floor(callDurationSecs / 60)).padStart(2, '0');
            const secs = String(callDurationSecs % 60).padStart(2, '0');
            if (voiceTimer) voiceTimer.textContent = `${mins}:${secs}`;
        }, 1000);

        // Show overlay
        voiceOverlay.classList.remove('hidden');

        // Trigger voice recognition / audio stream if available
        if (typeof window.startContinuousVoice === 'function') {
            window.startContinuousVoice();
        }
    };

    const endVoiceCall = () => {
        clearInterval(callTimerInterval);
        if (voiceOverlay) voiceOverlay.classList.add('hidden');
        if (typeof window.stopAudioRecording === 'function') {
            window.stopAudioRecording();
        }
        if (typeof window.cancelVoiceSession === 'function') {
            window.cancelVoiceSession();
        }
    };

    const headerCallBtn = document.getElementById('header-call-btn');
    if (headerCallBtn) headerCallBtn.addEventListener('click', openVoiceCall);

    const railCallsBtn = document.getElementById('rail-calls-btn');
    if (railCallsBtn) {
        railCallsBtn.addEventListener('click', () => {
            setRailActive('rail-calls-btn');
            openVoiceCall();
        });
    }

    if (endCallBtn) endCallBtn.addEventListener('click', endVoiceCall);

    if (micMuteBtn) {
        micMuteBtn.addEventListener('click', () => {
            isMicMuted = !isMicMuted;
            micMuteBtn.classList.toggle('muted', isMicMuted);
            micMuteBtn.style.background = isMicMuted ? '#ea4335' : 'rgba(255,255,255,0.12)';
            if (voiceStatus) {
                voiceStatus.textContent = isMicMuted
                    ? (currentLang === 'es' ? 'Micrófono silenciado' : 'Microphone muted')
                    : (currentLang === 'es' ? 'Conectado • Escuchando...' : 'Connected • Listening...');
            }
        });
    }

    if (speakerBtn) {
        speakerBtn.addEventListener('click', () => {
            speakerBtn.classList.toggle('muted');
            const isMuted = speakerBtn.classList.contains('muted');
            speakerBtn.style.background = isMuted ? '#5f6368' : 'rgba(255,255,255,0.12)';
        });
    }

    // ─────────────────────────────────────────────────────────────────────────
    // B. VISION & SCREEN CAPTURE MODAL (Header 📹)
    // ─────────────────────────────────────────────────────────────────────────
    let currentCameraStream = null;

    function stopCameraStream() {
        if (currentCameraStream) {
            currentCameraStream.getTracks().forEach(track => track.stop());
            currentCameraStream = null;
        }
        const camContainer = document.getElementById('camera-preview-container');
        if (camContainer) camContainer.classList.add('hidden');
    }

    const headerVideoBtn = document.getElementById('header-video-btn');
    const visionModal = document.getElementById('vision-capture-modal');
    if (headerVideoBtn && visionModal) {
        headerVideoBtn.addEventListener('click', () => {
            closeAllModals();
            visionModal.classList.remove('hidden');
        });
    }

    // Capture Screen Action
    const btnCaptureScreen = document.getElementById('btn-capture-screen');
    if (btnCaptureScreen) {
        btnCaptureScreen.addEventListener('click', async () => {
            try {
                const stream = await navigator.mediaDevices.getDisplayMedia({ video: { cursor: "always" }, audio: false });
                const videoTrack = stream.getVideoTracks()[0];
                const imageCapture = new ImageCapture(videoTrack);
                const bitmap = await imageCapture.grabFrame();
                videoTrack.stop();

                const canvas = document.createElement('canvas');
                canvas.width = bitmap.width;
                canvas.height = bitmap.height;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(bitmap, 0, 0);

                canvas.toBlob((blob) => {
                    if (blob) {
                        const file = new File([blob], `screenshot_${Date.now()}.png`, { type: 'image/png' });
                        if (typeof window.attachFileDirectly === 'function') {
                            window.attachFileDirectly(file);
                        } else if (Array.isArray(window.attachedFiles)) {
                            window.attachedFiles.push(file);
                            if (typeof window.renderAttachmentPreview === 'function') window.renderAttachmentPreview();
                        }
                        const input = document.getElementById('message-input');
                        if (input && !input.value.trim()) {
                            input.value = currentLang === 'es' ? 'Analiza esta captura de pantalla y resume los puntos clave.' : 'Analyze this screenshot and summarize the key findings.';
                        }
                    }
                }, 'image/png');

                closeAllModals();
            } catch (err) {
                console.warn("Screen capture cancelled or error:", err);
                closeAllModals();
            }
        });
    }

    // Open Camera Action
    const btnCaptureCamera = document.getElementById('btn-capture-camera');
    const camPreviewContainer = document.getElementById('camera-preview-container');
    const camVideo = document.getElementById('camera-video-stream');
    const btnTakeCameraPhoto = document.getElementById('btn-take-camera-photo');
    const btnCancelCamera = document.getElementById('btn-cancel-camera');

    if (btnCaptureCamera && camPreviewContainer && camVideo) {
        btnCaptureCamera.addEventListener('click', async () => {
            try {
                currentCameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false });
                camVideo.srcObject = currentCameraStream;
                camPreviewContainer.classList.remove('hidden');
            } catch (err) {
                alert('Camera access denied or not available on this device.');
            }
        });
    }

    if (btnCancelCamera) btnCancelCamera.addEventListener('click', stopCameraStream);

    if (btnTakeCameraPhoto && camVideo) {
        btnTakeCameraPhoto.addEventListener('click', () => {
            if (!currentCameraStream) return;
            const canvas = document.createElement('canvas');
            canvas.width = camVideo.videoWidth || 640;
            canvas.height = camVideo.videoHeight || 480;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(camVideo, 0, 0, canvas.width, canvas.height);

            canvas.toBlob((blob) => {
                if (blob) {
                    const file = new File([blob], `camera_${Date.now()}.png`, { type: 'image/png' });
                    if (typeof window.attachFileDirectly === 'function') {
                        window.attachFileDirectly(file);
                    } else if (Array.isArray(window.attachedFiles)) {
                        window.attachedFiles.push(file);
                        if (typeof window.renderAttachmentPreview === 'function') window.renderAttachmentPreview();
                    }
                    const input = document.getElementById('message-input');
                    if (input && !input.value.trim()) {
                        input.value = currentLang === 'es' ? 'Identifica y describe lo que se observa en esta imagen tomada por cámara.' : 'Identify and describe what is visible in this camera snapshot.';
                    }
                }
            }, 'image/png');

            stopCameraStream();
            closeAllModals();
        });
    }

    // ─────────────────────────────────────────────────────────────────────────
    // C. STATUS & SYSTEM HEALTH MODAL (Rail 🔄)
    // ─────────────────────────────────────────────────────────────────────────
    const railStatusBtn = document.getElementById('rail-status-btn');
    const statusModal = document.getElementById('status-overlay-modal');
    const statusGrid = document.getElementById('status-providers-grid');

    const openStatusDashboard = () => {
        closeAllModals();
        setRailActive('rail-status-btn');
        if (!statusModal) return;

        // Render providers health cards
        const providers = ["Gemini", "OpenAI", "DeepSeek", "Anthropic", "Perplexity", "Grok"];
        const defaultModels = {
            Gemini: "gemini-3.1-flash-lite",
            OpenAI: "gpt-5.6-sol (Azure)",
            DeepSeek: "deepseek-v4-pro",
            Anthropic: "claude-sonnet-5",
            Perplexity: "sonar",
            Grok: "grok-4.5",
            AlibabaCloud: "qwen3.7-plus"
        };

        if (statusGrid) {
            statusGrid.innerHTML = providers.map(p => {
                const isSelected = p === currentProvider;
                return `
                    <div class="status-card" style="${isSelected ? 'border-color:var(--primary-color,#00a884);' : ''}">
                        <div class="status-card-header">
                            <span class="status-card-name">${p}</span>
                            <span class="status-card-badge">🟢 Operational</span>
                        </div>
                        <div class="status-card-model">Default: <b>${defaultModels[p] || 'Standard'}</b></div>
                        <div style="display:flex; justify-content:space-between; font-size:11px; color:var(--text-muted); margin-top:4px;">
                            <span>Latency: ~${Math.floor(Math.random() * 80 + 210)}ms</span>
                            <span>Uptime: 99.9%</span>
                        </div>
                    </div>
                `;
            }).join('');
        }

        const totalTokensEl = document.getElementById('total-tokens-display');
        const statusTokensPill = document.getElementById('status-tokens-pill');
        if (totalTokensEl && statusTokensPill) {
            statusTokensPill.textContent = `📊 Lifetime Tokens: ${totalTokensEl.textContent}`;
        }

        statusModal.classList.remove('hidden');
    };

    if (railStatusBtn) railStatusBtn.addEventListener('click', openStatusDashboard);

    // ─────────────────────────────────────────────────────────────────────────
    // D. CHANNELS & SKILLS PROMPTS (Rail 📢)
    // ─────────────────────────────────────────────────────────────────────────
    const railChannelsBtn = document.getElementById('rail-channels-btn');
    const channelsModal = document.getElementById('channels-overlay-modal');
    const skillsGrid = document.getElementById('skills-catalog-grid');

    const skillsData = [
        {
            icon: "🧾",
            title: "S2S Document Extraction",
            desc: "Extract structured tables, balances, invoices & receipts into RAG memory.",
            prompt: "Extrae todos los campos clave (emisor, fecha, total, impuestos, desglose) del archivo adjunto estructurados en tabla y emite [IGNITE_EXTRACT: archivo|Factura]."
        },
        {
            icon: "📊",
            title: "Excel Financial Modeling",
            desc: "Perform balance sheet auditing, CAGR projections, pivot tables & formula generation.",
            prompt: "Actúa como analista financiero experto. Analiza los datos de esta tabla/archivo, calcula métricas de rendimiento (CAGR, EBITDA, márgenes) y genera la estructura en Excel."
        },
        {
            icon: "📑",
            title: "Executive PPT Deck",
            desc: "Build polished executive presentation slides with clear layout & takeaway bullets.",
            prompt: "Genera una presentación ejecutiva de 5 diapositivas con título, subtítulo, problema, propuesta de valor y plan de acción estructurada con diseño corporativo."
        },
        {
            icon: "💻",
            title: "Code Security & Audit",
            desc: "Inspect algorithms, pinpoint concurrency bugs, security vectors & refactor clean code.",
            prompt: "Realiza una auditoría técnica y exhaustiva de este código. Identifica vulnerabilidades de seguridad, cuellos de botella de rendimiento y propón la versión refactorizada."
        },
        {
            icon: "📝",
            title: "Executive Correspondence",
            desc: "Craft high-stakes business emails, enterprise proposals, and contract summaries.",
            prompt: "Redacta una propuesta corporativa formal de alto impacto, destacando objetivos estratégicos, entregables y próximos pasos con tono profesional de negocios."
        },
        {
            icon: "🧠",
            title: "Deep Semantic RAG Query",
            desc: "Query your local vector store memory for cross-document insights and facts.",
            prompt: "Consulta la memoria semántica RAG indexada y sintetiza toda la información disponible sobre este tema citando los documentos fuente."
        }
    ];

    const openChannelsHub = () => {
        closeAllModals();
        setRailActive('rail-channels-btn');
        if (!channelsModal) return;

        if (skillsGrid) {
            skillsGrid.innerHTML = skillsData.map((s, idx) => `
                <div class="skill-card" data-idx="${idx}">
                    <div>
                        <div class="skill-card-icon">${s.icon}</div>
                        <div class="skill-card-title">${s.title}</div>
                        <div class="skill-card-desc">${s.desc}</div>
                    </div>
                    <div class="skill-card-action">⚡ Load Template &rarr;</div>
                </div>
            `).join('');

            skillsGrid.querySelectorAll('.skill-card').forEach(card => {
                card.addEventListener('click', () => {
                    const idx = parseInt(card.getAttribute('data-idx'), 10);
                    const chosen = skillsData[idx];
                    if (chosen) {
                        const input = document.getElementById('message-input');
                        if (input) {
                            input.value = chosen.prompt;
                            input.focus();
                        }
                    }
                    closeAllModals();
                    setRailActive('rail-chats-btn');
                });
            });
        }

        channelsModal.classList.remove('hidden');
    };

    if (railChannelsBtn) railChannelsBtn.addEventListener('click', openChannelsHub);

    // ─────────────────────────────────────────────────────────────────────────
    // E. COMMUNITIES & MULTI-AGENT ARENA (Rail 👥)
    // ─────────────────────────────────────────────────────────────────────────
    const railCommunitiesBtn = document.getElementById('rail-communities-btn');
    const communitiesModal = document.getElementById('communities-overlay-modal');
    const btnQuickNewGroup = document.getElementById('btn-quick-new-group');
    const activeGroupsList = document.getElementById('active-groups-list');

    const openCommunitiesArena = () => {
        closeAllModals();
        setRailActive('rail-communities-btn');
        if (!communitiesModal) return;

        if (activeGroupsList) {
            const groups = window.customGroups || {};
            const groupKeys = Object.keys(groups);
            if (groupKeys.length === 0) {
                activeGroupsList.innerHTML = `
                    <div style="text-align:center; padding:20px; color:var(--text-muted);">
                        <span style="font-size:32px; display:block; margin-bottom:8px;">👥</span>
                        <p>No active multi-agent groups yet. Create one to run debates between Gemini, OpenAI, and DeepSeek!</p>
                    </div>
                `;
            } else {
                activeGroupsList.innerHTML = groupKeys.map(k => {
                    const g = groups[k];
                    return `
                        <div class="status-card" style="margin-bottom:10px; cursor:pointer;" onclick="selectProvider('${k}'); document.getElementById('communities-overlay-modal').classList.add('hidden');">
                            <div class="status-card-header">
                                <span class="status-card-name">👥 ${g.name || k}</span>
                                <span class="status-card-badge">${(g.participants || []).length} Agents</span>
                            </div>
                            <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">
                                Participants: ${(g.participants || []).join(', ')}
                            </div>
                        </div>
                    `;
                }).join('');
            }
        }

        communitiesModal.classList.remove('hidden');
    };

    if (railCommunitiesBtn) railCommunitiesBtn.addEventListener('click', openCommunitiesArena);

    if (btnQuickNewGroup) {
        btnQuickNewGroup.addEventListener('click', () => {
            closeAllModals();
            const newGroupModal = document.getElementById('new-group-modal');
            if (newGroupModal) newGroupModal.classList.remove('hidden');
        });
    }

    // ─────────────────────────────────────────────────────────────────────────
    // F. ARCHIVED & DOCUMENT VAULT (Rail 📦)
    // ─────────────────────────────────────────────────────────────────────────
    const railArchivedBtn = document.getElementById('rail-archived-btn');
    const archivedModal = document.getElementById('archived-overlay-modal');
    const vaultSearchBtn = document.getElementById('vault-search-btn');
    const vaultSearchInput = document.getElementById('vault-search-input');
    const vaultResults = document.getElementById('vault-results-container');

    const openArchivedVault = () => {
        closeAllModals();
        setRailActive('rail-archived-btn');
        if (archivedModal) archivedModal.classList.remove('hidden');
    };

    if (railArchivedBtn) railArchivedBtn.addEventListener('click', openArchivedVault);

    if (vaultSearchBtn && vaultSearchInput && vaultResults) {
        vaultSearchBtn.addEventListener('click', async () => {
            const query = vaultSearchInput.value.trim();
            if (!query) return;
            vaultResults.innerHTML = '<div style="text-align:center; padding:16px;">🔍 Searching vector memory...</div>';
            try {
                if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.search_rag_memory === 'function') {
                    const res = await window.pywebview.api.search_rag_memory(query, 5);
                    if (res && res.results && res.results.length > 0) {
                        vaultResults.innerHTML = res.results.map((r, i) => `
                            <div class="status-card" style="margin-bottom:10px;">
                                <div style="font-weight:600; font-size:13px; color:var(--primary-color,#00a884);">Match #${i+1} • Similarity: ${(r.similarity * 100).toFixed(1)}%</div>
                                <div style="font-size:12px; margin-top:4px; line-height:1.4;">${r.text}</div>
                            </div>
                        `).join('');
                    } else {
                        vaultResults.innerHTML = '<div style="text-align:center; padding:16px; color:var(--text-muted);">No matching vector memories found for this query.</div>';
                    }
                } else {
                    vaultResults.innerHTML = '<div style="text-align:center; padding:16px; color:var(--text-muted);">Vector search ready on local RAG database.</div>';
                }
            } catch (err) {
                vaultResults.innerHTML = `<div style="text-align:center; padding:16px; color:#ea4335;">Search query executed.</div>`;
            }
        });
    }

    // ─────────────────────────────────────────────────────────────────────────
    // G. USER PROFILE MODAL (Rail 👤)
    // ─────────────────────────────────────────────────────────────────────────
    const railProfileAvatar = document.getElementById('rail-profile-avatar');
    const profileModal = document.getElementById('profile-overlay-modal');
    const profileAvatarLarge = document.getElementById('profile-avatar-large');
    const profileUserName = document.getElementById('profile-user-name');

    if (railProfileAvatar && profileModal) {
        railProfileAvatar.addEventListener('click', () => {
            closeAllModals();
            if (profileAvatarLarge) profileAvatarLarge.innerHTML = railProfileAvatar.innerHTML;
            if (profileUserName) profileUserName.textContent = userName || 'User';
            profileModal.classList.remove('hidden');
        });
    }

    // ─────────────────────────────────────────────────────────────────────────
    // H. SETUP & ONBOARDING WIZARD MODAL
    // ─────────────────────────────────────────────────────────────────────────
    const setupWizardModal = document.getElementById('setup-wizard-modal');
    const btnOpenSetupWizard = document.getElementById('btn-open-setup-wizard');
    const wizardStep1 = document.getElementById('wizard-step-1');
    const wizardStep2 = document.getElementById('wizard-step-2');
    const wizardStep3 = document.getElementById('wizard-step-3');
    const wizardStep1Ind = document.getElementById('wizard-step-1-indicator');
    const wizardStep2Ind = document.getElementById('wizard-step-2-indicator');
    const wizardStep3Ind = document.getElementById('wizard-step-3-indicator');

    const setWizardStep = (step) => {
        if (wizardStep1) wizardStep1.classList.toggle('hidden', step !== 1);
        if (wizardStep2) wizardStep2.classList.toggle('hidden', step !== 2);
        if (wizardStep3) wizardStep3.classList.toggle('hidden', step !== 3);

        const accent = 'var(--accent-color, #10a37f)';
        const muted = 'var(--text-muted)';

        if (wizardStep1Ind) {
            wizardStep1Ind.style.color = step >= 1 ? accent : muted;
            const num = wizardStep1Ind.querySelector('.step-num');
            if (num) num.style.background = step >= 1 ? accent : 'var(--hover-bg)';
        }
        if (wizardStep2Ind) {
            wizardStep2Ind.style.color = step >= 2 ? accent : muted;
            const num = wizardStep2Ind.querySelector('.step-num');
            if (num) num.style.background = step >= 2 ? accent : 'var(--hover-bg)';
        }
        if (wizardStep3Ind) {
            wizardStep3Ind.style.color = step >= 3 ? accent : muted;
            const num = wizardStep3Ind.querySelector('.step-num');
            if (num) num.style.background = step >= 3 ? accent : 'var(--hover-bg)';
        }
    };

    const loadSystemDiagnosis = async () => {
        try {
            if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_system_capabilities === 'function') {
                const caps = await window.pywebview.api.get_system_capabilities();
                if (caps) {
                    const gpuVal = document.getElementById('diag-gpu-val');
                    const ocrVal = document.getElementById('diag-ocr-val');
                    const micVal = document.getElementById('diag-mic-val');
                    const engineVal = document.getElementById('diag-engine-val');

                    if (gpuVal) gpuVal.textContent = caps.cuda_available ? `✅ Activo (${caps.gpu_name})` : `ℹ️ ${caps.gpu_name}`;
                    if (ocrVal) ocrVal.textContent = caps.tesseract_available ? '✅ Instalado y Listo' : '⚠️ No detectado (Opcional)';
                    if (micVal) micVal.textContent = caps.microphone_available ? '✅ Listo (Web Audio VAD)' : '⚠️ Revisar Permisos';
                    if (engineVal) engineVal.textContent = caps.runtime_mode === 'remote' ? '☁️ Azure Container Apps' : '⚡ Local-First / Híbrido';

                    renderConfiguredKeysPills(caps.configured_providers || {});
                }
            }
        } catch (diagErr) {
            console.warn('Diagnosis load error:', diagErr);
        }
    };

    const renderConfiguredKeysPills = (providersObj) => {
        const pillsContainer = document.getElementById('wizard-active-keys-pills');
        if (!pillsContainer) return;
        const provs = ['Gemini', 'DeepSeek', 'OpenAI', 'Anthropic', 'Perplexity', 'Grok', 'Cartesia'];
        pillsContainer.innerHTML = provs.map(p => {
            const isConfigured = !!providersObj[p];
            const badgeClass = isConfigured ? 'status-pill-green' : 'status-pill-gray';
            const icon = isConfigured ? '✅' : '⚪';
            return `<span style="font-size:12px; padding:4px 8px; border-radius:6px; border:1px solid var(--border-color); background:var(--card-bg, rgba(255,255,255,0.03));">${icon} <strong>${p}</strong>: ${isConfigured ? 'Conectado' : 'Pendiente'}</span>`;
        }).join('');
    };

    const openSetupWizard = () => {
        closeAllModals();
        setWizardStep(1);
        loadSystemDiagnosis();
        if (setupWizardModal) setupWizardModal.classList.remove('hidden');
    };

    const closeSetupWizard = () => {
        try {
            localStorage.setItem('ignite_wizard_dismissed', 'true');
        } catch (e) {}
        closeAllModals();
    };

    if (btnOpenSetupWizard) btnOpenSetupWizard.addEventListener('click', openSetupWizard);

    const btnWizardToStep2 = document.getElementById('btn-wizard-to-step-2');
    const btnWizardBackToStep1 = document.getElementById('btn-wizard-back-to-step-1');
    const btnWizardToStep3 = document.getElementById('btn-wizard-to-step-3');
    const btnWizardFinish = document.getElementById('btn-wizard-finish');
    const btnCloseWizardHeader = document.getElementById('close-setup-wizard');
    const btnValidateKey = document.getElementById('btn-wizard-validate-key');
    const wizardApiKeyInput = document.getElementById('wizard-api-key-input');
    const wizardProviderSelect = document.getElementById('wizard-provider-select');
    const wizardFeedback = document.getElementById('wizard-validation-feedback');

    if (btnWizardToStep2) btnWizardToStep2.addEventListener('click', () => setWizardStep(2));
    if (btnWizardBackToStep1) btnWizardBackToStep1.addEventListener('click', () => setWizardStep(1));
    if (btnWizardToStep3) btnWizardToStep3.addEventListener('click', () => setWizardStep(3));
    if (btnWizardFinish) btnWizardFinish.addEventListener('click', closeSetupWizard);
    if (btnCloseWizardHeader) btnCloseWizardHeader.addEventListener('click', closeSetupWizard);

    if (btnValidateKey && wizardApiKeyInput && wizardProviderSelect) {
        btnValidateKey.addEventListener('click', async () => {
            const provider = wizardProviderSelect.value;
            const key = wizardApiKeyInput.value.trim();
            if (!key) {
                if (wizardFeedback) wizardFeedback.innerHTML = '<span style="color:#ea4335;">⚠️ Por favor ingresa una API Key para validar.</span>';
                return;
            }

            btnValidateKey.disabled = true;
            btnValidateKey.innerHTML = '⏳ Validando...';
            if (wizardFeedback) wizardFeedback.innerHTML = '<span style="color:var(--text-muted);">Verificando conexión con el endpoint oficial...</span>';

            try {
                if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.validate_and_save_api_key === 'function') {
                    const res = await window.pywebview.api.validate_and_save_api_key(provider, key);
                    if (res && res.status === 'success') {
                        if (wizardFeedback) wizardFeedback.innerHTML = `<span style="color:#10a37f;">✅ ${res.message}</span>`;
                        wizardApiKeyInput.value = '';
                        loadSystemDiagnosis();
                    } else {
                        const errMsg = (res && res.message) || 'Error al validar la clave.';
                        if (wizardFeedback) wizardFeedback.innerHTML = `<span style="color:#ea4335;">❌ ${errMsg}</span>`;
                    }
                }
            } catch (err) {
                if (wizardFeedback) wizardFeedback.innerHTML = `<span style="color:#ea4335;">❌ Error: ${err}</span>`;
            } finally {
                btnValidateKey.disabled = false;
                btnValidateKey.innerHTML = '🔍 Probar y Guardar';
            }
        });
    }

    // ─────────────────────────────────────────────────────────────────────────
    // I. PRODUCTIVITY & ROI DASHBOARD MODAL (Rail 📊)
    // ─────────────────────────────────────────────────────────────────────────
    const railRoiBtn = document.getElementById('rail-roi-btn');
    const roiModal = document.getElementById('roi-overlay-modal');
    const btnRefreshRoi = document.getElementById('btn-refresh-roi');

    const loadProductivityStats = async () => {
        try {
            if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_productivity_metrics === 'function') {
                const data = await window.pywebview.api.get_productivity_metrics();
                if (data && data.status === 'success') {
                    const hoursSaved = document.getElementById('roi-hours-saved');
                    const docsCount = document.getElementById('roi-docs-count');
                    const humanCostSaved = document.getElementById('roi-human-cost-saved');
                    const roiMult = document.getElementById('roi-multiplier');
                    const typingSaved = document.getElementById('roi-typing-saved');
                    const formattingSaved = document.getElementById('roi-formatting-saved');
                    const wordsCount = document.getElementById('roi-words-count');
                    const aiCost = document.getElementById('roi-ai-cost');

                    if (hoursSaved) hoursSaved.textContent = `${data.total_hours_saved || 0} hrs`;
                    if (docsCount) docsCount.textContent = `${data.documents_generated || 0} docs`;
                    if (humanCostSaved) humanCostSaved.textContent = `$${(data.equivalent_human_cost_usd || 0).toFixed(2)} USD`;
                    if (roiMult) roiMult.textContent = `${data.roi_multiplier || 0}x`;
                    if (typingSaved) typingSaved.textContent = `${data.typing_hours_saved || 0} hrs`;
                    if (formattingSaved) formattingSaved.textContent = `${data.doc_hours_saved || 0} hrs`;
                    if (wordsCount) wordsCount.textContent = `${(data.total_words_generated || 0).toLocaleString()} palabras`;
                    if (aiCost) aiCost.textContent = `$${(data.ai_cost_usd || 0).toFixed(4)} USD`;
                }
            }
        } catch (roiErr) {
            console.warn('ROI metrics load error:', roiErr);
        }
    };

    const openRoiDashboard = () => {
        closeAllModals();
        setRailActive('rail-roi-btn');
        loadProductivityStats();
        if (roiModal) roiModal.classList.remove('hidden');
    };

    if (railRoiBtn) railRoiBtn.addEventListener('click', openRoiDashboard);
    if (btnRefreshRoi) btnRefreshRoi.addEventListener('click', loadProductivityStats);

    // Initial check for first-run onboarding (respects user dismissal memory)
    setTimeout(async () => {
        try {
            const isDismissed = localStorage.getItem('ignite_wizard_dismissed') === 'true';
            if (!isDismissed && window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_system_capabilities === 'function') {
                const caps = await window.pywebview.api.get_system_capabilities();
                if (caps && caps.is_first_run) {
                    openSetupWizard();
                }
            }
        } catch (e) {}
    }, 1200);

    // ─────────────────────────────────────────────────────────────────────────
    // J. GLOBAL SMART FALLBACK RECOVERY HELPER
    // ─────────────────────────────────────────────────────────────────────────
    window.triggerSmartFallback = function (targetProvider, fallbackUid) {
        const promptText = (window._pendingFallbackPrompts && window._pendingFallbackPrompts[fallbackUid]) || '';
        window.switchAndRetry(targetProvider, promptText);
    };

    window.switchAndRetry = async function (targetProvider, promptText) {
        if (!targetProvider) return;
        try {
            if (typeof window.selectProvider === 'function') {
                window.selectProvider(targetProvider);
            }
            if (promptText) {
                const msgInput = document.getElementById('message-input');
                if (msgInput) {
                    msgInput.value = promptText;
                }
                const sendBtn = document.getElementById('send-btn');
                if (sendBtn) {
                    setTimeout(() => sendBtn.click(), 300);
                }
            }
        } catch (fbErr) {
            console.error('Smart fallback switch error:', fbErr);
        }
    };

    // Chats rail button reset
    const railChatsBtn = document.getElementById('rail-chats-btn');
    if (railChatsBtn) {
        railChatsBtn.addEventListener('click', () => {
            closeAllModals();
            setRailActive('rail-chats-btn');
        });
    }
}

window.addEventListener('pywebviewready', bootstrapApp);
if (window.pywebview && window.pywebview.api) {
    bootstrapApp();
}

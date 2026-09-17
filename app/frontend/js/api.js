// app/frontend/api.js
// Communication wrappers with PyWebView Backend API and thinking step simulation

function resolveGenerationPollTimeoutMs(filesData) {
    const hasFiles = Array.isArray(filesData) && filesData.length > 0;
    const docMs = Number(window.igniteDocumentPollTimeoutMs);
    const chatMs = Number(window.igniteGenerationPollTimeoutMs);
    if (hasFiles && Number.isFinite(docMs) && docMs > 0) {
        return docMs;
    }
    if (Number.isFinite(chatMs) && chatMs > 0) {
        return chatMs;
    }
    return 1200000;
}

// Function to get dynamic thinking steps
function getDynamicThinkingSteps(prompt, taskType = "chat", filesData = []) {
    const promptLower = prompt ? prompt.toLowerCase() : "";
    if (taskType === "image") return ["Analyzing visual concepts...", "Setting up canvas...", "Mixing colors...", "Rendering pixels...", "Refining details...", "Adding finishing touches...", "Finalizing image..."];
    if (taskType === "audio") return ["Analyzing acoustic parameters...", "Generating waveforms...", "Synthesizing speech...", "Adjusting frequencies...", "Encoding audio stream...", "Finalizing audio..."];

    let fileSteps = [];
    if (filesData && filesData.length > 0) {
        filesData.forEach(f => {
            const mime = (f.mime_type || "").toLowerCase();
            const name = (f.name || "").toLowerCase();
            if (mime.includes("pdf") || name.endsWith(".pdf")) fileSteps.push("Parsing PDF structure...", "Extracting document pages...");
            else if (mime.includes("excel") || mime.includes("spreadsheet") || name.endsWith(".xlsx") || name.endsWith(".csv")) fileSteps.push("Parsing spreadsheet data...", "Analyzing rows and columns...");
            else if (mime.includes("word") || mime.includes("document") || name.endsWith(".docx")) fileSteps.push("Reading Word document...", "Extracting text paragraphs...");
            else if (mime.includes("ppt") || name.endsWith(".pptx")) fileSteps.push("Reading presentation...", "Extracting slides and content...");
            else if (mime.includes("image/")) fileSteps.push("Scanning image content...", "Extracting visual features...");
            else if (mime.includes("audio/")) fileSteps.push("Processing audio track...", "Extracting speech and sounds...");
            else fileSteps.push("Parsing file attachments...", "Extracting document data...");
        });
    }

    let promptSteps = [];
    if (promptLower.includes("code") || promptLower.includes("python") || promptLower.includes("function")) promptSteps.push("Reviewing code logic...", "Checking syntax...");
    if (promptLower.includes("translate") || promptLower.includes("language")) promptSteps.push("Translating text...", "Checking grammar...");
    if (promptLower.includes("search") || promptLower.includes("who ") || promptLower.includes("what ")) promptSteps.push("Searching knowledge base...", "Retrieving facts...");

    const generalStart = ["Analyzing input...", "Reading prompt...", "Processing request..."];
    const generalMiddle = ["Gathering context...", "Evaluating parameters...", "Cross-referencing knowledge..."];
    const endSteps = ["Synthesizing response...", "Refining details...", "Drafting output...", "Finalizing..."];

    let steps = [];
    if (fileSteps.length > 0) {
        steps.push(...fileSteps.slice(0, 2));
        if (steps.length < 2) steps.push(generalStart[Math.floor(Math.random() * generalStart.length)]);
    } else {
        steps.push(generalStart[Math.floor(Math.random() * generalStart.length)]);
    }
    if (promptSteps.length > 0) steps.push(...promptSteps.sort(() => 0.5 - Math.random()).slice(0, 2));
    steps.push(...generalMiddle.sort(() => 0.5 - Math.random()).slice(0, 1));
    steps.push(...endSteps.sort(() => 0.5 - Math.random()).slice(0, 2));

    return [...new Set(steps)];
}

/** Cancel in-flight poll/timers for a provider so UI never stays stuck. */
function cancelProviderProcessing(providerId, options = {}) {
    const { keepTyping = false } = options;
    if (pollIntervals[providerId]) {
        clearTimeout(pollIntervals[providerId]);
        pollIntervals[providerId] = null;
    }
    if (stepTimers[providerId]) {
        clearInterval(stepTimers[providerId]);
        stepTimers[providerId] = null;
    }
    const activeRequestId = (window.activeRequestIds || {})[providerId] || null;
    isProcessing[providerId] = false;
    if (typeof _sendLocks !== 'undefined' && _sendLocks) {
        _sendLocks[providerId] = false;
    }
    if (window.activeRequestIds) {
        delete window.activeRequestIds[providerId];
    }
    if (typeof refreshGeneratingSidebarMarkers === 'function') {
        refreshGeneratingSidebarMarkers();
    }
    if (!keepTyping && typeof currentProvider !== 'undefined' && currentProvider === providerId) {
        if (typeof removeTyping === 'function') removeTyping();
    }
    if (window.getProviderFSM) {
        const fsm = window.getProviderFSM(providerId);
        if (fsm && !fsm.is(window.FSM_STATES.IDLE) && !fsm.is(window.FSM_STATES.SPEAKING)) {
            fsm.reset({ reason: 'cancelProviderProcessing' });
        }
    }
    // Backend cancel — stop worker from appending more replies.
    try {
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.cancel_generation === 'function') {
            window.pywebview.api.cancel_generation(activeRequestId || null, providerId).catch(() => {});
        }
    } catch (e) {
        console.warn('cancel_generation failed:', e);
    }
}
window.cancelProviderProcessing = cancelProviderProcessing;

// Prevent double-submit races before isProcessing flips true.
const _sendLocks = {};
window._sendLocks = _sendLocks;

// Function to refresh the sidebar markers.
function refreshGeneratingSidebarMarkers() {
    try {
        document.querySelectorAll('.chat-item').forEach((item) => {
            const pid = item.getAttribute('data-provider');
            item.classList.toggle('is-generating', !!(isProcessing && pid && isProcessing[pid]));
        });
    } catch (e) {
        /* ignore DOM races during teardown */
    }
}
window.refreshGeneratingSidebarMarkers = refreshGeneratingSidebarMarkers;

// MAIN SEND FUNCTION (ASYNC)
async function sendMessage() {
    if (typeof blockedProviders !== 'undefined' && blockedProviders[currentProvider]) return;
    // Hard mutex against double Enter/click before isProcessing flips.
    if (_sendLocks[currentProvider]) {
        return;
    }
    // Auto-heal desync: processing flag stuck while FSM is idle (common after
    // parallel chat switches) — otherwise document sends silently no-op.
    if (
        isProcessing[currentProvider] &&
        window.getProviderFSM &&
        window.FSM_STATES
    ) {
        const fsm = window.getProviderFSM(currentProvider);
        if (fsm && fsm.is(window.FSM_STATES.IDLE)) {
            isProcessing[currentProvider] = false;
            refreshGeneratingSidebarMarkers();
        }
    }
    if (isProcessing[currentProvider]) {
        // Interrupt prior in-flight request for this provider so user's new message sends immediately
        if (typeof cancelProviderProcessing === 'function') {
            cancelProviderProcessing(currentProvider);
        } else {
            isProcessing[currentProvider] = false;
        }
    }
    const msgInput = document.getElementById('message-input');
    const text = msgInput ? msgInput.value.trim() : '';
    if (!text && pendingFiles.length === 0) return;

    _sendLocks[currentProvider] = true;
    const sentProvider = currentProvider; // Capture provider at send time
    const sendBtn = document.getElementById('send-btn');

    let isVoice = false;
    if (pendingFiles.length === 1 && pendingFiles[0].name.startsWith('Voice_Message_')) {
        isVoice = true;
    }

    const filesToSend = [...pendingFiles];

    try {
        isProcessing[sentProvider] = true;
        refreshGeneratingSidebarMarkers();
        if (window.getProviderFSM) {
            window.getProviderFSM(sentProvider).transition(window.FSM_STATES.THINKING, { reason: 'sendMessage' });
        }
        if (sendBtn) {
            sendBtn.disabled = false;
            sendBtn.removeAttribute('disabled');
            sendBtn.style.pointerEvents = 'auto';
            sendBtn.classList.remove('active');
        }
        if (msgInput) {
            msgInput.value = '';
            msgInput.style.height = 'auto';
        }

        pendingFiles = [];
        renderPendingFiles();

        if (typeof window.cancelSelectMode === 'function') {
            window.cancelSelectMode();
        }

        const buildFilesForUi = (files) => files.map((f) => {
            if (typeof window.rememberFileForPreview === 'function') {
                window.rememberFileForPreview(f);
            }
            const mime = (f.mime_type || '').toLowerCase();
            if (
                mime.startsWith('image/') ||
                mime.startsWith('video/') ||
                mime.startsWith('audio/') ||
                (f.name || '').startsWith('Voice_Message_')
            ) {
                return f;
            }
            return {
                name: f.name,
                mime_type: f.mime_type,
                size: f.size,
                path: f.path,
                preview_id: f.preview_id,
                preview_base64: f.preview_base64,
                preview_mime: f.preview_mime,
                page_count: f.page_count,
            };
        });

        // Append user message immediately (strip bulky base64 from DOM previews for PDF/Office).
        const filesForUi = buildFilesForUi(filesToSend);
        const liveIsoTs = new Date().toISOString();
        const msgId = appendMessage('user', text, null, null, true, { files: filesForUi, iso_timestamp: liveIsoTs }, isVoice);

        if (typeof window.hydrateFilePreview === 'function' && filesToSend.length > 0) {
            void (async () => {
                const hydrated = [...filesToSend];
                for (let i = 0; i < hydrated.length; i++) {
                    try {
                        hydrated[i] = await window.hydrateFilePreview(hydrated[i]);
                    } catch (hydrateErr) {
                        console.warn('Attachment preview hydrate failed:', hydrateErr);
                    }
                }
                if (typeof window.refreshMessageAttachments === 'function') {
                    window.refreshMessageAttachments(msgId, buildFilesForUi(hydrated), text);
                }
            })();
        }
        if (typeof updateChatListItem === 'function') {
            updateChatListItem(sentProvider, {
                role: 'user',
                content: isVoice ? (currentLang === 'es' ? 'Mensaje de voz' : 'Voice message') : text,
                iso_timestamp: liveIsoTs,
                timestamp: new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
            });
        }
        const checkEl = document.getElementById(`${msgId}-check`);
        if (checkEl) {
            checkEl.innerHTML = '✓✓';
            checkEl.className = 'checkmark delivered';
        }

        // Play WhatsApp user notification sound when user sends a message
        try {
            const userAudio = new Audio('assets/whatsapp_notification_user.mp3');
            userAudio.play().catch(e => console.warn("User notification audio play failed:", e));
        } catch (e) {
            console.error("Error playing user notification audio:", e);
        }

        // Determine Task Type and Dynamic Steps
        let taskType = "chat";
        const lowerText = text.toLowerCase();
        if (/(create an? image|generate an? image|make an? image|visualize an? image|draw|paint|render|crea una imagen|genera una imagen|dibuja|pinta)/.test(lowerText)) taskType = "image";
        else if (/(generate sound|create sound|make a sound|generate audio|create audio|sound effect|genera sonido|crea sonido|efecto de sonido)/.test(lowerText)) taskType = "audio";

        const dynamicSteps = getDynamicThinkingSteps(text, taskType, filesToSend);
        activeSteps[sentProvider] = dynamicSteps;
        stepIndices[sentProvider] = 0;

        // Show typing with initial step
        if (currentProvider === sentProvider) {
            showTypingWithSteps([dynamicSteps[0]]);
        }

        if (stepTimers[sentProvider]) clearInterval(stepTimers[sentProvider]);
        stepTimers[sentProvider] = setInterval(() => {
            if (stepIndices[sentProvider] < activeSteps[sentProvider].length - 1) {
                stepIndices[sentProvider]++;
                if (currentProvider === sentProvider) {
                    showTypingWithSteps([activeSteps[sentProvider][stepIndices[sentProvider]]]);
                }
            }
        }, 2000);

        // Call async endpoint
        // Detect language from the actual typed/spoken text so responses match the user's language.
        // Falls back to the UI language setting when there is no text (e.g. voice-only message).
        let expectedLang;
        if (text && typeof detectLang === 'function') {
            expectedLang = detectLang(text);
        } else {
            expectedLang = currentLang === 'es' ? 'es-MX' : 'en-US';
        }
        // Pass sentProvider so a mid-flight chat switch cannot retarget the worker.
        Promise.resolve(
            window.pywebview.api.send_message_async(
                text,
                filesToSend,
                expectedLang,
                isVoice,
                null,
                null,
                null,
                sentProvider
            )
        )
            .then(response => {
                if (response && response.status === 'error') {
                    cancelProviderProcessing(sentProvider);
                    if (currentProvider === sentProvider) {
                        appendMessage(
                            'assistant',
                            `**Error:** ${response.message || response.error || 'Send failed'}`,
                            null, null, false, null, false, sentProvider
                        );
                    }
                    return;
                }
                if (response && response.request_id) {
                    let requestId = response.request_id;
                    window.activeRequestIds = window.activeRequestIds || {};
                    window.activeRequestIds[sentProvider] = requestId;
                    let appendedRepliesCount = 0;
                    let streamedGroupReplies = 0;
                    if (pollIntervals[sentProvider]) clearTimeout(pollIntervals[sentProvider]);
                    let pollDelay = 400;
                    const pollStartedAt = Date.now();
                    const POLL_TIMEOUT_MS = resolveGenerationPollTimeoutMs(filesToSend);
                    // Transient transport blips (ACA scale events) shouldn't kill the poll.
                    const POLL_MAX_TRANSIENT_RETRIES = 4;
                    let pollTransientFailures = 0;
                    function finishPollError(errMsg) {
                        cancelProviderProcessing(sentProvider);
                        if (currentProvider === sentProvider) {
                            appendMessage('assistant', `**Error:** ${errMsg}`, null, null, false, null, false, sentProvider);
                            if (isVoice && typeof speakText === 'function') {
                                speakText(null, errMsg);
                            }
                        }
                    }
                    function pollStatus() {
                        if (Date.now() - pollStartedAt > POLL_TIMEOUT_MS) {
                            finishPollError(
                                currentLang === 'es'
                                    ? 'La generación tardó demasiado y se canceló. Intenta de nuevo.'
                                    : 'Generation timed out. Please try again.'
                            );
                            return;
                        }
                        // Ask backend for replies after the ones we already applied (slim payloads).
                        Promise.resolve(
                            window.pywebview.api.get_generation_status(requestId, appendedRepliesCount)
                        )
                            .then(status => {
                                let newReplies = false;
                                const incoming = status.replies || [];
                                // Backend may return either a delta slice or the full list.
                                const startIdx = (status.reply_offset != null)
                                    ? 0
                                    : appendedRepliesCount;
                                const delta = (status.reply_offset != null)
                                    ? incoming
                                    : incoming.slice(appendedRepliesCount);
                                if (delta.length > 0) {
                                    newReplies = true;
                                    for (let i = 0; i < delta.length; i++) {
                                        const r = delta[i];
                                        try {
                                            const notificationAudio = new Audio('assets/whatsapp_notification_llm.mp3');
                                            notificationAudio.play().catch(e => console.warn("Audio play failed:", e));
                                        } catch (e) { }

                                        if (sentProvider === currentProvider) {
                                            const extra = { files: r.files || [] };
                                            if (r.image_data) extra.image_data = r.image_data;
                                            if (r.audio_data) { extra.audio_data = r.audio_data; extra.audio_mime = r.audio_mime; }
                                            if (r.audio_mime === 'browser-tts' && r.script) extra.script = r.script;
                                            if (r.iso_timestamp) extra.iso_timestamp = r.iso_timestamp;
                                            appendMessage('assistant', r.reply, r.token_info, null, false, extra, isVoice, r.provider);
                                            if (typeof window.updateAiGridReply === 'function') {
                                                window.updateAiGridReply(r.provider, r.reply, r.token_info);
                                            }
                                        } else {
                                            unreadCounts[sentProvider] = (unreadCounts[sentProvider] || 0) + 1;
                                            streamedGroupReplies += 1;
                                            if (typeof updateNotificationBell === 'function') {
                                                updateNotificationBell();
                                            }
                                        }
                                        if (typeof updateChatListItem === 'function') {
                                            updateChatListItem(sentProvider, {
                                                role: 'assistant',
                                                content: `[${r.provider}]: ${r.reply}`,
                                                iso_timestamp: r.iso_timestamp || new Date().toISOString(),
                                                timestamp: new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
                                            });
                                        }
                                    }
                                    if (status.reply_offset != null) {
                                        appendedRepliesCount = status.reply_offset + delta.length;
                                    } else {
                                        appendedRepliesCount = incoming.length;
                                    }
                                }

                                if (status.status === 'processing' || status.status === 'queued') {
                                    pollTransientFailures = 0;
                                    if (typeof window.updateAiGridFromStatus === 'function') {
                                        window.updateAiGridFromStatus(status, sentProvider);
                                    }
                                    if (sentProvider === currentProvider) {
                                        if (status.current_respondent) {
                                            showTypingWithSteps([`${status.current_respondent} is typing...`]);
                                        } else if (stepIndices[sentProvider] >= activeSteps[sentProvider].length - 1) {
                                            showTypingWithSteps([
                                                currentLang === 'es' ? 'Todavía trabajando...' : 'Still working...'
                                            ]);
                                        }
                                    }
                                    // Adaptive backoff: faster while streaming, slower otherwise
                                    // to avoid saturating the bridge when two chats poll at once.
                                    if (newReplies) {
                                        pollDelay = 400;
                                    } else {
                                        pollDelay = Math.min(pollDelay + 150, 1500);
                                    }
                                    pollIntervals[sentProvider] = setTimeout(pollStatus, pollDelay);
                                } else if (status.status === 'done') {
                                    if (typeof window.updateAiGridFromStatus === 'function') {
                                        window.updateAiGridFromStatus(status, sentProvider);
                                    }
                                    cancelProviderProcessing(sentProvider, { keepTyping: true });
                                    if (currentProvider === sentProvider) {
                                        removeTyping();
                                        if (typeof window.syncSharedControlsForProvider === 'function') {
                                            window.syncSharedControlsForProvider(sentProvider);
                                        } else {
                                            const sendBtnDone = document.getElementById('send-btn');
                                            if (sendBtnDone) sendBtnDone.disabled = false;
                                        }
                                        const userChecks = document.querySelectorAll('.message-wrapper.user .checkmark');
                                        if (userChecks.length > 0) {
                                            const lastCheck = userChecks[userChecks.length - 1];
                                            if (lastCheck) {
                                                lastCheck.className = 'checkmark read';
                                                lastCheck.innerHTML = '✓✓';
                                            }
                                        }
                                    }
                                    if (status.result) {
                                        if (status.result.token_totals && status.result.token_totals[sentProvider] !== undefined) {
                                            window.providerTokens[sentProvider] = status.result.token_totals[sentProvider];
                                            if (sentProvider === currentProvider) updateTokenDisplay(currentProvider);
                                        }
                                        status.result.sentProvider = sentProvider;
                                        // Group replies were already streamed; avoid double unread/UI work.
                                        status.result._streamedReplyCount = streamedGroupReplies || appendedRepliesCount;
                                        handleResult(status.result);
                                    } else if (window.getProviderFSM) {
                                        window.getProviderFSM(sentProvider).transition(window.FSM_STATES.IDLE, { reason: 'done-no-result' });
                                        if (typeof window.syncSharedControlsForProvider === 'function' && currentProvider === sentProvider) {
                                            window.syncSharedControlsForProvider(sentProvider);
                                        }
                                    }
                                } else if (status.status === 'cancelled') {
                                    cancelProviderProcessing(sentProvider);
                                    if (currentProvider === sentProvider) {
                                        removeTyping();
                                    }
                                } else if (status.status === 'error') {
                                    // Remote proxy uses `message`; local uses `error`.
                                    const errText = status.error || status.message || '';
                                    const transient = /unavailable|timeout|timed out|50[234]/i.test(errText);
                                    if (transient && pollTransientFailures < POLL_MAX_TRANSIENT_RETRIES) {
                                        pollTransientFailures += 1;
                                        pollDelay = Math.min(1500 * pollTransientFailures, 5000);
                                        pollIntervals[sentProvider] = setTimeout(pollStatus, pollDelay);
                                    } else {
                                        finishPollError(errText || 'Unknown error');
                                    }
                                } else {
                                    finishPollError(
                                        status.error
                                        || status.message
                                        || (currentLang === 'es'
                                            ? 'Se perdió el estado de la solicitud. Intenta enviar de nuevo.'
                                            : 'Request status was lost. Please send again.')
                                    );
                                }
                            })
                            .catch(err => {
                                if (pollTransientFailures < POLL_MAX_TRANSIENT_RETRIES) {
                                    pollTransientFailures += 1;
                                    pollDelay = Math.min(1500 * pollTransientFailures, 5000);
                                    pollIntervals[sentProvider] = setTimeout(pollStatus, pollDelay);
                                    return;
                                }
                                finishPollError(
                                    currentLang === 'es'
                                        ? `Error de conexión: ${err}`
                                        : `Connection Error: ${err}`
                                );
                            });
                    }
                    pollIntervals[sentProvider] = setTimeout(pollStatus, pollDelay);
                } else {
                    cancelProviderProcessing(sentProvider);
                    if (sentProvider === currentProvider) {
                        const errMsg = "Async not supported.";
                        appendMessage('assistant', `**Error:** ${errMsg}`, null, null, false, null, false, sentProvider);
                        if (isVoice && typeof speakText === 'function') {
                            speakText(null, errMsg);
                        }
                    }
                }
            })
            .catch(err => {
                cancelProviderProcessing(sentProvider);
                if (sentProvider === currentProvider) {
                    const errMsg = `${err}`;
                    appendMessage('assistant', `**Error:** ${errMsg}`, null, null, false, null, false, sentProvider);
                    if (isVoice && typeof speakText === 'function') {
                        speakText(null, errMsg);
                    }
                }
                if (typeof updateInputButtonsState === 'function') updateInputButtonsState();
            });
    } catch (syncErr) {
        console.error('sendMessage failed before async dispatch:', syncErr);
        // Restore composer so document attaches are not lost on UI exceptions.
        pendingFiles = filesToSend.concat(pendingFiles);
        if (msgInput && text) {
            msgInput.value = text;
            msgInput.style.height = 'auto';
            msgInput.style.height = `${msgInput.scrollHeight}px`;
        }
        cancelProviderProcessing(sentProvider);
        if (typeof renderPendingFiles === 'function') renderPendingFiles();
        if (typeof updateInputButtonsState === 'function') updateInputButtonsState();
        if (sentProvider === currentProvider) {
            appendMessage(
                'assistant',
                `**Error:** ${syncErr && syncErr.message ? syncErr.message : syncErr}`,
                null, null, false, null, false, sentProvider
            );
        }
    }
}

// Function to handle result
function handleResult(result) {
    const resProvider = result.provider || result.sentProvider || currentProvider;

    if (result.status === 'error') {
        if (resProvider === currentProvider) {
            appendMessage('assistant', `**Error:** ${result.message}`, null, null, false, null, false, resProvider);
            if (result.from_mic && typeof speakText === 'function') {
                speakText(null, result.message);
            }
        }
        return;
    }

    // Update user message bubble with transcription if it exists
    if (result.user_prompt && resProvider === currentProvider) {
        const userWrappers = document.querySelectorAll('.message-wrapper.user');
        if (userWrappers.length > 0) {
            const lastUser = userWrappers[userWrappers.length - 1];
            const contentDiv = lastUser.querySelector('.message-content');
            if (contentDiv) {
                // If it is from the microphone, keep the custom voice player!
                if (!result.from_mic) {
                    // Keep the attachments div if it exists in the message bubble
                    const attachmentsDiv = contentDiv.querySelector('.message-attachments');
                    const attachmentsHtml = attachmentsDiv ? attachmentsDiv.outerHTML : '';

                    let contentHtml = result.user_prompt;
                    try {
                        if (typeof marked !== 'undefined' && marked.parse) {
                            contentHtml = marked.parse(result.user_prompt);
                        } else {
                            contentHtml = result.user_prompt.replace(/\n/g, '<br>');
                        }
                    } catch (e) {
                        contentHtml = result.user_prompt.replace(/\n/g, '<br>');
                    }
                    contentDiv.innerHTML = attachmentsHtml + contentHtml;
                }
            }
        }
    }

    let replyText = '';
    if (result.is_group && result.replies) {
        replyText = result.replies.map(r => `${r.provider}: ${r.reply}`).join('\n\n');
    } else {
        replyText = result.reply || 'No response';
    }
    let extra = {};
    if (result.image_data) extra.image_data = result.image_data;
    if (result.audio_data) { extra.audio_data = result.audio_data; extra.audio_mime = result.audio_mime; }
    if (result.audio_mime === 'browser-tts' && result.script) {
        extra.script = result.script;
    }
    if (result.files) {
        extra.files = result.files;
    }
    if (result.iso_timestamp) {
        extra.iso_timestamp = result.iso_timestamp;
    }

    let tokenInfo = result.token_info || null;

    // Play WhatsApp notification sound for LLM response
    try {
        const notificationAudio = new Audio('assets/whatsapp_notification_llm.mp3');
        notificationAudio.play().catch(e => console.warn("Notification audio play failed:", e));
    } catch (e) {
        console.error("Error playing notification audio:", e);
    }

    if (result.token_totals && result.token_totals[resProvider] !== undefined) {
        window.providerTokens[resProvider] = result.token_totals[resProvider];
    } else if (tokenInfo) {
        const c = Number(tokenInfo.candidates_tokens || tokenInfo.completion_tokens || 0);
        const th = Number(tokenInfo.thinking_tokens || 0);
        const tot = Number(tokenInfo.total_tokens || 0);
        window.providerTokens[resProvider] = (window.providerTokens[resProvider] || 0) + (c + th || tot);
        if (result.user_prompt_tokens) {
            window.providerTokens[resProvider] += Number(result.user_prompt_tokens) || 0;
        }
    }
    if (resProvider === currentProvider) {
        updateTokenDisplay(currentProvider);

        // Dynamically show prompt tokens consumed on the user's message
        const userPromptTokens = result.user_prompt_tokens || 0;
        if (userPromptTokens > 0) {
            const userMetas = document.querySelectorAll('.message-wrapper.user .message-meta-inline');
            if (userMetas.length > 0) {
                const lastUserMeta = userMetas[userMetas.length - 1];
                if (lastUserMeta && !lastUserMeta.querySelector('.token-details')) {
                    const tokenSpan = document.createElement('span');
                    tokenSpan.className = 'token-details';
                    const t = translations[currentLang] || translations['en'];
                    const tokensConsumedText = t.tokens_consumed.replace('{tokens}', userPromptTokens);
                    tokenSpan.innerHTML = `${tokensConsumedText} <span class="meta-separator">•</span> `;
                    lastUserMeta.insertBefore(tokenSpan, lastUserMeta.firstChild);
                }
            }
        }

        if (!result.is_group) {
            appendMessage('assistant', replyText, tokenInfo, null, false, extra, result.from_mic || false, resProvider);
        }

        if (result.goodbye_detected) {
            if (typeof window.stopVoiceLoop === 'function') {
                window.stopVoiceLoop();
            }
        }

        if (result.from_mic) {
            if (typeof window.setVoiceLoopActive === 'function') {
                window.setVoiceLoopActive(!result.goodbye_detected);
            }
            if (result.is_group) {
                // Speak only the first reply: reading every provider's full answer
                // stalls SPEAKING for minutes and floods Cartesia with requests.
                const firstReply = (result.replies && result.replies[0]) || null;
                const spokenText = firstReply
                    ? `${firstReply.provider}: ${firstReply.reply}`
                    : replyText;
                speakText(null, spokenText);
            } else {
                const lastMsg = document.querySelector('.message-wrapper.assistant:last-child .tts-btn');
                if (lastMsg && replyText) {
                    speakText(lastMsg, replyText);
                } else {
                    speakText(null, replyText || '');
                }
            }
        }

        // Update user checkmarks to "read"
        const userChecks = document.querySelectorAll('.message-wrapper.user .checkmark');
        if (userChecks.length > 0) {
            const lastCheck = userChecks[userChecks.length - 1];
            if (lastCheck) {
                lastCheck.className = 'checkmark read';
                lastCheck.innerHTML = '✓✓';
            }
        }
    } else if (!(result.is_group && (result._streamedReplyCount || 0) > 0)) {
        // Background 1:1 completion. Group replies already bumped unread while streaming.
        unreadCounts[resProvider] = (unreadCounts[resProvider] || 0) + 1;
        if (typeof updateNotificationBell === 'function') {
            updateNotificationBell();
        }
    }

    // Update preview row in the chats sidebar (groups already updated per streamed reply)
    if (!(result.is_group && (result._streamedReplyCount || 0) > 0) && typeof updateChatListItem === 'function') {
        updateChatListItem(resProvider, {
            role: 'assistant',
            content: replyText,
            iso_timestamp: result.iso_timestamp || new Date().toISOString(),
            timestamp: new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
        });
    }

    if (resProvider === currentProvider && typeof window.syncSharedControlsForProvider === 'function') {
        window.syncSharedControlsForProvider(resProvider);
    }
}

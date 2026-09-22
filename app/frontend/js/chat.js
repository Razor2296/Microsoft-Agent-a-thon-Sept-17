// app/frontend/chat.js
// Message rendering, avatars, and history rendering logic

// --- Helper: Reliable Image Download via Blob URL ---
window.downloadGeneratedImage = function(btn) {
    if (!btn) return;
    const src = btn.dataset.src || btn.getAttribute('data-src');
    const filename = btn.dataset.filename || `IgniteChat_Imagen_${Date.now()}.png`;
    if (!src) return;

    // 1. PyWebView Native Desktop Download (bypasses browser <a download> block)
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.save_file_to_downloads === 'function') {
        window.pywebview.api.save_file_to_downloads(src, filename)
            .then(res => {
                if (res && res.status === 'success') {
                    console.log('File saved to Downloads successfully:', res.filepath);
                } else if (res && res.message) {
                    console.error('save_file_to_downloads message:', res.message);
                }
            })
            .catch(err => console.error('save_file_to_downloads error:', err));
        return;
    }

    try {
        if (src.startsWith('data:')) {
            const parts = src.split(',');
            const mimeMatch = parts[0].match(/:(.*?);/);
            const mime = mimeMatch ? mimeMatch[1] : 'image/png';
            const bstr = atob(parts[1]);
            let n = bstr.length;
            const u8arr = new Uint8Array(n);
            while (n--) {
                u8arr[n] = bstr.charCodeAt(n);
            }
            const blob = new Blob([u8arr], { type: mime });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            setTimeout(() => {
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            }, 1000);
        } else {
            fetch(src)
                .then(res => res.blob())
                .then(blob => {
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.style.display = 'none';
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    setTimeout(() => {
                        document.body.removeChild(a);
                        URL.revokeObjectURL(url);
                    }, 1000);
                })
                .catch(() => {
                    const a = document.createElement('a');
                    a.style.display = 'none';
                    a.href = src;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    setTimeout(() => document.body.removeChild(a), 1000);
                });
        }
    } catch (e) {
        console.error('downloadGeneratedImage error:', e);
    }
};

// Avatar helpers
function getAvatarHtml(role, raw = false) {
    if (!role) role = 'assistant';
    // role can be 'user', 'assistant', or a provider name like 'Gemini', 'DeepSeek', etc.
    let avatarContent;
    if (role === 'user') {
        avatarContent = appAvatars['user'];
    } else if (role === 'assistant') {
        avatarContent = appAvatars[currentProvider];
    } else {
        // Treat role as a provider name
        avatarContent = appAvatars[role];
    }
    let defaultIcon = role === 'user' ? '🧑‍💻' : '🤖';
    
    // Determine fallback src depending on the role
    let fallbackSrc = '';
    if (role && role !== 'user' && role !== 'assistant') {
        fallbackSrc = `assets/${role.toLowerCase()}-color.svg`;
    } else if (role === 'assistant') {
        fallbackSrc = `assets/${currentProvider ? currentProvider.toLowerCase() : 'gemini'}-color.svg`;
    }
    
    if (!avatarContent) {
        if (fallbackSrc) {
            return raw ? `<img src="${fallbackSrc}" alt="${role}"/>` : `<div class="avatar-icon"><img src="${fallbackSrc}" alt="${role}" onerror="this.parentElement.className='avatar-icon default'; this.outerHTML='${defaultIcon}'"/></div>`;
        }
        return raw ? defaultIcon : `<div class="avatar-icon default">${defaultIcon}</div>`;
    }
    
    if (avatarContent.startsWith('<svg')) {
        return raw ? avatarContent : `<div class="avatar-icon svg-icon">${avatarContent}</div>`;
    } else if (avatarContent.startsWith('data:image') || avatarContent.includes('base64')) {
        return raw ? `<img src="${avatarContent}" alt="avatar"/>` : `<div class="avatar-icon"><img src="${avatarContent}" alt="avatar"/></div>`;
    }
    
    // Fallback if avatarContent is present but unsupported format
    if (fallbackSrc) {
        return raw ? `<img src="${fallbackSrc}" alt="${role}"/>` : `<div class="avatar-icon"><img src="${fallbackSrc}" alt="${role}" onerror="this.parentElement.className='avatar-icon default'; this.outerHTML='${defaultIcon}'"/></div>`;
    }
    
    return raw ? defaultIcon : `<div class="avatar-icon default">${defaultIcon}</div>`;
}

// Function to generate random ID
function generateId() {
    return Math.random().toString(36).substr(2, 9);
}

// Functions to get date badge text
function getDateBadgeText(dateStr) {
    if (!dateStr) return translations[currentLang].today;
    const parts = dateStr.split('-');
    if (parts.length !== 3) return dateStr;
    const msgDate = new Date(parts[0], parts[1] - 1, parts[2]);
    const today = new Date();
    const diffTime = today.setHours(0, 0, 0, 0) - msgDate.setHours(0, 0, 0, 0);
    const diffDays = Math.round(diffTime / (1000 * 60 * 60 * 24));

    if (diffDays === 0) return translations[currentLang].today;
    if (diffDays === 1) return translations[currentLang].yesterday;
    return msgDate.toLocaleDateString('en-GB');
}

function getLocalDateStr() {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    const d = String(now.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
}

// Ensure today's date badge is added for live messages
function ensureTodayBadge() {
    const chatContainer = document.getElementById('chat-container');
    if (!chatContainer) return;
    
    const todayDateStr = getLocalDateStr();
    const todayText = translations[currentLang].today;

    // Find all date badge containers in the chat container
    const badgeContainers = chatContainer.querySelectorAll('.chat-date-badge-container');
    if (badgeContainers.length > 0) {
        const lastContainer = badgeContainers[badgeContainers.length - 1];
        const lastDate = lastContainer.getAttribute('data-date');
        
        if (lastDate === todayDateStr) {
            // Already has today's badge as the latest badge
            return;
        }
        
        // Midnight has passed! Update all existing badges' text relative to the new day
        badgeContainers.forEach(container => {
            const dateStr = container.getAttribute('data-date');
            if (dateStr) {
                const badge = container.querySelector('.chat-date-badge');
                if (badge) {
                    badge.textContent = getDateBadgeText(dateStr);
                }
            }
        });
    }

    // Append today's badge
    const badgeContainer = document.createElement('div');
    badgeContainer.className = 'chat-date-badge-container';
    badgeContainer.setAttribute('data-date', todayDateStr);
    badgeContainer.innerHTML = `<div class="chat-date-badge">${todayText}</div>`;
    chatContainer.appendChild(badgeContainer);
}

// Scroll to bottom helper with layout delay protection
function scrollToBottom(force = false) {
    const chatContainer = document.getElementById('chat-container');
    if (!chatContainer || !force) return;
    
    // Immediate scroll to handle instant updates
    chatContainer.scrollTop = chatContainer.scrollHeight;
    
    // Delayed scroll to handle browser layout/reflow (especially for markdown)
    setTimeout(() => {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }, 50);
    
    // Extra delayed scroll as a safety buffer for slower rendering processes
    setTimeout(() => {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }, 150);
}

// --- Helper: Build Voice Player HTML ---
function buildVoicePlayerHTML(extra, fallbackContent) {
    let voiceFile = null;
    if (extra && extra.files) {
        voiceFile = extra.files.find(f => f.name && f.name.startsWith('Voice_Message_'));
    }
    if (voiceFile && voiceFile.base64) {
        const mime = voiceFile.mime_type || 'audio/webm';
        const audioSrc = `data:${mime};base64,${voiceFile.base64}`;
        const playerUid = generateId();
        
        const heights = [10, 16, 12, 22, 14, 8, 20, 18, 12, 24, 16, 10, 18, 14, 22, 8, 12, 16, 10, 6];
        const barsHtml = heights.map(h => `<span class="w-bar" style="height: ${h}px;"></span>`).join('');
        
        return `
        <div class="whatsapp-voice-player" id="player-${playerUid}">
            <audio id="audio-${playerUid}" src="${audioSrc}"></audio>
            <button class="voice-play-btn" onclick="toggleVoicePlay('${playerUid}')">
                <svg class="play-icon" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>
                <svg class="pause-icon" viewBox="0 0 24 24" style="display:none;"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" fill="currentColor"/></svg>
            </button>
            <div class="voice-waveform-container" onclick="seekVoice(event, '${playerUid}')">
                <div class="voice-waveform" id="waveform-${playerUid}">
                    ${barsHtml}
                </div>
            </div>
            <div class="voice-speed-badge" onclick="cycleVoiceSpeed('${playerUid}')" id="speed-${playerUid}">1x</div>
            <div class="voice-duration" id="duration-${playerUid}">0:00</div>
        </div>
        `;
    }
    return `
    <div class="whatsapp-voice-player-placeholder">
        🎙️ <em>(Voice Message: ${fallbackContent})</em>
    </div>
    `;
}

// Additive Markdown enhancers — never changes marked.parse output structure.
function enhanceCodeBlocks(rootEl) {
    if (!rootEl) return;
    const blocks = rootEl.querySelectorAll('pre > code');
    blocks.forEach((codeEl) => {
        const pre = codeEl.parentElement;
        if (!pre || pre.dataset.enhanced === '1') return;
        pre.dataset.enhanced = '1';
        pre.classList.add('code-block');

        // Optional highlight.js (loaded only if present; never required).
        try {
            if (window.hljs && typeof window.hljs.highlightElement === 'function') {
                window.hljs.highlightElement(codeEl);
            }
        } catch (e) {}

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'code-copy-btn';
        btn.textContent = currentLang === 'es' ? 'Copiar' : 'Copy';
        btn.addEventListener('click', async (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            const text = codeEl.innerText || codeEl.textContent || '';
            try {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    await navigator.clipboard.writeText(text);
                } else {
                    const ta = document.createElement('textarea');
                    ta.value = text;
                    document.body.appendChild(ta);
                    ta.select();
                    document.execCommand('copy');
                    document.body.removeChild(ta);
                }
                btn.textContent = currentLang === 'es' ? 'Copiado' : 'Copied';
                setTimeout(() => {
                    btn.textContent = currentLang === 'es' ? 'Copiar' : 'Copy';
                }, 1200);
            } catch (err) {
                console.warn('Code copy failed:', err);
            }
        });
        pre.appendChild(btn);
    });
}

// --- Helper: Build Message Attachments HTML ---
function buildMessageAttachmentsHTML(extra, contentHtml) {
    if (!extra) return contentHtml;

    if (extra.files && extra.files.length > 0) {
        const displayFiles = extra.files.filter(f => !f.name.startsWith('Voice_Message_'));
        if (displayFiles.length > 0) {
            let filesHtml = '<div class="message-attachments">';
            displayFiles.forEach(f => {
                if (typeof window.rememberFileForPreview === 'function') {
                    window.rememberFileForPreview(f);
                }
                const mime = f.mime_type || '';
                const safeName = typeof escapeHtml === 'function' ? escapeHtml(f.name || 'file') : (f.name || 'file');
                if (mime.startsWith('image/') && f.base64) {
                    filesHtml += `<img src="data:${mime};base64,${f.base64}" alt="${safeName}" class="attachment-image-preview" data-preview-id="${f.preview_id || ''}" data-file-name="${safeName}" data-mime="${mime}"/>`;
                } else if (mime.startsWith('video/') && f.base64) {
                    filesHtml += `<video class="attachment-video-preview" controls preload="metadata" data-preview-id="${f.preview_id || ''}" data-file-name="${safeName}" data-mime="${mime}"><source src="data:${mime};base64,${f.base64}" type="${mime}"></video>`;
                } else if (typeof window.buildWhatsAppAttachmentCardHTML === 'function') {
                    filesHtml += window.buildWhatsAppAttachmentCardHTML(f);
                } else {
                    const sizeText = f.size ? formatFileSize(f.size) : '';
                    const sizeHtml = sizeText ? `<span class="attachment-card-size">${sizeText}</span>` : '';
                    const iconHtml = typeof getFileIcon === 'function' ? getFileIcon(f) : '📎';
                    const officeKind = typeof getOfficeFileKind === 'function' ? getOfficeFileKind(f) : null;
                    const officeClass = officeKind ? ` attachment-card--${officeKind}` : '';
                    const pathAttr = f.path ? ` data-path="${f.path}" style="cursor: pointer;" onclick="window.openAttachmentFile(this)"` : '';
                    filesHtml += `
                        <div class="attachment-card${officeClass}"${pathAttr}>
                            <div class="attachment-card-icon">${iconHtml}</div>
                            <div class="attachment-card-details">
                                <span class="attachment-card-name" title="${safeName}">${safeName}</span>
                                ${sizeHtml}
                            </div>
                        </div>
                    `;
                }
            });
            filesHtml += '</div>';
            contentHtml = filesHtml + contentHtml;
        }
    }
    if (extra.image_data) {
        const downloadFilename = `IgniteChat_Imagen_${Date.now()}.png`;
        contentHtml += `
            <div class="generated-image-wrapper">
                <img src="${extra.image_data}" alt="Generated Image" class="generated-chat-image" />
                <button type="button" class="image-download-overlay-btn" title="Descargar imagen" data-src="${extra.image_data}" data-filename="${downloadFilename}" onclick="window.downloadGeneratedImage(this)">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                        <polyline points="7 10 12 15 17 10"></polyline>
                        <line x1="12" y1="15" x2="12" y2="3"></line>
                    </svg>
                </button>
            </div>
        `;
    }
    if (extra.audio_data && extra.audio_mime) {
        contentHtml += `<br/><audio controls style="width:100%;margin-top:8px;"><source src="${extra.audio_data}" type="${extra.audio_mime}"></audio>`;
    }
    if (extra.audio_mime === 'browser-tts' && extra.script) {
        contentHtml += `<br/><i>🔊 Browser TTS generated: "${extra.script}"</i>`;
    }
    return contentHtml;
}

/** Refresh attachment cards on a live user bubble after async PDF thumbnail hydrate.
 *  MUST preserve WhatsApp voice player: buildMessageAttachmentsHTML filters out
 *  Voice_Message_* — rebuilding with text-only HTML empties mic bubbles. */
window.refreshMessageAttachments = function(msgId, files, content) {
    try {
        const wrapper = document.querySelector(`[data-msg-id="${CSS.escape(msgId)}"]`);
        if (!wrapper) return;
        const contentEl = wrapper.querySelector('.message-content');
        if (!contentEl) return;
        const raw = content != null ? content : (wrapper.dataset.rawContent || '');
        const fileList = files || [];
        const isVoice =
            wrapper.dataset.isVoice === '1' ||
            fileList.some((f) => (f.name || '').startsWith('Voice_Message_'));

        // Voice-only: player already rendered in appendMessage — do not rebuild.
        if (isVoice) {
            const hasNonVoice = fileList.some(
                (f) => !(f.name || '').startsWith('Voice_Message_')
            );
            if (!hasNonVoice) return;
            let voiceHtml = buildVoicePlayerHTML({ files: fileList }, raw);
            contentEl.innerHTML = buildMessageAttachmentsHTML({ files: fileList }, voiceHtml);
            return;
        }

        let textHtml = raw;
        try {
            if (typeof marked !== 'undefined' && marked.parse) {
                textHtml = marked.parse(raw);
            } else {
                textHtml = raw.replace(/\n/g, '<br>');
            }
        } catch (parseErr) {
            textHtml = raw.replace(/\n/g, '<br>');
        }
        contentEl.innerHTML = buildMessageAttachmentsHTML({ files: fileList }, textHtml);
    } catch (err) {
        console.warn('refreshMessageAttachments failed:', err);
    }
};

// --- Helper: Build Avatar HTML ---
function buildMessageAvatarHTML(role, msgProvider) {
    msgProvider = msgProvider || currentProvider;
    const providerLabel = msgProvider.toUpperCase();

    let color = '#3186FF';
    if (msgProvider === 'DeepSeek') color = '#4C6BFE';
    else if (msgProvider === 'OpenAI') color = '#10a37f';
    else if (msgProvider === 'Anthropic') color = '#cc785c';
    else if (msgProvider === 'Perplexity') color = '#19a3b8';
    else if (msgProvider === 'Grok') color = '#09090B';

    if (role === 'user') {
        return `
            <div class="message-avatar-outer">
                ${getAvatarHtml('user')}
                <div class="avatar-label" style="color: #ff2b2b;">YOU</div>
            </div>
        `;
    }
    return `
        <div class="message-avatar-outer">
            ${getAvatarHtml(msgProvider)}
            <div class="avatar-label" style="color: ${color}">${providerLabel}</div>
        </div>
    `;
}

window.formatMessageTimestamp = function(timestamp, extra) {
    const isoSource = (extra && extra.iso_timestamp) || (typeof timestamp === 'string' && (timestamp.includes('T') || timestamp.includes('Z')) ? timestamp : null);
    if (isoSource) {
        try {
            const d = new Date(isoSource);
            if (!isNaN(d.getTime())) {
                return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: true });
            }
        } catch(e) {}
    }
    if (timestamp && typeof timestamp === 'string' && timestamp.trim()) {
        return timestamp;
    }
    return new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: true });
};

// Append Message to UI
function appendMessage(role, content, tokenInfo = null, timestamp = null, addCheckmarks = false, extra = null, isVoice = false, msgProvider = null, isLive = true) {
    try {
        const chatContainer = document.getElementById('chat-container');
        const wasNearBottom = chatContainer ? (chatContainer.scrollHeight - chatContainer.clientHeight - chatContainer.scrollTop < 20) : false;

        if (isLive) {
            ensureTodayBadge();
        }
        const wrapperDiv = document.createElement('div');
        wrapperDiv.className = `message-wrapper ${role}`;
        wrapperDiv.dataset.rawContent = content;
        if (isVoice) {
            wrapperDiv.dataset.isVoice = '1';
        }

        let msgTs = Date.now();
        if (extra && extra.iso_timestamp) {
            try {
                const d = new Date(extra.iso_timestamp);
                if (!isNaN(d.getTime())) msgTs = d.getTime();
            } catch(e) {}
        } else if (extra && extra.date && timestamp) {
            try {
                const dateParts = extra.date.split('-');
                const timeParts = timestamp.split(' ');
                const hhmm = timeParts[0].split(':');
                let hours = parseInt(hhmm[0]);
                const minutes = parseInt(hhmm[1]);
                if (timeParts[1] === 'PM' && hours < 12) hours += 12;
                if (timeParts[1] === 'AM' && hours === 12) hours = 0;
                const d = new Date(parseInt(dateParts[0]), parseInt(dateParts[1]) - 1, parseInt(dateParts[2]), hours, minutes);
                msgTs = d.getTime();
            } catch(e) {}
        }
        wrapperDiv.dataset.ts = msgTs;

        const msgId = `msg-${generateId()}`;
        wrapperDiv.dataset.msgId = msgId;
        const timeStr = window.formatMessageTimestamp(timestamp, extra);
        const stableReactionKey = `rx-${role}-${(timeStr || '').replace(/[^\w]/g, '')}-${(content || '').slice(0, 20).replace(/\W/g, '_')}`;
        wrapperDiv.dataset.reactionKey = stableReactionKey;
        const t = translations[currentLang] || translations['en'];

        let tokensText = '';
        if (tokenInfo) {
            let tokens = 0;
            if (typeof tokenInfo === 'number') {
                tokens = tokenInfo;
            } else if (typeof tokenInfo === 'object') {
                if (role === 'user') {
                    tokens = Number(tokenInfo.prompt_tokens || tokenInfo.input_tokens || tokenInfo.total_tokens) || 0;
                } else {
                    const cand = Number(tokenInfo.candidates_tokens) || 0;
                    const comp = Number(tokenInfo.completion_tokens) || 0;
                    const think = Number(tokenInfo.thinking_tokens) || 0;
                    const out = Number(tokenInfo.output_tokens) || 0;
                    const tot = Number(tokenInfo.total_tokens) || 0;
                    const prompt = Number(tokenInfo.prompt_tokens) || 0;
                    tokens = (cand + think) || comp || out || tot || prompt || 0;
                }
            }
            if (tokens > 0) {
                const tokensConsumedText = t.tokens_consumed.replace('{tokens}', tokens.toLocaleString());
                tokensText = `<span class="token-details">${tokensConsumedText}</span>`;
            }
        }

        let checkmarksHtml = '';
        if (role === 'user' && addCheckmarks) {
            checkmarksHtml = `<span class="checkmark sent" id="${msgId}-check">✓</span>`;
        } else if (role === 'user') {
            checkmarksHtml = `<span class="checkmark read">✓✓</span>`;
        }

        // Render Markdown safely
        let contentHtml = content;
        try {
            if (typeof marked !== 'undefined' && marked.parse) {
                contentHtml = marked.parse(content);
            } else {
                contentHtml = content.replace(/\n/g, '<br>');
            }
        } catch (e) {
            contentHtml = content.replace(/\n/g, '<br>');
        }

        if (isVoice && role === 'user') {
            contentHtml = buildVoicePlayerHTML(extra, content);
        }

        contentHtml = buildMessageAttachmentsHTML(extra, contentHtml);

        // Skill: Smart Proactive Fallback Recovery Card (Only for live sessions)
        if (isLive && role === 'assistant' && (content.startsWith('Error:') || content.startsWith('⚠️') || (extra && extra.is_error))) {
            const userWrappers = Array.from(document.querySelectorAll('.message-wrapper.user'));
            const lastUserMsg = userWrappers.length > 0 ? userWrappers[userWrappers.length - 1] : null;
            const lastPrompt = lastUserMsg ? (lastUserMsg.dataset.rawContent || '') : '';
            const currentP = msgProvider || currentProvider || 'Gemini';
            const suggestedAlts = ['Gemini', 'DeepSeek', 'OpenAI'].filter(p => p !== currentP);
            const fallbackUid = `fb-${generateId()}`;
            window._pendingFallbackPrompts = window._pendingFallbackPrompts || {};
            window._pendingFallbackPrompts[fallbackUid] = lastPrompt;

            const buttonsHtml = suggestedAlts.map(alt => `
                <button class="whatsapp-btn green-btn" style="font-size:12px; padding:4px 10px; margin:2px;" onclick="window.triggerSmartFallback('${alt}', '${fallbackUid}')">
                    ⚡ Responder con ${alt}
                </button>
            `).join('');

            contentHtml += `
                <div class="smart-fallback-card" style="margin-top:12px; padding:10px 12px; border-radius:8px; background:rgba(234, 67, 53, 0.08); border:1px solid rgba(234, 67, 53, 0.25);">
                    <div style="font-size:12px; font-weight:600; color:var(--text-color); margin-bottom:8px;">
                        💡 ¿Deseas que complete tu consulta inmediatamente con otro proveedor disponible?
                    </div>
                    <div style="display:flex; flex-wrap:wrap; gap:6px;">
                        ${buttonsHtml}
                    </div>
                </div>
            `;
        }

        let footerHtml = '';
        if (role === 'assistant' && isVoice) {
            const ttsTitle = t.listen || 'Listen';
            footerHtml += `<button class="tts-btn" onclick="speakText(this)" title="${ttsTitle}">🔊</button> <span class="meta-separator">•</span> `;
        }
        if (tokensText) footerHtml += tokensText + ' <span class="meta-separator">•</span> ';
        footerHtml += `<span class="msg-timestamp">${timeStr} ${checkmarksHtml}</span>`;

        const avatarOuterHtml = buildMessageAvatarHTML(role, msgProvider);

        wrapperDiv.innerHTML = `
            ${avatarOuterHtml}
            <div class="message ${role}">
                <div class="message-content">${contentHtml}</div>
                <div class="message-footer">
                    <div class="reaction-badges" style="display: none;"></div>
                    <div class="message-meta-inline gemini-tokens">
                        ${footerHtml}
                    </div>
                </div>
            </div>
        `;

        chatContainer.appendChild(wrapperDiv);

        try {
            const contentNode = wrapperDiv.querySelector('.message-content');
            enhanceCodeBlocks(contentNode);
        } catch (enhanceErr) {
            console.warn('enhanceCodeBlocks skipped:', enhanceErr);
        }

        // Restore persisted reactions for this message (survives chat switches & re-renders)
        try {
            const savedRx = localStorage.getItem(stableReactionKey);
            if (savedRx) {
                const rxData = JSON.parse(savedRx);
                wrapperDiv.dataset.reactions = savedRx;
                renderReactionsUI(wrapperDiv, rxData);
            }
        } catch (_) {}
        // --- Add WhatsApp-style actions button and menu
        try {
            const messageBubble = wrapperDiv.querySelector('.message');
            const actionsBtn = document.createElement('button');
            actionsBtn.className = 'msg-actions-btn';
            actionsBtn.title = 'Message actions';
            actionsBtn.innerHTML = '\u25be'; // ▾ downward triangle

            actionsBtn.onclick = (ev) => {
                ev.stopPropagation();
                const existing = messageBubble.querySelector('.message-actions-menu');
                if (existing) { existing.remove(); return; }
                closeAllActionMenus();
                const menu = buildMessageActionsMenu(wrapperDiv, contentHtml, role);
                messageBubble.appendChild(menu);
            };

            wrapperDiv.addEventListener('mouseenter', () => {
                if (messageBubble && !messageBubble.querySelector('.msg-actions-btn')) {
                    messageBubble.appendChild(actionsBtn);
                }
            });
            wrapperDiv.addEventListener('mouseleave', () => {
                // Only remove the button — menu stays open until click-outside fires
                const btn = messageBubble ? messageBubble.querySelector('.msg-actions-btn') : null;
                if (btn) btn.remove();
            });
        } catch (e) {
            console.warn('Failed to attach message actions button', e);
        }

        
        const shouldScroll = isLive ? ((role === 'user') || wasNearBottom) : false;
        if (shouldScroll) {
            scrollToBottom(true);
        } else if (isLive && role !== 'user') {
            window.unreadWhileScrolledUp = (window.unreadWhileScrolledUp || 0) + 1;
            const badge = document.getElementById('scroll-bottom-badge');
            if (badge) {
                badge.textContent = window.unreadWhileScrolledUp;
                badge.classList.remove('hidden');
            }
        }

        // Scroll again when images load asynchronously
        const imgs = wrapperDiv.querySelectorAll('img');
        imgs.forEach(img => {
            img.onload = () => {
                if (shouldScroll) {
                    scrollToBottom(true);
                }
            };
        });

        return msgId;
    } catch (error) {
        console.error('appendMessage error:', error);
        // Mostrar un mensaje de error en el chat
        const errorDiv = document.createElement('div');
        errorDiv.className = 'message-wrapper assistant';
        errorDiv.innerHTML = `
            <div class="message assistant" style="background-color: #ff4b4b; color: white;">
                ⚠️ Error al mostrar el mensaje: ${error.message}
            </div>
        `;
        document.getElementById('chat-container').appendChild(errorDiv);
        return null;
    }
}

// Send welcome message and save it to backend history
function sendWelcomeMessage() {
    try {
        const t = translations[currentLang];
        
        // If current provider is a group, show a welcome message for each participant
        if (currentProvider && currentProvider.startsWith("group_")) {
            const groupInfo = window.customGroups && window.customGroups[currentProvider];
            if (groupInfo && groupInfo.participants && groupInfo.participants.length > 0) {
                groupInfo.participants.forEach(p => {
                    const greeting = t.greeting.replace('{name}', userName).replace('{provider}', p);
                    const tokenInfo = {
                        total_tokens: 0,
                        prompt_tokens: 0,
                        candidates_tokens: 0,
                        thinking_tokens: 0
                    };
                    appendMessage('assistant', greeting, tokenInfo, null, false, null, true, p);

                    // Save the welcome message to backend history under the group ID specifying the participant model
                    if (window.pywebview && window.pywebview.api && window.pywebview.api.save_welcome_message) {
                        window.pywebview.api.save_welcome_message(currentProvider, greeting, p).catch(err => {
                            console.error("Failed to save welcome message for participant " + p + ":", err);
                        });
                    }
                });
                if (typeof window.updateChatListItem === 'function') {
                    const lastGreeting = t.greeting.replace('{name}', userName).replace('{provider}', groupInfo.participants[groupInfo.participants.length - 1]);
                    window.updateChatListItem(currentProvider, {
                        role: 'assistant',
                        content: lastGreeting,
                        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                        is_welcome: true
                    });
                }
                return;
            }
        }
        
        // Default standard individual provider greeting
        const greeting = t.greeting.replace('{name}', userName).replace('{provider}', currentProvider);
        const tokenInfo = {
            total_tokens: 0,
            prompt_tokens: 0,
            candidates_tokens: 0,
            thinking_tokens: 0
        };
        appendMessage('assistant', greeting, tokenInfo, null, false, null, true, currentProvider);

        if (typeof window.updateChatListItem === 'function') {
            window.updateChatListItem(currentProvider, {
                role: 'assistant',
                content: greeting,
                timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                is_welcome: true
            });
        }
        window.cachedHistories = window.cachedHistories || {};
        window.cachedHistories[currentProvider] = [{
            role: 'assistant',
            content: greeting,
            is_welcome: true,
            provider: currentProvider,
            token_info: tokenInfo
        }];

        // Save the welcome message to backend history
        if (window.pywebview && window.pywebview.api && window.pywebview.api.save_welcome_message) {
            window.pywebview.api.save_welcome_message(currentProvider, greeting).catch(err => {
                console.error("Failed to save welcome message to backend:", err);
            });
        }
    } catch (e) {
        console.error("Error sending welcome message:", e);
        // Fallback: mostrar un mensaje de texto plano
        const chatContainer = document.getElementById('chat-container');
        chatContainer.innerHTML = `<div style="padding: 20px; color: var(--text-color);">${userName ? `Hello ${userName}!` : 'Hello!'} I'm your ${currentProvider} assistant.</div>`;
    }
}

// Typing indicator with steps
function showTypingWithSteps(steps) {
    const chatContainer = document.getElementById('chat-container');
    const wasNearBottom = chatContainer ? (chatContainer.scrollHeight - chatContainer.clientHeight - chatContainer.scrollTop < 20) : false;
    
    let typingDiv = document.getElementById('typing-indicator');
    const stepText = steps && steps.length > 0 ? steps[steps.length - 1] : 'Thinking...';
    
    if (!typingDiv) {
        typingDiv = document.createElement('div');
        typingDiv.className = 'message-wrapper assistant typing-wrapper';
        typingDiv.id = 'typing-indicator';
        typingDiv.innerHTML = `
            <div class="message-avatar-outer">
                ${getAvatarHtml(currentProvider || 'assistant')}
            </div>
            <div class="message assistant typing">
                <div class="typing-content">
                    <span class="spinner"></span>
                    <span class="step-text">${stepText}</span>
                </div>
            </div>
        `;
        chatContainer.appendChild(typingDiv);
    } else {
        const textSpan = typingDiv.querySelector('.step-text');
        if (textSpan) {
            textSpan.textContent = stepText;
        }
    }
    if (wasNearBottom) {
        scrollToBottom(true);
    }
}

// Function to remove typing indicator
function removeTyping() {
    const el = document.getElementById('typing-indicator');
    if (el) el.remove();
}

// Nueva función showWelcomeOrHistory
function showWelcomeOrHistory(history, ownerProvider = null) {
    const p = ownerProvider || currentProvider;
    window.cachedHistories = window.cachedHistories || {};
    window.cachedHistories[p] = history || [];

    // Limpia el contenedor
    const chatContainer = document.getElementById('chat-container');
    if (chatContainer) chatContainer.innerHTML = '';

    // Si hay mensajes, renderizarlos con el badge de fecha
    if (history && history.length > 0) {
        renderHistory(history, p);
    } else {
        // Si no hay mensajes, mostrar el saludo de bienvenida
        sendWelcomeMessage();
    }
}

// Render full history
function renderHistory(history, ownerProvider = null) {
    const chatContainer = document.getElementById('chat-container');
    chatContainer.innerHTML = '';
    const t = translations[currentLang] || translations['en'];
    const historyOwner = ownerProvider || currentProvider;
    window.providerTokens = window.providerTokens || {};
    let tokensForHistory = 0;

    let lastDate = null;

    if (!history || history.length === 0) {
        window.providerTokens[historyOwner] = 0;
        if (historyOwner === currentProvider) updateTokenDisplay(currentProvider);
        return;
    }

    history.forEach(msg => {
        try {
            let msgDateStr = msg.date || new Date().toISOString().split('T')[0];
            if (msgDateStr !== lastDate) {
                const badgeText = getDateBadgeText(msgDateStr);
                chatContainer.innerHTML += `<div class="chat-date-badge-container" data-date="${msgDateStr}"><div class="chat-date-badge">${badgeText}</div></div>`;
                lastDate = msgDateStr;
            }

            let text = msg.content || '';
            const msgProvider = msg.provider || historyOwner;

            // Strip internal system context injected by the backend before rendering user messages.
            // The backend prepends [SYSTEM NOTE: ...] and extracted file content to the user query.
            // We only want to show the actual user query in the chat bubble.
            if (msg.role === 'user' && text) {
                // Pattern 1: ends with "[User Query]:\n<actual text>" or "[Consulta del Usuario ...]:\n<actual text>"
                const userQueryMatch = text.match(/\[(?:User Query|Consulta del Usuario)[^\]]*\]:\s*([\s\S]*)$/i);
                if (userQueryMatch) {
                    text = userQueryMatch[1].trim();
                } else {
                    // Pattern 2: remove leading [SYSTEM NOTE: ...] blocks (possibly multiple)
                    // These blocks are surrounded by [ ] and contain "SYSTEM NOTE" or "System Note"
                    let cleaned = text.replace(/^\[(?:SYSTEM NOTE|System Note)[^\]]*\][\s\S]*?(?=\[(?:User Query|Consulta del Usuario)|\[User Input\]|$)/i, '').trim();
                    // Pattern 3: remove "--- Sheet: ... ---\n..." table content that was extracted from files
                    cleaned = cleaned.replace(/^---\s*Sheet:[^-]*---[\s\S]*$/m, '').trim();
                    if (cleaned && cleaned.length < text.length) {
                        text = cleaned;
                    }
                }
                // Final guard: if still looks like a system note header, just show original input
                if (!text || /^\[(?:SYSTEM NOTE|System Note)/i.test(text)) {
                    text = msg.content || '';
                }
            }

            const looksWelcome = !!msg.is_welcome || /^(Hello|Hi|Hey|Hola)\s+User\b/i.test(text);
            if (looksWelcome) {
                const welcomeT = translations[currentLang] || translations['en'];
                const displayName = (userName && userName !== 'User') ? userName : (userName || 'User');
                text = welcomeT.greeting
                    .replace('{name}', displayName)
                    .replace('{provider}', msgProvider);
            } else if (userName && userName !== 'User') {
                // Remote ACA may persist greetings with the generic Linux username.
                text = text.replace(/\b(Hello|Hi|Hey|Hola)\s+User\b/gi, `$1 ${userName}`);
            }

            let extra = {};
            if (msg.date) extra.date = msg.date;
            if (msg.iso_timestamp) extra.iso_timestamp = msg.iso_timestamp;
            if (msg.image_data) extra.image_data = msg.image_data;
            if (msg.audio_data) { extra.audio_data = msg.audio_data; extra.audio_mime = msg.audio_mime; }
            if (msg.audio_mime === 'browser-tts' && msg.script) {
                extra.audio_mime = msg.audio_mime;
                extra.script = msg.script;
            }
            if (msg.files) extra.files = msg.files;
            if (msg.token_info) {
                if (msg.role === 'user') {
                    tokensForHistory += Number(msg.token_info.prompt_tokens || msg.token_info.input_tokens || msg.token_info.total_tokens) || 0;
                } else {
                    const cand = Number(msg.token_info.candidates_tokens) || 0;
                    const comp = Number(msg.token_info.completion_tokens) || 0;
                    const think = Number(msg.token_info.thinking_tokens) || 0;
                    const out = Number(msg.token_info.output_tokens) || 0;
                    const tot = Number(msg.token_info.total_tokens) || 0;
                    const prompt = Number(msg.token_info.prompt_tokens) || 0;
                    tokensForHistory += (cand + think) || comp || out || tot || prompt || 0;
                }
            }
            appendMessage(msg.role, text, msg.token_info, msg.timestamp, false, extra, msg.is_welcome || msg.from_mic || false, msgProvider, false);
        } catch (err) {
            console.error("Error rendering message:", err);
            appendMessage('assistant', `⚠️ Error al mostrar mensaje: ${err.message}`, null, null, false, null, false, historyOwner, false);
        }
    });
    window.providerTokens[historyOwner] = tokensForHistory;
    if (historyOwner === currentProvider) {
        updateTokenDisplay(currentProvider);
    }
    
    // Scroll to bottom after loading history
    scrollToBottom(true);
    
    // Also scroll when any image in the history finishes loading
    const imgs = chatContainer.querySelectorAll('img');
    imgs.forEach(img => {
        if (!img.complete) {
            img.onload = () => scrollToBottom(true);
        }
    });
}

// --- WhatsApp Voice Message Playback Helpers ---
window.formatVoiceTime = function(seconds) {
    if (isNaN(seconds) || seconds === Infinity) return "0:00";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
};

window.toggleVoicePlay = function(id) {
    const audio = document.getElementById(`audio-${id}`);
    const playBtn = document.querySelector(`#player-${id} .play-icon`);
    const pauseBtn = document.querySelector(`#player-${id} .pause-icon`);
    if (!audio) return;

    if (!audio.dataset.initialized) {
        audio.dataset.initialized = "true";
        audio.addEventListener('timeupdate', () => {
            const percent = (audio.currentTime / audio.duration) * 100;
            const bars = document.querySelectorAll(`#waveform-${id} .w-bar`);
            const totalBars = bars.length;
            const activeCount = Math.floor((percent / 100) * totalBars);
            bars.forEach((bar, idx) => {
                if (idx < activeCount) {
                    bar.classList.add('active');
                } else {
                    bar.classList.remove('active');
                }
            });
            const durationEl = document.getElementById(`duration-${id}`);
            if (durationEl) {
                durationEl.textContent = window.formatVoiceTime(audio.currentTime);
            }
        });
        audio.addEventListener('ended', () => {
            playBtn.style.display = 'block';
            pauseBtn.style.display = 'none';
            const bars = document.querySelectorAll(`#waveform-${id} .w-bar`);
            bars.forEach(bar => bar.classList.remove('active'));
            const durationEl = document.getElementById(`duration-${id}`);
            if (durationEl) {
                durationEl.textContent = window.formatVoiceTime(audio.duration || 0);
            }
        });
        audio.addEventListener('loadedmetadata', () => {
            const durationEl = document.getElementById(`duration-${id}`);
            if (durationEl) {
                durationEl.textContent = window.formatVoiceTime(audio.duration);
            }
        });
    }

    if (audio.paused) {
        // Pause other active audio players
        document.querySelectorAll('audio').forEach(a => {
            if (a !== audio) {
                a.pause();
                const oid = a.id.replace('audio-', '');
                const oPlay = document.querySelector(`#player-${oid} .play-icon`);
                const oPause = document.querySelector(`#player-${oid} .pause-icon`);
                if (oPlay && oPause) {
                    oPlay.style.display = 'block';
                    oPause.style.display = 'none';
                }
            }
        });
        audio.play();
        playBtn.style.display = 'none';
        pauseBtn.style.display = 'block';
    } else {
        audio.pause();
        playBtn.style.display = 'block';
        pauseBtn.style.display = 'none';
    }
};

window.cycleVoiceSpeed = function(id) {
    const audio = document.getElementById(`audio-${id}`);
    const speedBtn = document.getElementById(`speed-${id}`);
    if (!audio || !speedBtn) return;
    
    let speed = parseFloat(audio.playbackRate);
    if (speed === 1.0) speed = 1.5;
    else if (speed === 1.5) speed = 2.0;
    else speed = 1.0;
    
    audio.playbackRate = speed;
    speedBtn.textContent = `${speed}x`;
};

// --- Message actions and reactions helpers ---
function closeAllActionMenus() {
    document.querySelectorAll('.message-actions-menu').forEach(m => m.remove());
}

function buildMessageActionsMenu(wrapperDiv, contentHtml, role) {
    const menu = document.createElement('div');
    // Positioning is handled by CSS: top:34px left:-34px relative to .message bubble
    menu.className = 'message-actions-menu';


    // Reaction bar
    const reactionBar = document.createElement('div');
    reactionBar.className = 'reaction-bar';
    const emojis = ['👍','❤️','😂','😮','😢','🙏'];
    emojis.forEach(e => {
        const btn = document.createElement('button');
        btn.className = 'reaction-pill';
        btn.textContent = e;
        btn.title = e;
        btn.onclick = (ev) => { ev.stopPropagation(); toggleReaction(wrapperDiv, e); menu.remove(); };
        reactionBar.appendChild(btn);
    });
    menu.appendChild(reactionBar);

    const t = translations[currentLang] || translations['en'];
    // Action list with icons (no Ask Meta AI)
    const actions = [
        { icon: '💬', text: t.reply    || 'Reply',    handler: replyMessage },
        { icon: '📋', text: t.copy     || 'Copy',     handler: copyMessage },
        { icon: '➡️', text: t.forward  || 'Forward',  handler: forwardMessage },
        { icon: '📌', text: t.pin      || 'Pin',      handler: pinMessage },
        { icon: '⭐', text: t.star     || 'Star',     handler: starMessage },
        { icon: '🌐', text: t.translate || 'Translate', handler: (w) => window.translateMessage(w) },
        { icon: '☑️', text: t.select   || 'Select',   handler: selectMessage },
        { icon: '⚠️', text: t.report   || 'Report',   handler: reportMessage },
        { icon: '🗑️', text: t.delete_action || 'Delete', handler: deleteMessage, danger: true }
    ];

    const list = document.createElement('div');
    list.className = 'message-actions-list';
    actions.forEach(a => {
        const item = document.createElement('div');
        item.className = a.danger ? 'message-action-item danger' : 'message-action-item';
        item.innerHTML = `<span class="action-icon">${a.icon}</span><span>${a.text}</span>`;
        item.onclick = (ev) => { ev.stopPropagation(); a.handler(wrapperDiv); closeAllActionMenus(); };
        list.appendChild(item);
    });
    menu.appendChild(list);

    // Click outside to close
    setTimeout(() => {
        document.addEventListener('click', function onDocClick(e) {
            if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener('click', onDocClick); }
        });
    }, 10);

    return menu;
}

function extractPlainTextFromMessage(wrapperDiv) {
    const content = wrapperDiv.querySelector('.message-content');
    if (!content) return '';
    return content.innerText || content.textContent || '';
}

function toggleReaction(wrapperDiv, emoji) {
    try {
        // Use stable reaction key (survives re-renders); fall back to old msgId-based key
        const reactionKey = wrapperDiv.dataset.reactionKey || `reactions-${wrapperDiv.dataset.msgId}` || '';
        let data = {};
        if (reactionKey) {
            const stored = localStorage.getItem(reactionKey);
            data = stored ? JSON.parse(stored) : (wrapperDiv.dataset.reactions ? JSON.parse(wrapperDiv.dataset.reactions) : {});
        } else {
            data = wrapperDiv.dataset.reactions ? JSON.parse(wrapperDiv.dataset.reactions) : {};
        }
        if (!data[emoji]) data[emoji] = 0;
        data[emoji] = data[emoji] > 0 ? 0 : 1;
        wrapperDiv.dataset.reactions = JSON.stringify(data);
        // Persist with stable key so it survives chat switches
        if (reactionKey) localStorage.setItem(reactionKey, JSON.stringify(data));
        renderReactionsUI(wrapperDiv, data);
    } catch (e) { console.error('toggleReaction', e); }
}

function renderReactionsUI(msgEl, data) {
    const messageBox = msgEl.querySelector('.message');
    if (!messageBox) return;

    let container = messageBox.querySelector('.reaction-badges');
    const activeEntries = Object.entries(data || {}).filter(([_, count]) => count && count > 0);

    if (activeEntries.length === 0) {
        if (container) {
            container.innerHTML = '';
            container.style.display = 'none';
        }
        msgEl.classList.remove('has-reactions');
        return;
    }

    if (!container) {
        const footer = messageBox.querySelector('.message-footer');
        container = document.createElement('div');
        container.className = 'reaction-badges';
        if (footer) {
            footer.insertBefore(container, footer.firstChild);
        } else {
            messageBox.appendChild(container);
        }
    }
    container.style.display = 'inline-flex';
    msgEl.classList.add('has-reactions');
    container.innerHTML = '';
    for (const [emoji, count] of activeEntries) {
        const span = document.createElement('span');
        span.className = 'reaction-badge';
        span.textContent = count > 1 ? `${emoji} ${count}` : `${emoji} 1`;
        span.title = `${emoji} (${count})`;
        span.onclick = (ev) => {
            ev.stopPropagation();
            toggleReaction(msgEl, emoji);
        };
        container.appendChild(span);
    }
}


// Action handlers
function replyMessage(wrapperDiv) {
    const txt = extractPlainTextFromMessage(wrapperDiv);
    const input = document.getElementById('message-input');
    if (!input) return;

    // Remove existing reply banner if any
    const existingBanner = document.getElementById('reply-banner');
    if (existingBanner) existingBanner.remove();

    // Build contextual reply banner above the input area
    const inputArea = input.closest('.input-area') || input.parentElement;
    if (inputArea) {
        const banner = document.createElement('div');
        banner.id = 'reply-banner';
        banner.className = 'reply-banner';
        const preview = txt.length > 80 ? txt.substring(0, 80) + '...' : txt;
        banner.innerHTML = `
            <span class="reply-banner-icon">💬</span>
            <div class="reply-banner-text">
                <span class="reply-banner-label">${translations[currentLang]?.reply || 'Reply'}</span>
                <span class="reply-banner-preview">${preview}</span>
            </div>
            <button class="reply-banner-close" onclick="document.getElementById('reply-banner')?.remove()" title="Cancel">&#x2715;</button>
        `;
        inputArea.insertBefore(banner, inputArea.firstChild);
    }
    input.focus();
}

function copyMessage(wrapperDiv) {
    const txt = extractPlainTextFromMessage(wrapperDiv);
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(txt).then(() => {
            showTemporaryToast('Copied to clipboard');
        }).catch(() => { alert('Copied: ' + txt); });
    } else {
        alert(txt);
    }
}

function forwardMessage(wrapperDiv) {
    const txt = extractPlainTextFromMessage(wrapperDiv);
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(txt).then(() => {
            showTemporaryToast(translations[currentLang]?.copied_forward || 'Copied — paste to forward');
        });
    } else {
        showTemporaryToast(translations[currentLang]?.copied_forward || 'Copied — paste to forward');
    }
}

// ── PIN MESSAGE ──────────────────────────────────────────────────────────────
function pinMessage(wrapperDiv) {
    const t = translations[currentLang] || translations['en'];
    const isPinned = wrapperDiv.classList.toggle('pinned');
    const text = extractPlainTextFromMessage(wrapperDiv);
    const preview = text.length > 60 ? text.slice(0, 60) + '...' : text;
    const pinKey = `pinned-${currentProvider}`;

    if (isPinned) {
        localStorage.setItem(pinKey, preview);
        showTemporaryToast(t.pin_banner_label || 'Pinned');
    } else {
        localStorage.removeItem(pinKey);
        showTemporaryToast(t.unpin || 'Unpinned');
    }
    window.refreshPinBanner();
}

window.refreshPinBanner = function() {
    const t = translations[currentLang] || translations['en'];
    const pinKey = `pinned-${currentProvider}`;
    const pinned = localStorage.getItem(pinKey);
    let banner = document.getElementById('pin-banner');

    if (pinned) {
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'pin-banner';
            banner.className = 'pin-banner';
            const header = document.getElementById('header');
            if (header && header.nextSibling) {
                header.parentNode.insertBefore(banner, header.nextSibling);
            }
        }
        banner.innerHTML = `
            <div class="pin-banner-inner">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M17 4v7l2 3H5l2-3V4h10m0-2H7c-.55 0-1 .45-1 1v9L4 15v1h7v5l1 1 1-1v-5h7v-1l-2-3V3c0-.55-.45-1-1-1z"/></svg>
                <span class="pin-banner-label">${t.pin_banner_label || 'Pinned message'}</span>
                <span class="pin-banner-text">${pinned}</span>
                <button class="pin-banner-close" onclick="(function(){localStorage.removeItem('${`pinned-${currentProvider}`}'); document.getElementById('pin-banner')?.remove(); document.querySelectorAll('.pinned').forEach(el=>el.classList.remove('pinned'));})()" title="${t.unpin || 'Unpin'}">&times;</button>
            </div>
        `;
    } else if (banner) {
        banner.remove();
    }
};

// ── STAR MESSAGE ─────────────────────────────────────────────────────────────
function starMessage(wrapperDiv) {
    const t = translations[currentLang] || translations['en'];
    const isStarred = wrapperDiv.classList.toggle('starred');
    const text = extractPlainTextFromMessage(wrapperDiv);
    const timeStr = wrapperDiv.dataset.reactionKey || wrapperDiv.dataset.msgId || '';
    const starKey = `starred-${currentProvider}`;

    let starred = JSON.parse(localStorage.getItem(starKey) || '[]');
    if (isStarred) {
        starred.push({ text, key: timeStr, ts: Date.now() });
        showTemporaryToast('⭐ ' + (t.star || 'Starred'));
    } else {
        starred = starred.filter(s => s.key !== timeStr);
        showTemporaryToast(t.unstar || 'Unstarred');
    }
    localStorage.setItem(starKey, JSON.stringify(starred));
}

window.openStarredPanel = function() {
    const t = translations[currentLang] || translations['en'];
    const starKey = `starred-${currentProvider}`;
    const starred = JSON.parse(localStorage.getItem(starKey) || '[]');

    const existing = document.getElementById('starred-panel');
    if (existing) { existing.remove(); return; }

    const panel = document.createElement('div');
    panel.id = 'starred-panel';
    panel.className = 'starred-panel';

    let itemsHtml = starred.length === 0
        ? `<div class="starred-empty">${t.starred_panel_empty || 'No starred messages yet.'}</div>`
        : starred.map(s => `
            <div class="starred-item">
                <span class="starred-item-icon">⭐</span>
                <span class="starred-item-text">${s.text.slice(0,120)}${s.text.length > 120 ? '...' : ''}</span>
            </div>`).join('');

    panel.innerHTML = `
        <div class="starred-panel-header">
            <span>${t.starred_panel_title || 'Starred Messages'}</span>
            <button class="starred-panel-close" onclick="document.getElementById('starred-panel')?.remove()">&times;</button>
        </div>
        <div class="starred-panel-list">${itemsHtml}</div>
    `;
    document.getElementById('main-area')?.appendChild(panel);
};

// ── SELECT MESSAGE (multi-select mode) ───────────────────────────────────────
function selectMessage(wrapperDiv) {
    wrapperDiv.classList.toggle('selected');
    window.updateSelectActionBar();
}

window.updateSelectActionBar = function() {
    const selected = document.querySelectorAll('.message-wrapper.selected');
    let bar = document.getElementById('select-action-bar');
    const t = translations[currentLang] || translations['en'];

    if (selected.length === 0) {
        if (bar) bar.remove();
        return;
    }
    if (!bar) {
        bar = document.createElement('div');
        bar.id = 'select-action-bar';
        bar.className = 'select-action-bar';
        document.getElementById('input-container')?.prepend(bar);
    }
    bar.innerHTML = `
        <span class="select-count">${selected.length} selected</span>
        <button class="select-action-btn" onclick="window.copySelectedMessages()">${t.copy_selected || 'Copy'}</button>
        <button class="select-action-btn danger" onclick="window.deleteSelectedMessages()">${t.delete_selected || 'Delete'}</button>
        <button class="select-action-btn cancel" onclick="window.cancelSelectMode()">${t.cancel_select || 'Cancel'}</button>
    `;
};

window.copySelectedMessages = function() {
    const selected = [...document.querySelectorAll('.message-wrapper.selected')];
    const text = selected.map(w => extractPlainTextFromMessage(w)).join('\n---\n');
    navigator.clipboard?.writeText(text).then(() => showTemporaryToast('Copied'));
    window.cancelSelectMode();
};

window.deleteSelectedMessages = function() {
    const t = translations[currentLang] || translations['en'];
    if (!confirm(t.confirm_delete || 'Delete selected messages?')) return;
    document.querySelectorAll('.message-wrapper.selected').forEach(w => w.remove());
    window.cancelSelectMode();
};

window.cancelSelectMode = function() {
    document.querySelectorAll('.message-wrapper.selected').forEach(w => w.classList.remove('selected'));
    document.getElementById('select-action-bar')?.remove();
};

function reportMessage(wrapperDiv) {
    const txt = extractPlainTextFromMessage(wrapperDiv);
    if (window.pywebview && window.pywebview.api && window.pywebview.api.report_message) {
        window.pywebview.api.report_message(txt).then(() => showTemporaryToast('Reported')).catch(() => showTemporaryToast('Report failed'));
    } else {
        showTemporaryToast('Reported');
        console.log('Report (no backend):', txt);
    }
}

function deleteMessage(wrapperDiv) {
    const t = translations[currentLang] || translations['en'];
    const confirmText = t.confirm_delete || 'Delete this message?';
    const yesText = t.delete_action || 'Delete';
    const noText = t.cancel || 'Cancel';

    // Custom inline confirm dialog (avoids native confirm() which may fail in webview)
    const existing = document.getElementById('delete-confirm-dialog');
    if (existing) existing.remove();

    const dialog = document.createElement('div');
    dialog.id = 'delete-confirm-dialog';
    dialog.className = 'delete-confirm-dialog';
    dialog.innerHTML = `
        <span class="delete-confirm-text">${confirmText}</span>
        <div class="delete-confirm-btns">
            <button class="delete-confirm-btn cancel" id="del-cancel-btn">${noText}</button>
            <button class="delete-confirm-btn confirm" id="del-confirm-btn">${yesText}</button>
        </div>
    `;
    document.body.appendChild(dialog);

    document.getElementById('del-cancel-btn').onclick = () => dialog.remove();
    document.getElementById('del-confirm-btn').onclick = () => {
        dialog.remove();
        wrapperDiv.remove();
        // Clear using stable reaction key
        const reactionKey = wrapperDiv.dataset.reactionKey || (wrapperDiv.dataset.msgId ? `reactions-${wrapperDiv.dataset.msgId}` : null);
        if (reactionKey) localStorage.removeItem(reactionKey);
        if (window.pywebview && window.pywebview.api && window.pywebview.api.delete_message) {
            const txt = extractPlainTextFromMessage(wrapperDiv);
            window.pywebview.api.delete_message(txt).catch(() => {});
        }
    };

    // Auto-close if user clicks outside
    setTimeout(() => {
        document.addEventListener('click', function onOutside(e) {
            if (!dialog.contains(e.target)) { dialog.remove(); document.removeEventListener('click', onOutside); }
        });
    }, 10);
}

function showTemporaryToast(text, timeout=1200, options) {
    try {
        const existing = document.getElementById('temp-toast');
        if (existing) existing.remove();
        const t = document.createElement('div');
        t.id = 'temp-toast';
        t.className = (options && options.multiline) ? 'temp-toast temp-toast-multiline' : 'temp-toast';
        t.textContent = text;
        document.body.appendChild(t);
        setTimeout(() => t.remove(), timeout);
    } catch(e) { console.log(text); }
}

window.seekVoice = function(event, id) {
    const audio = document.getElementById(`audio-${id}`);
    const container = event.currentTarget;
    if (!audio || !container) return;
    
    const rect = container.getBoundingClientRect();
    const clickX = event.clientX - rect.left;
    const width = rect.width;
    const percent = clickX / width;
    
    if (audio.duration) {
        audio.currentTime = percent * audio.duration;
    }
};

// Function to update notification bell badge and dropdown items
function updateNotificationBell() {
    const badge = document.getElementById('notification-badge');
    const dropdown = document.getElementById('notification-dropdown');

    let totalUnreadMessages = 0;
    const groupProviders = Object.keys(window.customGroups || {});
    const providers = [...baseProviders, ...groupProviders];
    
    // Clear unread count for the active provider
    unreadCounts[currentProvider] = 0;

    providers.forEach(p => {
        if (unreadCounts[p] > 0) {
            totalUnreadMessages += unreadCounts[p];
        }
    });

    if (badge) {
        if (totalUnreadMessages > 0) {
            badge.textContent = totalUnreadMessages;
            badge.classList.add('visible');
        } else {
            badge.textContent = '0';
            badge.classList.remove('visible');
        }
    }

    // Populate dropdown
    const t = translations[currentLang] || translations['en'];
    const titleText = currentLang === 'es' ? 'Mensajes no leídos' : 'Unread Messages';
    const noNotificationsText = currentLang === 'es' ? 'No hay mensajes nuevos' : 'No new messages';

    let dropdownHtml = `<div class="dropdown-header">${titleText}</div>`;
    let hasUnread = false;

    providers.forEach(p => {
        const count = unreadCounts[p] || 0;

        // Update sidebar badge
        const sidebarBadge = document.getElementById(`sidebar-badge-${p}`);
        if (sidebarBadge) {
            if (count > 0) {
                sidebarBadge.textContent = count;
                sidebarBadge.classList.remove('hidden');
            } else {
                sidebarBadge.textContent = '0';
                sidebarBadge.classList.add('hidden');
            }
        }

        if (count > 0) {
            hasUnread = true;
            let avatarHtml = getAvatarHtml(p, true);
            let displayProvider = p.toUpperCase();
            let color = '#3186FF';
            if (p.startsWith('group_')) {
                const g = window.customGroups[p];
                displayProvider = g ? g.name : 'AI Group';
                color = '#128C7E';
            } else {
                if (p === 'DeepSeek') color = '#4C6BFE';
                else if (p === 'OpenAI') color = '#10a37f';
                else if (p === 'Anthropic') color = '#cc785c';
                else if (p === 'Perplexity') color = '#19a3b8';
                else if (p === 'Grok') color = '#09090B';
            }

            dropdownHtml += `
                <div class="notification-item" onclick="switchToProviderFromNotification('${p}')">
                    <div class="notification-item-name">
                        <div class="notification-item-avatar">${avatarHtml}</div>
                        <span style="color: ${color}; font-weight: bold;">${displayProvider}</span>
                    </div>
                    <span class="notification-item-count">${count}</span>
                </div>
            `;
        }
    });

    if (!hasUnread) {
        dropdownHtml += `<div class="notification-empty">${noNotificationsText}</div>`;
    }

    if (dropdown) {
        dropdown.innerHTML = dropdownHtml;
    }
}

// Function to switch provider when a notification item is clicked
window.switchToProviderFromNotification = function(provider) {
    // 1. Close dropdown
    const dropdown = document.getElementById('notification-dropdown');
    if (dropdown) dropdown.classList.add('hidden');

    // 2. Clear unread count
    unreadCounts[provider] = 0;
    updateNotificationBell();

    // 3. Update sidebar radio checked status
    const radios = document.getElementsByName('provider');
    for (let i = 0; i < radios.length; i++) {
        if (radios[i].value === provider) {
            radios[i].checked = true;
            // Trigger change event to load provider
            const event = new Event('change');
            radios[i].dispatchEvent(event);
            break;
        }
    }
};

// Select provider and trigger change event
window.selectProvider = function(provider) {
    const radio = document.getElementById(`radio-${provider}`);
    if (radio && !radio.checked) {
        radio.checked = true;
        const event = new Event('change');
        radio.dispatchEvent(event);
    }
    const appContainer = document.getElementById('app-container');
    if (appContainer) {
        appContainer.classList.remove('chat-collapsed');
    }
};

// Update preview row for an AI provider in the chats sidebar
window.updateChatListItem = function(provider, lastMsg) {
    const timeEl = document.getElementById(`chat-item-time-${provider}`);
    const msgEl = document.getElementById(`chat-item-last-msg-${provider}`);
    if (!timeEl || !msgEl) return;

    if (lastMsg) {
        timeEl.textContent = window.formatMessageTimestamp(lastMsg.timestamp, lastMsg) || '';
        let prefix = '';
        if (lastMsg.role === 'user') {
            prefix = currentLang === 'es' ? 'Tú: ' : 'You: ';
        }
        
        let content = lastMsg.content || '';
        if (content.includes('🖼️ **Generated image**') || content.includes('Generated image')) {
            content = currentLang === 'es' ? '🖼️ Imagen' : '🖼️ Image';
        } else if (content.includes('🎵 **Generated audio**') || content.includes('Generated audio')) {
            content = currentLang === 'es' ? '🎵 Audio' : '🎵 Audio';
        } else if (lastMsg.is_voice || lastMsg.from_mic || content.includes('Voice Message') || content.includes('Voice_Message_')) {
            content = currentLang === 'es' ? '🎙️ Mensaje de voz' : '🎙️ Voice message';
        }
        
        // Strip markdown if needed or just display first few characters
        let displayContent = content.replace(/[*#`_\-]/g, '').trim();
        if (displayContent.length > 28) {
            displayContent = displayContent.substring(0, 28) + '...';
        }
        msgEl.textContent = prefix + displayContent;
    } else {
        timeEl.textContent = '';
        msgEl.textContent = currentLang === 'es' ? 'Haz clic para chatear' : 'Click to start chatting';
    }
};

// ============================================================================
// MESSAGE SEARCH & CONTACT DROPDOWN / BLOCK FUNCTIONALITY
// ============================================================================

let currentSearchMatches = [];
let currentSearchIndex = -1;

function escapeRegExp(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function removeHighlights(rootElement) {
    const marks = rootElement.querySelectorAll('mark.search-highlight');
    marks.forEach(mark => {
        const parent = mark.parentNode;
        if (parent) {
            const textNode = document.createTextNode(mark.textContent);
            parent.replaceChild(textNode, mark);
            parent.normalize();
        }
    });
}

function highlightSearchTerm(rootElement, term) {
    removeHighlights(rootElement);
    if (!term || term.trim() === "") return [];
    
    const walker = document.createTreeWalker(rootElement, NodeFilter.SHOW_TEXT, null, false);
    const textNodes = [];
    let node;
    while (node = walker.nextNode()) {
        const parent = node.parentNode;
        if (parent && (parent.parentNode && (parent.tagName === 'SCRIPT' || parent.tagName === 'STYLE' || parent.classList.contains('search-highlight')))) {
            continue;
        }
        textNodes.push(node);
    }
    
    const matches = [];
    const escapedTerm = escapeRegExp(term);
    const regex = new RegExp(`(${escapedTerm})`, 'gi');
    
    for (let i = textNodes.length - 1; i >= 0; i--) {
        const textNode = textNodes[i];
        const parent = textNode.parentNode;
        if (!parent) continue;
        
        const text = textNode.nodeValue;
        if (regex.test(text)) {
            const fragment = document.createDocumentFragment();
            let lastIndex = 0;
            text.replace(regex, (match, p1, index) => {
                if (index > lastIndex) {
                    fragment.appendChild(document.createTextNode(text.substring(lastIndex, index)));
                }
                const mark = document.createElement('mark');
                mark.className = 'search-highlight';
                mark.textContent = match;
                fragment.appendChild(mark);
                matches.push(mark);
                lastIndex = index + match.length;
            });
            if (lastIndex < text.length) {
                fragment.appendChild(document.createTextNode(text.substring(lastIndex)));
            }
            parent.replaceChild(fragment, textNode);
        }
    }
    return matches.reverse();
}

window.openSearch = function() {
    const searchBar = document.getElementById('message-search-bar');
    if (searchBar) {
        searchBar.classList.remove('hidden-search');
    }
    const input = document.getElementById('message-search-input');
    if (input) {
        input.value = "";
        input.focus();
    }
    window.updateSearchUI();
};

window.closeSearch = function() {
    const searchBar = document.getElementById('message-search-bar');
    if (searchBar) {
        searchBar.classList.add('hidden-search');
    }
    const input = document.getElementById('message-search-input');
    if (input) {
        input.value = "";
    }
    const chatContainer = document.getElementById('chat-container');
    if (chatContainer) {
        removeHighlights(chatContainer);
    }
    currentSearchMatches = [];
    currentSearchIndex = -1;
};

window.updateSearchUI = function() {
    const badge = document.getElementById('message-search-count');
    const input = document.getElementById('message-search-input');
    if (badge && input) {
        const query = input.value;
        if (!query) {
            badge.textContent = "";
        } else if (currentSearchMatches.length > 0) {
            badge.textContent = `${currentSearchIndex + 1} / ${currentSearchMatches.length}`;
        } else {
            const t = (typeof translations !== 'undefined' && translations[currentLang]) ? translations[currentLang] : null;
            badge.textContent = (t && t.no_matches) ? t.no_matches : (currentLang === 'es' ? "Sin coincidencias" : "No matches");
        }
    }
};

window.scrollToMatch = function(index) {
    currentSearchMatches.forEach(m => m.classList.remove('active-highlight'));
    if (index >= 0 && index < currentSearchMatches.length) {
        const activeMark = currentSearchMatches[index];
        activeMark.classList.add('active-highlight');
        activeMark.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
};

window.nextSearchMatch = function() {
    if (currentSearchMatches.length === 0) return;
    currentSearchIndex = (currentSearchIndex + 1) % currentSearchMatches.length;
    window.updateSearchUI();
    window.scrollToMatch(currentSearchIndex);
};

window.prevSearchMatch = function() {
    if (currentSearchMatches.length === 0) return;
    currentSearchIndex = (currentSearchIndex - 1 + currentSearchMatches.length) % currentSearchMatches.length;
    window.updateSearchUI();
    window.scrollToMatch(currentSearchIndex);
};

window.onSearchInput = function() {
    const input = document.getElementById('message-search-input');
    const query = input ? input.value : "";
    const chatContainer = document.getElementById('chat-container');
    
    if (chatContainer) {
        currentSearchMatches = highlightSearchTerm(chatContainer, query);
    }
    
    if (currentSearchMatches.length > 0) {
        currentSearchIndex = 0;
        window.updateSearchUI();
        window.scrollToMatch(currentSearchIndex);
    } else {
        currentSearchIndex = -1;
        window.updateSearchUI();
    }
};

// Block Contact logic
window.toggleBlockProvider = function(provider) {
    if (typeof blockedProviders === 'undefined') return;
    blockedProviders[provider] = !blockedProviders[provider];
    window.updateBlockUI();
};

window.updateBlockUI = function() {
    if (typeof blockedProviders === 'undefined') return;
    const blocked = blockedProviders[currentProvider];
    const msgInput = document.getElementById('message-input');
    const micBtn = document.getElementById('mic-btn');
    const sendBtn = document.getElementById('send-btn');
    const blockItem = document.getElementById('menu-block');
    
    // Remove existing block system message if any
    const existingMsg = document.getElementById('block-system-msg');
    if (existingMsg) existingMsg.remove();
    
    if (blocked) {
        // Disable input
        if (msgInput) {
            msgInput.disabled = true;
            msgInput.value = "";
            msgInput.placeholder = currentLang === 'es' ? 
                `Desbloquea a ${currentProvider} para enviar un mensaje` : 
                `Unblock ${currentProvider} to send a message`;
        }
        if (micBtn) {
            micBtn.style.opacity = '0.3';
            micBtn.style.pointerEvents = 'none';
        }
        if (sendBtn) {
            sendBtn.style.opacity = '0.3';
            sendBtn.style.pointerEvents = 'none';
        }
        if (blockItem) {
            blockItem.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="16" height="16"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg> ${currentLang === 'es' ? 'Desbloquear' : 'Unblock'}`;
        }
        
        // Append blocked message system indicator at the bottom of chat container
        const chatContainer = document.getElementById('chat-container');
        if (chatContainer) {
            const blockDiv = document.createElement('div');
            blockDiv.id = 'block-system-msg';
            blockDiv.className = 'chat-system-message';
            blockDiv.style.textAlign = 'center';
            blockDiv.style.margin = '15px auto';
            blockDiv.style.padding = '8px 16px';
            blockDiv.style.borderRadius = '8px';
            blockDiv.style.backgroundColor = 'rgba(0, 0, 0, 0.25)';
            blockDiv.style.color = '#ff6b6b';
            blockDiv.style.fontSize = '13px';
            blockDiv.style.maxWidth = 'fit-content';
            blockDiv.innerHTML = currentLang === 'es' ? 
                `Bloqueaste a este contacto. Haz clic para <a href="#" id="system-unblock-link" style="color: #ff6b6b; font-weight: bold; text-decoration: underline;">desbloquear</a>.` : 
                `You blocked this contact. Tap to <a href="#" id="system-unblock-link" style="color: #ff2b55; font-weight: bold; text-decoration: underline;">unblock</a>.`;
            chatContainer.appendChild(blockDiv);
            
            // Bind unblock click
            const link = document.getElementById('system-unblock-link');
            if (link) {
                link.addEventListener('click', (e) => {
                    e.preventDefault();
                    window.toggleBlockProvider(currentProvider);
                });
            }
            scrollToBottom(true);
        }
    } else {
        // Enable input
        if (msgInput) {
            msgInput.disabled = false;
            const t = translations[currentLang] || translations['en'];
            msgInput.placeholder = t.ask;
        }
        if (micBtn) {
            micBtn.style.opacity = '1';
            micBtn.style.pointerEvents = 'auto';
        }
        if (sendBtn) {
            sendBtn.style.opacity = '1';
            sendBtn.style.pointerEvents = 'auto';
        }
        if (blockItem) {
            blockItem.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="16" height="16"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg> ${currentLang === 'es' ? 'Bloquear' : 'Block'}`;
        }
    }
};

window.openAttachmentFile = function(element) {
    const filepath = element.getAttribute('data-path');
    if (!filepath) return;
    
    // Visually indicate opening
    const originalOpacity = element.style.opacity;
    element.style.opacity = '0.4';
    element.style.pointerEvents = 'none';
    
    window.pywebview.api.open_file_path(filepath)
        .then(res => {
            element.style.opacity = originalOpacity || '1';
            element.style.pointerEvents = 'auto';
            if (res.status === 'error') {
                alert(`Error opening file: ${res.message}`);
            }
        })
        .catch(err => {
            element.style.opacity = originalOpacity || '1';
            element.style.pointerEvents = 'auto';
            console.error('Error opening file:', err);
        });
};

// ─────────────────────────────────────────────────────────────────────────────
// TRANSLATE MESSAGE
// ─────────────────────────────────────────────────────────────────────────────
window.translateMessage = function(wrapperDiv) {
    const t = translations[currentLang] || translations['en'];
    const content = wrapperDiv.querySelector('.message-content');
    if (!content) return;
    const originalHtml = content.innerHTML;
    const originalText = content.innerText || content.textContent || '';
    const targetLang = currentLang === 'es' ? 'English' : 'Spanish';
    content.innerHTML = '<em style="opacity:0.6">' + (t.translating || 'Translating...') + '</em>';
    if (window.pywebview && window.pywebview.api && window.pywebview.api.translate_message) {
        window.pywebview.api.translate_message(originalText, targetLang).then(res => {
            if (res && res.translation) {
                content.innerHTML = window.marked ? window.marked.parse(res.translation) : res.translation;
                let badge = wrapperDiv.querySelector('.translated-badge');
                if (!badge) {
                    badge = document.createElement('span');
                    badge.className = 'translated-badge';
                    badge.textContent = '\uD83C\uDF10 ' + targetLang;
                    wrapperDiv.querySelector('.message')?.appendChild(badge);
                }
            } else { content.innerHTML = originalHtml; showTemporaryToast('Translation failed'); }
        }).catch(() => { content.innerHTML = originalHtml; showTemporaryToast('Translation error'); });
    } else { content.innerHTML = originalHtml; showTemporaryToast('Translation not available'); }
};

// ─────────────────────────────────────────────────────────────────────────────
// SUMMARIZE CHAT
// ─────────────────────────────────────────────────────────────────────────────
window.summarizeChat = function() {
    const t = translations[currentLang] || translations['en'];
    showTemporaryToast(t.summarizing || 'Summarizing...', 3000);
    if (window.pywebview && window.pywebview.api && window.pywebview.api.summarize_chat) {
        window.pywebview.api.summarize_chat(currentLang).then(res => {
            if (res && res.summary) {
                const chatContainer = document.getElementById('chat-container');
                if (!chatContainer) return;
                const summaryDiv = document.createElement('div');
                summaryDiv.className = 'summary-bubble';
                const parsed = window.marked ? window.marked.parse(res.summary) : res.summary;
                summaryDiv.innerHTML = '<div class="summary-bubble-header"><span>' + (t.summary_title || '\uD83D\uDCCB Conversation Summary') + '</span><button class="summary-close-btn" onclick="this.closest(\'.summary-bubble\').remove()">&times;</button></div><div class="summary-content">' + parsed + '</div>';
                chatContainer.appendChild(summaryDiv);
                summaryDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
            } else { showTemporaryToast('Summary failed'); }
        }).catch(() => showTemporaryToast('Summary error'));
    } else { showTemporaryToast('Summary not available'); }
};

// ─────────────────────────────────────────────────────────────────────────────
// EXPORT CHAT TXT
// ─────────────────────────────────────────────────────────────────────────────
window.exportChatTxt = function() {
    const t = translations[currentLang] || translations['en'];
    const wrappers = document.querySelectorAll('.message-wrapper');
    if (!wrappers.length) { showTemporaryToast('No messages to export'); return; }
    const lines = ['=== ' + currentProvider + ' Chat Export ===\n'];
    wrappers.forEach(w => {
        const role = w.classList.contains('user') ? 'You' : currentProvider;
        const text = extractPlainTextFromMessage(w) || '';
        const time = w.querySelector('.message-timestamp')?.textContent || '';
        lines.push('[' + time + '] ' + role + ':\n' + text + '\n');
    });
    const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = currentProvider + '_chat_' + new Date().toISOString().slice(0,10) + '.txt';
    a.click();
    URL.revokeObjectURL(url);
    showTemporaryToast(t.export_done || 'Chat exported!');
};

// ─────────────────────────────────────────────────────────────────────────────
// DISAPPEARING MESSAGES
// ─────────────────────────────────────────────────────────────────────────────
window.openDisappearingModal = function() {
    const t = translations[currentLang] || translations['en'];
    const key = 'disappearing-' + currentProvider;
    const raw = localStorage.getItem(key);
    const current = raw ? (JSON.parse(raw).value || 'off') : 'off';
    document.getElementById('disappearing-modal')?.remove();
    const options = [
        { value: 'off', label: t.disappearing_off || 'Off' },
        { value: '24h', label: t.disappearing_24h || '24 hours' },
        { value: '7d',  label: t.disappearing_7d  || '7 days' },
        { value: '90d', label: t.disappearing_90d || '90 days' }
    ];
    const modal = document.createElement('div');
    modal.id = 'disappearing-modal';
    modal.className = 'disappearing-modal';
    modal.innerHTML = '<div class="disappearing-modal-inner"><div class="disappearing-modal-header"><span>\u23F1\uFE0F ' + (t.disappearing_title || 'Disappearing Messages') + '</span><button onclick="document.getElementById(\'disappearing-modal\')?.remove()">&times;</button></div>' + options.map(o => '<label class="disappearing-option' + (current === o.value ? ' active' : '') + '"><input type="radio" name="disappearing-opt" value="' + o.value + '" ' + (current === o.value ? 'checked' : '') + '> ' + o.label + '</label>').join('') + '<button class="disappearing-save-btn" onclick="window.saveDisappearing()">OK</button></div>';
    document.getElementById('main-area')?.appendChild(modal);
};

window.saveDisappearing = function() {
    const key = 'disappearing-' + currentProvider;
    const selected = document.querySelector('input[name="disappearing-opt"]:checked');
    if (!selected) return;
    const val = selected.value;
    if (val === 'off') { localStorage.removeItem(key); }
    else { const durations = { '24h': 86400000, '7d': 604800000, '90d': 7776000000 }; localStorage.setItem(key, JSON.stringify({ value: val, setAt: Date.now(), durationMs: durations[val] })); }
    document.getElementById('disappearing-modal')?.remove();
    showTemporaryToast('Saved');
    window.applyDisappearingMessages();
};

window.applyDisappearingMessages = function() {
    const key = 'disappearing-' + currentProvider;
    const raw = localStorage.getItem(key);
    if (!raw) return;
    try {
        const config = JSON.parse(raw);
        if (!config || !config.durationMs) return;
        const cutoff = config.setAt + config.durationMs;
        document.querySelectorAll('.message-wrapper').forEach(w => {
            const msgTs = parseInt(w.dataset.ts || '0');
            if (msgTs && msgTs < cutoff) w.remove();
        });
    } catch(e) {}
};

// ─────────────────────────────────────────────────────────────────────────────
// ARCHIVE / UNARCHIVE CHAT
// ─────────────────────────────────────────────────────────────────────────────
window.archiveChat = function(provider) {
    const t = translations[currentLang] || translations['en'];
    provider = provider || currentProvider;
    const archiveKey = 'archived-chats';
    let archived = JSON.parse(localStorage.getItem(archiveKey) || '[]');
    if (!archived.includes(provider)) { archived.push(provider); localStorage.setItem(archiveKey, JSON.stringify(archived)); showTemporaryToast(t.archive || 'Archived'); }
    const item = document.querySelector('.chat-item[data-provider="' + provider + '"]');
    if (item) item.style.display = 'none';
};

window.openArchivedPanel = function() {
    const t = translations[currentLang] || translations['en'];
    const archiveKey = 'archived-chats';
    const archived = JSON.parse(localStorage.getItem(archiveKey) || '[]');
    document.getElementById('archived-panel')?.remove();
    const panel = document.createElement('div');
    panel.id = 'archived-panel';
    panel.className = 'archived-panel';
    const itemsHtml = archived.length === 0 ? '<div class="archived-empty">' + (t.archived_empty || 'No archived chats.') + '</div>' : archived.map(p => '<div class="archived-item" onclick="window.unarchiveChat(\'' + p + '\')"><span class="archived-item-name">' + p + '</span><span class="archived-item-action">' + (t.unarchive || 'Unarchive') + '</span></div>').join('');
    panel.innerHTML = '<div class="archived-panel-header"><span>\uD83D\uDCC2 ' + (t.archived_title || 'Archived') + '</span><button onclick="document.getElementById(\'archived-panel\')?.remove()">&times;</button></div><div class="archived-panel-list">' + itemsHtml + '</div>';
    document.getElementById('chats-sidebar-panel')?.appendChild(panel);
};

window.unarchiveChat = function(provider) {
    const archiveKey = 'archived-chats';
    let archived = JSON.parse(localStorage.getItem(archiveKey) || '[]');
    archived = archived.filter(p => p !== provider);
    localStorage.setItem(archiveKey, JSON.stringify(archived));
    const item = document.querySelector('.chat-item[data-provider="' + provider + '"]');
    if (item) item.style.display = '';
    document.getElementById('archived-panel')?.remove();
    showTemporaryToast('Unarchived');
};



// app/frontend/audio.js
// Logic for speech recording (Microphone) with automated silence-submission loop and Web Speech synthesis

let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let currentUtterance = null;
let ttsSessionId = 0;
// Chat that started the current TTS: completion must not mutate whichever
// chat the user switched to mid-playback.
let ttsOwnerProvider = null;
let cartesiaAudioPlayer = null;
let recordTimer = null; // max recording duration limit

// Silence timer and VAD tracking variables
let silenceTimer = null;
let countdownInterval = null;
let volumeInterval = null;
let audioContext = null;
let analyser = null;
let hasSpoken = false;
let voiceLoopActive = false;
let micStream = null;
let lastSilenceResetTime = 0;
let micMuted = false;

// Silence VAD configuration (replicating Streamlit mic_injector.py)
const SILENCE_TIMEOUT_LONG  = 3000; // ms — wait time during phrase pauses
const SILENCE_TIMEOUT_SHORT = 1800; // ms — wait time after complete sentence (isFinal)
const RMS_THRESHOLD = 0.03;         // volume threshold for voice activity detection
const TTS_TARGET_FIRST_PLAY_MS = 150; // README target for first-sentence play start
const MIC_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="white" style="display:block;"><path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2z"/></svg>';
const MIC_OFF_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="white" style="display:block;"><path d="M19 11h-1.7a5.17 5.17 0 0 1-.3 1.7l1.3 1.3A6.9 6.9 0 0 0 19 11zm-4.2.8L7.1 4.1A3 3 0 0 1 12 5v.2l2.8 2.8V11a2.94 2.94 0 0 1-.2.8zM4.3 3L3 4.3l5.2 5.2A4.9 4.9 0 0 0 7 11H5a7 7 0 0 0 6 6.92V21h2v-3.08a6.9 6.9 0 0 0 2.6-.9L19.7 21 21 19.7 4.3 3z"/></svg>';

// Module-level helper — restarts mic if the voice loop is still active
function checkAndRestartVoiceLoop() {
    if (voiceLoopActive) {
        setTimeout(() => {
            if (voiceLoopActive && !isRecording) {
                startRecording();
            }
        }, 300);
    }
}

// HTML template parts for floating UI
const WAVE_HTML = '<div class="audio-wave"><span class="bar"></span><span class="bar"></span><span class="bar"></span><span class="bar"></span><span class="bar"></span></div>';
const TRASH_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="white" style="display:block;"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>';

function setMicMuted(muted) {
    micMuted = !!muted;
    if (micStream) {
        micStream.getAudioTracks().forEach((track) => {
            track.enabled = !micMuted;
        });
    }
    const muteBtn = document.getElementById('stMuteMicBtn');
    if (muteBtn) {
        muteBtn.innerHTML = micMuted ? MIC_OFF_SVG : MIC_SVG;
        muteBtn.title = micMuted
            ? (currentLang === 'es' ? 'Activar micrófono' : 'Unmute mic')
            : (currentLang === 'es' ? 'Silenciar micrófono' : 'Mute mic');
        muteBtn.classList.toggle('is-muted', micMuted);
    }
    const hud = document.getElementById('stListeningMsg');
    if (hud && isRecording) {
        const txtSpan = hud.querySelector('#stMicStatusText');
        if (micMuted) {
            hud.className = 'st-msg-muted';
            if (txtSpan) txtSpan.textContent = currentLang === 'es' ? 'Silenciado...' : 'Muted...';
        }
    }
}

function updateHudWaveBars(rms) {
    const hud = document.getElementById('stListeningMsg');
    if (!hud) return;
    const bars = hud.querySelectorAll('.audio-wave .bar');
    if (!bars.length) return;
    // Map RMS to bar heights; keep a small floor so the wave stays visible.
    const level = micMuted ? 0 : Math.min(1, rms / 0.12);
    bars.forEach((bar, idx) => {
        const weight = 0.45 + ((idx % 3) * 0.2);
        const px = 4 + Math.round(level * 14 * weight);
        bar.style.animation = 'none';
        bar.style.height = `${px}px`;
        bar.style.opacity = micMuted ? '0.45' : '1';
    });
}

// Create the floating listening status bar dynamically on load
function initAudioHUD() {
    if (document.getElementById('stListeningMsg')) return;
    const hud = document.createElement('div');
    hud.id = 'stListeningMsg';
    hud.className = 'st-msg-speaking';
    hud.innerHTML = WAVE_HTML
        + '<span id="stMicStatusText" style="margin: 0 10px;">Listening...</span>'
        + WAVE_HTML
        + `<button id="stMuteMicBtn" type="button" title="Mute mic">${MIC_SVG}</button>`
        + `<button id="stCancelMicBtn" type="button" title="Discard">${TRASH_SVG}</button>`;
    const inputContainer = document.getElementById('input-container');
    if (inputContainer) {
        inputContainer.appendChild(hud);
    } else {
        document.body.appendChild(hud);
    }

    document.getElementById('stMuteMicBtn').addEventListener('click', (e) => {
        e.stopPropagation();
        e.preventDefault();
        setMicMuted(!micMuted);
    });

    // Event listener for Discard button
    document.getElementById('stCancelMicBtn').addEventListener('click', (e) => {
        e.stopPropagation();
        e.preventDefault();
        stopListening(false); // stop and discard (shouldSubmit = false)
    });
}

// Function to show listening HUD
function showListening() {
    initAudioHUD();
    setMicMuted(false);
    const hud = document.getElementById('stListeningMsg');
    if (hud) {
        hud.style.display = 'flex';
        hud.className = 'st-msg-speaking';
        const txtSpan = hud.querySelector('#stMicStatusText');
        if (txtSpan) txtSpan.textContent = currentLang === 'es' ? 'Escuchando...' : 'Listening...';
    }
}

// Hide visual listening HUD
function hideListening() {
    const hud = document.getElementById('stListeningMsg');
    if (hud) hud.style.display = 'none';
}

// Reset the silence countdown timer.
function resetSilenceTimer(durationMs = SILENCE_TIMEOUT_LONG) {
    const now = Date.now();
    const isShortTimeout = durationMs === SILENCE_TIMEOUT_SHORT;

    // Throttle resets for long timeouts to at most once per 200ms
    if (!isShortTimeout && (now - lastSilenceResetTime < 200)) {
        return;
    }
    lastSilenceResetTime = now;

    if (silenceTimer) clearTimeout(silenceTimer);
    if (countdownInterval) clearInterval(countdownInterval);

    const hud = document.getElementById('stListeningMsg');
    const txtSpan = hud ? hud.querySelector('#stMicStatusText') : null;

    if (hud) {
        if (!isShortTimeout) {
            if (txtSpan) txtSpan.textContent = currentLang === 'es' ? 'Hablando...' : 'Speaking...';
            hud.className = 'st-msg-speaking';
        } else {
            if (txtSpan) txtSpan.textContent = currentLang === 'es' ? 'Pausado...' : 'Paused...';
            hud.className = 'st-msg-paused';
        }
    }

    silenceTimer = setTimeout(() => {
        stopListening(true);
    }, durationMs);

    const startTime = Date.now() + 400; // Wait 400ms before showing countdown to prevent flicker
    countdownInterval = setInterval(() => {
        const now = Date.now();
        if (now >= startTime) {
            const remaining = Math.max(0, (durationMs - (now - (startTime - 400))) / 1000).toFixed(1);
            const hud = document.getElementById('stListeningMsg');
            if (hud) {
                const txtSpan = hud.querySelector('#stMicStatusText');
                if (txtSpan) {
                    txtSpan.textContent = currentLang === 'es' ? 
                        `Pausado... Enviando en ${remaining}s` : 
                        `Paused... Sending in ${remaining}s`;
                }
                hud.className = 'st-msg-paused';
            }
        }
    }, 100);
}

// Stop Web Speech Synthesis
function cancelSpeech(restartLoop = false) {
    if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
    }
    if (cartesiaAudioPlayer) {
        cartesiaAudioPlayer.pause();
        cartesiaAudioPlayer = null;
    }
    ttsSessionId = Date.now();
    currentUtterance = null;
    document.querySelectorAll('.tts-btn.active').forEach(btn => {
        btn.classList.remove('active');
        btn.innerHTML = '🔊';
        btn.title = (typeof translations !== 'undefined' && translations[currentLang]?.listen) || 'Listen';
    });
    // Leave SPEAKING on the TTS owner (not necessarily currentProvider after chat switch)
    if (window.getProviderFSM) {
        const owner = ttsOwnerProvider || (typeof currentProvider !== 'undefined' ? currentProvider : null);
        if (owner) {
            const fsm = window.getProviderFSM(owner);
            if (fsm && fsm.is(window.FSM_STATES.SPEAKING) && !restartLoop) {
                fsm.transition(window.FSM_STATES.IDLE, { reason: 'cancelSpeech' });
            }
        }
    }
    // If the voice loop is active and the caller requests restart, resume mic
    if (restartLoop) {
        checkAndRestartVoiceLoop();
    }
}

// Main toggle entry point for the mic button
function toggleRecording() {
    if (isRecording) {
        voiceLoopActive = false; // user clicked button to stop manually, so turn off voice loop
        stopListening(true);
    } else {
        startRecording();
    }
}

// Generation token to cancel in-flight getUserMedia when stop happens first
let recordingGeneration = 0;

let cachedMicStream = null;

function getAudioStream() {
    if (cachedMicStream && cachedMicStream.active && cachedMicStream.getAudioTracks().some(t => t.readyState === 'live')) {
        cachedMicStream.getAudioTracks().forEach(track => { track.enabled = true; });
        return Promise.resolve(cachedMicStream);
    }
    return navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
        .then(stream => {
            cachedMicStream = stream;
            try { localStorage.setItem('ignite_mic_permission_granted', 'true'); } catch (e) {}
            return stream;
        });
}

// Start recording and silence detection
function startRecording() {
    if (isRecording) return;

    // If LLM is currently processing or speaking, cancel it immediately so the user can interrupt!
    if (typeof isProcessing !== 'undefined' && isProcessing[currentProvider]) {
        console.log('User clicked mic during LLM response - interrupting LLM generation!');
        if (typeof window.cancelProviderProcessing === 'function') {
            window.cancelProviderProcessing(currentProvider);
        } else {
            isProcessing[currentProvider] = false;
        }
    }

    // Cancel any active TTS playback
    cancelSpeech();

    const thisGeneration = ++recordingGeneration;
    isRecording = true;
    hasSpoken = false;
    lastFinalTime = 0; // reset per-session
    voiceLoopActive = true;
    audioChunks = [];

    // FSM: IDLE → RECORDING (SPEAKING must go through IDLE per skill matrix)
    const _fsm = window.getProviderFSM ? window.getProviderFSM(currentProvider) : null;
    if (_fsm) {
        if (_fsm.is(window.FSM_STATES.ERROR)) _fsm.reset({ reason: 'mic-start' });
        if (_fsm.is(window.FSM_STATES.SPEAKING)) {
            _fsm.transition(window.FSM_STATES.IDLE, { reason: 'mic-barge-in' });
        }
        _fsm.transition(window.FSM_STATES.RECORDING);
    }

    const micBtn = document.getElementById('mic-btn');
    if (micBtn) micBtn.classList.add('recording');

    // Initialize getUserMedia and Web Audio analyser for volume & VAD
    getAudioStream()
        .then(stream => {
            // User stopped before permission resolved — release orphan tracks
            if (thisGeneration !== recordingGeneration || !isRecording) {
                stream.getAudioTracks().forEach(track => { track.enabled = false; });
                return;
            }
            micStream = stream;
            const recordStartTime = Date.now();

            // Setup audio context & analyzer node for volume tracking
            try {
                const AudioContextClass = window.AudioContext || window.webkitAudioContext;
                audioContext = new AudioContextClass();
                const source = audioContext.createMediaStreamSource(stream);
                analyser = audioContext.createAnalyser();
                analyser.fftSize = 256;

                source.connect(analyser);

                const dataArray = new Float32Array(analyser.fftSize);
                let consecutiveSpeechFrames = 0;

                volumeInterval = setInterval(() => {
                    if (!isRecording || !analyser) return;
                    analyser.getFloatTimeDomainData(dataArray);
                    let sumSquares = 0.0;
                    for (let i = 0; i < dataArray.length; i++) {
                        sumSquares += dataArray[i] * dataArray[i];
                    }
                    const rms = Math.sqrt(sumSquares / dataArray.length);
                    updateHudWaveBars(rms);

                    // While muted, keep the HUD quiet and do not advance VAD / silence timers.
                    if (micMuted) {
                        consecutiveSpeechFrames = 0;
                        return;
                    }
                    
                    if (rms > RMS_THRESHOLD) {
                        consecutiveSpeechFrames++;
                        if (consecutiveSpeechFrames >= 4) { // 4 frames * 50ms = 200ms of continuous sound
                            if (!hasSpoken) hasSpoken = true;
                        }
                        if (hasSpoken) {
                            resetSilenceTimer(SILENCE_TIMEOUT_LONG);
                        }
                    } else {
                        consecutiveSpeechFrames = 0;
                    }
                }, 50);
            } catch (e) {
                console.error("Web Audio API analyser setup failed:", e);
            }

            // Setup MediaRecorder
            let options = { mimeType: 'audio/webm' };
            if (!MediaRecorder.isTypeSupported('audio/webm')) {
                options = { mimeType: 'audio/ogg' };
            }
            try {
                mediaRecorder = new MediaRecorder(stream, options);
            } catch (e) {
                mediaRecorder = new MediaRecorder(stream);
            }

            mediaRecorder.addEventListener("dataavailable", event => {
                if (event.data && event.data.size > 0) {
                    audioChunks.push(event.data);
                }
            });

            mediaRecorder.addEventListener("stop", () => {
                const mime = mediaRecorder.mimeType || 'audio/webm';
                const audioBlob = new Blob(audioChunks, { type: mime });
                audioChunks = [];

                if (micStream) {
                    micStream.getAudioTracks().forEach(track => { track.enabled = false; });
                }

                // If submitted, prepare files and call sendMessage()
                if (shouldSubmitAudio) {
                    // Skip empty / silent clicks (no speech + tiny blob)
                    if ((!hasSpoken && audioBlob.size < 2500) || audioBlob.size < 500) {
                        console.warn('Discarding empty voice capture');
                        if (window.getProviderFSM) {
                            window.getProviderFSM(currentProvider).transition(window.FSM_STATES.IDLE, { reason: 'empty-voice' });
                        }
                        mediaRecorder = null;
                        return;
                    }
                    if (typeof isProcessing !== 'undefined' && isProcessing[currentProvider]) {
                        console.warn('Voice ready but text request still processing — dropping capture');
                        if (window.getProviderFSM) {
                            window.getProviderFSM(currentProvider).transition(window.FSM_STATES.IDLE, { reason: 'busy' });
                        }
                        mediaRecorder = null;
                        return;
                    }
                    const capturedProvider = currentProvider;
                    const reader = new FileReader();
                    reader.onload = (event) => {
                        try {
                            const base64String = event.target.result.split(',')[1];

                            // If the user switched chats while encoding, send to the
                            // original voice provider by temporarily aligning currentProvider.
                            const previousProvider = currentProvider;
                            if (capturedProvider && capturedProvider !== currentProvider) {
                                currentProvider = capturedProvider;
                            }

                            // Clear the input box to avoid residual text being sent/mixed with audio
                            const messageInput = document.getElementById('message-input');
                            if (messageInput) {
                                messageInput.value = '';
                                messageInput.dispatchEvent(new Event('input', { bubbles: true }));
                            }

                            // Preserve other attachments but filter out old voice messages
                            pendingFiles = pendingFiles.filter(f => !f.name.startsWith('Voice_Message_'));
                            pendingFiles.push({
                                name: `Voice_Message_${new Date().toLocaleTimeString().replace(/:/g, '-')}.webm`,
                                mime_type: mime,
                                base64: base64String,
                                size: audioBlob.size
                            });

                            if (typeof sendMessage === 'function') {
                                sendMessage();
                            }

                            if (capturedProvider && previousProvider !== capturedProvider) {
                                currentProvider = previousProvider;
                            }
                        } catch (err) {
                            console.error('Voice FileReader onload failed:', err);
                            if (window.getProviderFSM) {
                                window.getProviderFSM(capturedProvider || currentProvider).transition(
                                    window.FSM_STATES.IDLE,
                                    { reason: 'voice-reader-onload-error' }
                                );
                            }
                        }
                    };
                    reader.onerror = () => {
                        console.error('Voice FileReader error:', reader.error);
                        if (window.getProviderFSM) {
                            window.getProviderFSM(capturedProvider || currentProvider).transition(
                                window.FSM_STATES.IDLE,
                                { reason: 'voice-reader-error' }
                            );
                        }
                        if (typeof updateInputButtonsState === 'function') updateInputButtonsState();
                    };
                    reader.readAsDataURL(audioBlob);
                }
                
                mediaRecorder = null;
            });

            // Start recording
            mediaRecorder.start();
            showListening();
            recordTimer = setTimeout(() => {
                stopListening(true);
            }, 600000); // 10 minutes max limit
        })
        .catch(err => {
            console.error("Microphone access denied:", err);
            isRecording = false;
            voiceLoopActive = false;
            recordingGeneration++; // invalidate any late success
            if (micBtn) micBtn.classList.remove('recording');
            hideListening();
            // FSM: transition to ERROR on mic denial (auto-recovers to IDLE)
            if (window.getProviderFSM) {
                window.getProviderFSM(currentProvider).transition(window.FSM_STATES.ERROR, { reason: 'mic-denied' });
            }
            alert(currentLang === 'es' ? "Acceso al micrófono denegado o no disponible." : "Microphone access denied or not found.");
        });
}

// Stop listening state
let shouldSubmitAudio = true;
function stopListening(submit = true) {
    if (!isRecording) return;

    shouldSubmitAudio = submit;
    isRecording = false;
    recordingGeneration++; // invalidate in-flight getUserMedia
    const voiceProvider = currentProvider;
    const hasActiveRecorder = !!(mediaRecorder && mediaRecorder.state !== 'inactive');

    // Only enter THINKING when a real recording is about to submit.
    // Quick mic toggle before getUserMedia finishes used to leave send disabled forever.
    if (window.getProviderFSM) {
        const _fsm = window.getProviderFSM(voiceProvider);
        if (submit && hasActiveRecorder) {
            _fsm.transition(window.FSM_STATES.THINKING, { reason: 'voice-submit' });
        } else {
            _fsm.transition(window.FSM_STATES.IDLE, { reason: submit ? 'voice-no-recorder' : 'voice-discard' });
        }
    }

    // Clear timers
    if (recordTimer) clearTimeout(recordTimer);
    if (silenceTimer) clearTimeout(silenceTimer);
    if (countdownInterval) clearInterval(countdownInterval);
    if (volumeInterval) clearInterval(volumeInterval);
    micMuted = false;
    
    // Close audio context
    if (audioContext) {
        try {
            audioContext.close();
        } catch (e) {}
        audioContext = null;
    }
    analyser = null;

    if (!submit) {
        voiceLoopActive = false; // manual discard breaks the voice loop
        audioChunks = [];        // clear buffer immediately on cancel
        if (micStream) {
            micStream.getAudioTracks().forEach(track => { track.enabled = false; });
        }
    }

    // Stop MediaRecorder
    if (hasActiveRecorder) {
        try {
            mediaRecorder.stop();
        } catch (e) {
            if (window.getProviderFSM) {
                window.getProviderFSM(voiceProvider).transition(window.FSM_STATES.IDLE, { reason: 'recorder-stop-error' });
            }
        }
    } else {
        if (micStream) {
            micStream.getTracks().forEach(track => track.stop());
            micStream = null;
        }
        mediaRecorder = null;
        if (submit && window.getProviderFSM) {
            window.getProviderFSM(voiceProvider).transition(window.FSM_STATES.IDLE, { reason: 'voice-empty-stop' });
        }
    }

    const micBtn = document.getElementById('mic-btn');
    if (micBtn) micBtn.classList.remove('recording');
    hideListening();
}

// Detect language of text for speech synthesis
function detectLang(text) {
    if (!text || !text.trim()) return currentLang === 'es' ? 'es-MX' : 'en-US';
    
    // Quick heuristic: Spanish specific punctuation and accents
    if (/[áéíóúñü¿¡]/i.test(text)) {
        return 'es-MX';
    }

    const clean = text.toLowerCase().replace(/[^a-z\u00e0-\u024f]+/g, ' ').trim();
    const words = clean.split(/\s+/);
    const scores = {};
    const ALLOWED_LANGS = ["en-US", "es-MX", "fr-FR", "de-DE", "it-IT", "pt-BR"];
    const SUPPORTED_BASES = ["en", "es", "fr", "de", "it", "pt"];
    SUPPORTED_BASES.forEach(base => { scores[base] = 0; });
    
    const sets = {
        es: new Set(["hola","buen","buenas","camarada","tal","gracias","si","sí","no","yo","tu","tú","el","él","la","los","las","un","una","uno","de","del","al","que","qué","en","y","para","por","con","su","sus","como","cómo","pero","este","esta","estas","estos","hoy","muy","bien","tengo","quiero","puedo","podemos","hablar","español","buenos","dias","días","tardes","noches","entendido","claro","ayuda","ayudar","hacer","crear","generar","imagen","audio","texto","pantalla","grabar","microfono","micrófono","computadora","equipo","sistema","archivo","documento","escribir","leer","responder","respuesta","pregunta","saludos","por favor","favor","mal","más","mas","menos","también","tambien","sólo","solo","todo","todos","nada","algo","alguno","alguna","algunos","algunas","otro","otra","otros","otras","mismo","misma","mismos","mismas","analiza","analizar","boletas","boleta","factura","receta","estas","estos","pago","pagos"]),
        en: new Set(["the","a","an","and","of","to","in","for","with","on","at","by","from","is","are","was","were","have","has","had","do","does","did","hello","hi","thanks","you","your","we","they","he","she","it","this","that","what","how","can","could","would","should","please","yes","no","okay","ok","good","great"]),
        fr: new Set(["bonjour","merci","oui","je","tu","il","elle","le","la","les","un","une","de","et","en","pour","avec","est","bien"]),
        de: new Set(["hallo","danke","ja","ich","du","er","sie","wir","der","die","das","ein","und","mit","auf","von","ist","gut"]),
        it: new Set(["ciao","grazie","si","io","tu","il","la","un","una","e","di","a","da","sono","bene"]),
        pt: new Set(["ola","obrigado","sim","eu","tu","o","a","um","uma","de","em","para","com","por","bem"])
    };
    
    words.forEach(w => {
        SUPPORTED_BASES.forEach(base => {
            if (sets[base] && sets[base].has(w)) scores[base]++;
        });
    });
    
    let best = null, bestScore = 0;
    SUPPORTED_BASES.forEach(base => {
        if (scores[base] > bestScore) {
            bestScore = scores[base];
            best = base;
        }
    });
    
    const langMap = {
        en: "en-US",
        es: "es-MX",
        fr: "fr-FR",
        de: "de-DE",
        it: "it-IT",
        pt: "pt-BR"
    };
    
    if (best && bestScore > 0) return langMap[best];
    return currentLang === 'es' ? 'es-MX' : 'en-US';
}

// Find standard system voice for a given BCP-47 language code
function findVoiceForLang(lang) {
    if (!window.speechSynthesis) return null;
    const voices = window.speechSynthesis.getVoices();
    if (!voices || !voices.length) return null;
    
    const target = lang.toLowerCase().replace('_', '-');
    const base = target.split('-')[0];
    
    // 1. Exact match (e.g. es-mx)
    let voice = voices.find(v => v.lang.toLowerCase().replace('_', '-') === target);
    if (voice) return voice;
    
    // 2. Base match (e.g. es)
    voice = voices.find(v => v.lang.toLowerCase().replace('_', '-').startsWith(base));
    if (voice) return voice;
    
    // 3. Name match for Spanish keywords
    if (base === 'es') {
        voice = voices.find(v => {
            const nameLower = v.name.toLowerCase();
            return nameLower.includes('spanish') || nameLower.includes('español') || nameLower.includes('castellano');
        });
        if (voice) return voice;
    }
    
    return null;
}

window.speakText = function (btn, text) {
    if (!text && btn) {
        try {
            const wrapper = btn.closest('.message-wrapper');
            if (wrapper) {
                const contentEl = wrapper.querySelector('.message-content');
                if (contentEl) {
                    text = contentEl.textContent;
                }
            }
        } catch (e) {
            console.error("Error extracting text for TTS:", e);
        }
    }
    if (!text) text = '';

    const wasActive = btn && btn.classList.contains('active');

    if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
    }
    if (cartesiaAudioPlayer) {
        try {
            cartesiaAudioPlayer.pause();
        } catch (e) {}
        cartesiaAudioPlayer = null;
    }

    const currentSessionId = ++ttsSessionId;

    document.querySelectorAll('.tts-btn.active').forEach(b => {
        b.classList.remove('active');
        b.innerHTML = '🔊';
        b.title = (typeof translations !== 'undefined' && translations[currentLang]?.listen) || 'Listen';
    });

    if (wasActive) {
        return;
    }

    const cleanText = text
        .replace(/[\uE000-\uF8FF]|\uD83C[\uDC00-\uDFFF]|\uD83D[\uDC00-\uDFFF]|[\u2011-\u26FF]|\uD83E[\uDD10-\uDDFF]/g, "") // remove emojis
        .replace(/\*+([^*]+)\*+/g, "$1") // bold markdown
        .replace(/`([^`]+)`/g, "$1") // inline code
        .replace(/#+\s+/g, "") // headers
        .replace(/[\r\n]+/g, " ")
        .trim();

    if (!cleanText) {
        checkAndRestartVoiceLoop();
        return;
    }

    if (btn) {
        btn.classList.add('active');
        btn.innerHTML = '⏹️';
        btn.title = (typeof translations !== 'undefined' && translations[currentLang]?.stop_speech) || 'Stop';
    }

    // FSM: THINKING/IDLE → SPEAKING
    ttsOwnerProvider = (typeof currentProvider !== 'undefined') ? currentProvider : null;
    if (window.getProviderFSM) {
        const _fsmTts = window.getProviderFSM(currentProvider);
        if (_fsmTts.is(window.FSM_STATES.THINKING) || _fsmTts.is(window.FSM_STATES.IDLE)) {
            _fsmTts.transition(window.FSM_STATES.SPEAKING);
        }
    }


    // Delay audio playback start slightly to let speechSynthesis.cancel() complete and flush voice queues.
    setTimeout(() => {
        if (currentSessionId !== ttsSessionId) return;

        // Try Cartesia TTS first, otherwise fall back to browser Web Speech API
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.generate_cartesia_tts === 'function') {
            runCartesiaTTS(cleanText, btn, currentSessionId);
        } else {
            runBrowserTTS(cleanText, btn, currentSessionId);
        }
    }, 50);
};

function runCartesiaTTS(cleanText, btn, currentSessionId) {
    const rawSentences = cleanText.match(/[^.!?]+(?:[.!?]+|$)/g) || [];
    const sentences = [];
    rawSentences.forEach(s => {
        const trimmed = s.trim();
        if (trimmed) sentences.push(trimmed);
    });

    if (sentences.length === 0) {
        if (btn) {
            btn.classList.remove('active');
            btn.innerHTML = '🔊';
            btn.title = (typeof translations !== 'undefined' && translations[currentLang]?.listen) || 'Listen';
        }
        checkAndRestartVoiceLoop();
        return;
    }

    const ttsStartMs = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();

    // Determine the voice category once for the entire text block to keep the voice consistent.
    // Playback starts as soon as category resolves; sentence 0 is fetched first with a 2-ahead window.
    window.pywebview.api.determine_voice_category(cleanText)
        .then(voiceCat => {
            if (currentSessionId !== ttsSessionId) return;
            startCartesiaTTSPlayback(sentences, voiceCat, btn, currentSessionId, { ttsStartMs });
        })
        .catch(err => {
            console.warn("Failed to determine voice category, using default:", err);
            if (currentSessionId !== ttsSessionId) return;
            startCartesiaTTSPlayback(sentences, null, btn, currentSessionId, { ttsStartMs });
        });
}

function startCartesiaTTSPlayback(sentences, voiceCat, btn, currentSessionId, options = {}) {
    let index = 0;
    const preloadedAudio = {};
    const preloadingJobs = {};
    const ttsStartMs = options.ttsStartMs || ((typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now());
    let firstPlayLogged = false;

    function preloadSentence(idx) {
        if (idx >= sentences.length || preloadedAudio[idx] || preloadingJobs[idx]) return;
        
        preloadingJobs[idx] = true;
        const fetchStart = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
        window.pywebview.api.generate_cartesia_tts(sentences[idx], voiceCat)
            .then(res => {
                if (currentSessionId !== ttsSessionId) return;
                if (res && res.status === 'success' && res.audio_base64) {
                    preloadedAudio[idx] = `data:audio/mp3;base64,${res.audio_base64}`;
                    const fetchEnd = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
                    console.debug(`[TTS] preload sentence ${idx} in ${Math.round(fetchEnd - fetchStart)}ms`);
                }
            })
            .catch(err => {
                console.warn(`Preload failed for sentence ${idx}:`, err);
            })
            .finally(() => {
                delete preloadingJobs[idx];
            });
    }

    // Prefetch sentence 0 immediately, plus a 2-sentence look-ahead window.
    preloadSentence(0);
    preloadSentence(1);
    preloadSentence(2);

    function playNext() {
        if (currentSessionId !== ttsSessionId) return;

        if (index >= sentences.length) {
            cartesiaAudioPlayer = null;
            if (btn) {
                btn.classList.remove('active');
                btn.innerHTML = '🔊';
                btn.title = (typeof translations !== 'undefined' && translations[currentLang]?.listen) || 'Listen';
            }
            // FSM: SPEAKING → IDLE on TTS completion (on the chat that started it)
            if (window.getProviderFSM) {
                window.getProviderFSM(ttsOwnerProvider || currentProvider).transition(window.FSM_STATES.IDLE);
            }
            checkAndRestartVoiceLoop();
            return;
        }

        const sentenceText = sentences[index];

        const handlePlayback = (audioUrl) => {
            if (currentSessionId !== ttsSessionId) return;
            cartesiaAudioPlayer = new Audio(audioUrl);
            cartesiaAudioPlayer.onended = () => {
                // Free played audio: long scripts otherwise hold every sentence
                // as a base64 data URI until playback finishes.
                delete preloadedAudio[index];
                index++;
                playNext();
            };
            cartesiaAudioPlayer.onerror = (err) => {
                console.warn(`Cartesia playback error on sentence ${index}, falling back to browser TTS:`, err);
                cartesiaAudioPlayer = null;
                const remainingText = sentences.slice(index).join(' ');
                runBrowserTTS(remainingText, btn, currentSessionId);
            };
            const playStart = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
            cartesiaAudioPlayer.play().then(() => {
                if (!firstPlayLogged && index === 0) {
                    firstPlayLogged = true;
                    const elapsed = Math.round(playStart - ttsStartMs);
                    console.info(`[TTS] first sentence play start in ${elapsed}ms (target ~${TTS_TARGET_FIRST_PLAY_MS}ms)`);
                }
            }).catch(playErr => {
                console.warn(`Cartesia play error on sentence ${index}, falling back to browser TTS:`, playErr);
                cartesiaAudioPlayer = null;
                const remainingText = sentences.slice(index).join(' ');
                runBrowserTTS(remainingText, btn, currentSessionId);
            });

            // Keep a 2-sentence prefetch window ahead of the playhead.
            preloadSentence(index + 1);
            preloadSentence(index + 2);
        };

        if (preloadedAudio[index]) {
            handlePlayback(preloadedAudio[index]);
        } else if (preloadingJobs[index]) {
            // Wait briefly for an in-flight prefetch instead of issuing a duplicate request.
            const waitStart = Date.now();
            const waitForPreload = () => {
                if (currentSessionId !== ttsSessionId) return;
                if (preloadedAudio[index]) {
                    handlePlayback(preloadedAudio[index]);
                    return;
                }
                if (Date.now() - waitStart > 2500) {
                    window.pywebview.api.generate_cartesia_tts(sentenceText, voiceCat)
                        .then(res => {
                            if (currentSessionId !== ttsSessionId) return;
                            if (res && res.status === 'success' && res.audio_base64) {
                                handlePlayback(`data:audio/mp3;base64,${res.audio_base64}`);
                            } else {
                                const remainingText = sentences.slice(index).join(' ');
                                runBrowserTTS(remainingText, btn, currentSessionId);
                            }
                        })
                        .catch(() => {
                            if (currentSessionId !== ttsSessionId) return;
                            const remainingText = sentences.slice(index).join(' ');
                            runBrowserTTS(remainingText, btn, currentSessionId);
                        });
                    return;
                }
                setTimeout(waitForPreload, 40);
            };
            waitForPreload();
        } else {
            // Not preloaded yet, fetch it now
            window.pywebview.api.generate_cartesia_tts(sentenceText, voiceCat)
                .then(res => {
                    if (currentSessionId !== ttsSessionId) return;
                    if (res && res.status === 'success' && res.audio_base64) {
                        const audioUrl = `data:audio/mp3;base64,${res.audio_base64}`;
                        handlePlayback(audioUrl);
                    } else {
                        console.log("Cartesia sentence fetch failed, falling back to browser TTS");
                        const remainingText = sentences.slice(index).join(' ');
                        runBrowserTTS(remainingText, btn, currentSessionId);
                    }
                })
                .catch(err => {
                    console.error("Cartesia sentence fetch error, falling back to browser TTS:", err);
                    if (currentSessionId !== ttsSessionId) return;
                    const remainingText = sentences.slice(index).join(' ');
                    runBrowserTTS(remainingText, btn, currentSessionId);
                });
        }
    }

    // Start playing the first sentence
    playNext();
}

function runBrowserTTS(cleanText, btn, currentSessionId) {
    if (!window.speechSynthesis) {
        if (window.getProviderFSM) {
            window.getProviderFSM(currentProvider).transition(window.FSM_STATES.IDLE, { reason: 'no-speechSynthesis' });
        }
        checkAndRestartVoiceLoop();
        return;
    }
    if (window.getProviderFSM) {
        window.getProviderFSM(currentProvider).transition(window.FSM_STATES.SPEAKING, { reason: 'browser-tts' });
    }
    const rawSentences = cleanText.match(/[^.!?]+(?:[.!?]+|$)/g) || [];
    const sentences = [];
    rawSentences.forEach(s => {
        const trimmed = s.trim();
        if (trimmed) sentences.push(trimmed);
    });

    const chunks = [];
    sentences.forEach(s => {
        if (s.length > 200) {
            const words = s.split(' ');
            let chunk = '';
            for (let i = 0; i < words.length; i++) {
                if ((chunk + ' ' + words[i]).length <= 200) {
                    chunk += (chunk ? ' ' : '') + words[i];
                } else {
                    if (chunk) chunks.push(chunk);
                    chunk = words[i];
                }
            }
            if (chunk) chunks.push(chunk);
        } else {
            chunks.push(s);
        }
    });

    if (chunks.length === 0) {
        checkAndRestartVoiceLoop();
        return;
    }

    const lang = detectLang(cleanText);
    let index = 0;
    function speakNext() {
        if (currentSessionId !== ttsSessionId) {
            checkAndRestartVoiceLoop();
            return;
        }

        if (index >= chunks.length) {
            if (btn) {
                btn.classList.remove('active');
                btn.innerHTML = '🔊';
                btn.title = (typeof translations !== 'undefined' && translations[currentLang]?.listen) || 'Listen';
            }
            if (window.getProviderFSM) {
                window.getProviderFSM(ttsOwnerProvider || currentProvider).transition(window.FSM_STATES.IDLE, { reason: 'browser-tts-done' });
            }
            checkAndRestartVoiceLoop();
            return;
        }

        const utterance = new SpeechSynthesisUtterance(chunks[index]);
        utterance.lang = lang;
        utterance.rate = 1.0;
        
        const voice = findVoiceForLang(lang);
        if (voice) utterance.voice = voice;

        utterance.onstart = () => {
            if (btn) {
                btn.classList.add('active');
            }
        };
        utterance.onend = () => {
            index++;
            speakNext();
        };
        utterance.onerror = (e) => {
            console.error("Speech synthesis error:", e);
            index++;
            speakNext();
        };

        currentUtterance = utterance;
        window.speechSynthesis.speak(utterance);
    }

    const voices = window.speechSynthesis.getVoices();
    if (voices && voices.length > 0) {
        speakNext();
    } else {
        // If onvoiceschanged never fires (no voices installed), the FSM would
        // stay in SPEAKING forever. Fall back after a short wait.
        let started = false;
        const startOnce = () => {
            if (started) return;
            started = true;
            window.speechSynthesis.onvoiceschanged = null;
            speakNext();
        };
        window.speechSynthesis.onvoiceschanged = startOnce;
        setTimeout(startOnce, 2000);
    }
}

// Global hooks to abort voice loop or cancel recording (called by app.js on input interactions)
window.cancelVoiceSession = function () {
    voiceLoopActive = false;
    cancelSpeech();
    if (isRecording) {
        stopListening(false);
    }
};

window.stopVoiceLoop = function () {
    voiceLoopActive = false;
};

window.setVoiceLoopActive = function (active) {
    voiceLoopActive = active;
};


// app/frontend/files.js
// Logic for handling file details, previewing attachments, and icon templates

// Helper to format file sizes
function formatFileSize(bytes) {
    if (bytes === undefined || bytes === null) return '';
    if (bytes < 1024) return bytes + ' B';
    const kb = bytes / 1024;
    if (kb < 1024) return kb.toFixed(1) + ' KB';
    const mb = kb / 1024;
    return mb.toFixed(1) + ' MB';
}

// Office brand kinds for attachment cards / chips (Word blue, Excel green, PPT orange).
function getOfficeFileKind(file) {
    const name = (file && file.name ? file.name : '').toLowerCase();
    const mime = file && file.mime_type ? file.mime_type.toLowerCase() : '';
    if (
        name.endsWith('.xlsx') || name.endsWith('.xls') || name.endsWith('.csv') ||
        mime.includes('sheet') || mime.includes('excel') || mime.includes('csv')
    ) {
        return 'excel';
    }
    if (
        name.endsWith('.pptx') || name.endsWith('.ppt') ||
        mime.includes('presentation') || mime.includes('powerpoint')
    ) {
        return 'powerpoint';
    }
    if (
        name.endsWith('.docx') || name.endsWith('.doc') ||
        mime.includes('wordprocessingml') || mime.includes('msword') ||
        (mime.includes('word') && !mime.includes('powerpoint'))
    ) {
        return 'word';
    }
    return null;
}

// Helper to get matching file icon SVG or thumbnail image
function getFileIcon(file) {
    const name = file.name.toLowerCase();
    const mime = file.mime_type ? file.mime_type.toLowerCase() : '';

    if (mime.startsWith('image/')) {
        if (file.base64) {
            return `<img src="data:${file.mime_type};base64,${file.base64}" alt="${file.name}" />`;
        } else {
            return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>`;
        }
    }

    // Audio icon (music notes outline)
    if (mime.startsWith('audio/') || name.endsWith('.mp3') || name.endsWith('.wav') || name.endsWith('.m4a') || name.endsWith('.ogg') || name.endsWith('.webm')) {
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>`;
    }

    // PDF icon (document page outline)
    if (name.endsWith('.pdf') || mime.includes('pdf')) {
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>`;
    }

    const officeKind = getOfficeFileKind(file);
    if (officeKind === 'excel') {
        return `<img src="assets/excel-icon.png" alt="Excel"/>`;
    }
    if (officeKind === 'powerpoint') {
        return `<img src="assets/ppt-icon.png" alt="PowerPoint"/>`;
    }
    if (officeKind === 'word') {
        return `<img src="assets/word-icon.png" alt="Word"/>`;
    }

    // Default document icon
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>`;
}

function escapeHtml(value) {
    return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function filePreviewT(key, fallback) {
    const pack = (typeof translations !== 'undefined' && translations[currentLang]) || {};
    const en = (typeof translations !== 'undefined' && translations.en) || {};
    return pack[key] || en[key] || fallback;
}

function isPdfFile(file) {
    const name = (file && file.name ? file.name : '').toLowerCase();
    const mime = file && file.mime_type ? String(file.mime_type).toLowerCase() : '';
    return name.endsWith('.pdf') || mime.includes('pdf');
}

function isImageFile(file) {
    const mime = file && file.mime_type ? String(file.mime_type).toLowerCase() : '';
    return mime.startsWith('image/');
}

function isVideoFile(file) {
    const mime = file && file.mime_type ? String(file.mime_type).toLowerCase() : '';
    if (mime.startsWith('video/')) return true;
    const name = (file && file.name ? file.name : '').toLowerCase();
    return /\.(mp4|avi|mov|mkv|webm|m4v)$/.test(name);
}

function isAudioFile(file) {
    const mime = file && file.mime_type ? String(file.mime_type).toLowerCase() : '';
    if (mime.startsWith('audio/')) return true;
    const name = (file && file.name ? file.name : '').toLowerCase();
    return /\.(mp3|wav|m4a|aac|ogg|opus|webm|flac|wma|caf|3gp)$/.test(name);
}

function resolveAudioMimeType(file) {
    const rec = mergeFileForPreview(file);
    const mime = rec.mime_type ? String(rec.mime_type).toLowerCase() : '';
    if (mime && mime.startsWith('audio/')) return mime;
    const name = (rec.name || '').toLowerCase();
    const ext = name.includes('.') ? name.split('.').pop() : '';
    const map = {
        mp3: 'audio/mpeg',
        wav: 'audio/wav',
        m4a: 'audio/mp4',
        aac: 'audio/aac',
        ogg: 'audio/ogg',
        opus: 'audio/ogg',
        webm: 'audio/webm',
        flac: 'audio/flac',
        wma: 'audio/x-ms-wma',
        caf: 'audio/x-caf',
        '3gp': 'audio/3gpp'
    };
    return map[ext] || 'audio/mpeg';
}

function pathToFileUrl(filepath) {
    if (!filepath || typeof filepath !== 'string') return null;
    const trimmed = filepath.trim();
    if (!trimmed) return null;
    if (/^https?:\/\//i.test(trimmed) || trimmed.startsWith('blob:') || trimmed.startsWith('file:')) {
        return trimmed;
    }
    const normalized = trimmed.replace(/\\/g, '/');
    if (normalized.startsWith('/')) return 'file://' + normalized;
    return 'file:///' + normalized;
}

function canPreviewMediaInOverlay(file) {
    const rec = mergeFileForPreview(file);
    if (!rec) return false;
    if (isAudioFile(rec) || isVideoFile(rec)) {
        return fileHasInlineBytes(rec) || Boolean(rec.path);
    }
    return false;
}

function getFileTypeLabel(file) {
    if (isPdfFile(file)) return 'PDF';
    const officeKind = getOfficeFileKind(file);
    if (officeKind === 'word') return 'DOCX';
    if (officeKind === 'excel') return 'XLSX';
    if (officeKind === 'powerpoint') return 'PPTX';
    if (isImageFile(file)) return 'IMG';
    if (isVideoFile(file)) return 'VIDEO';
    if (isAudioFile(file)) return 'AUDIO';
    const name = (file && file.name ? file.name : '');
    const dot = name.lastIndexOf('.');
    if (dot > 0 && dot < name.length - 1) return name.slice(dot + 1).toUpperCase();
    return 'FILE';
}

function formatPageCountLabel(pageCount) {
    const n = Number(pageCount) || 0;
    if (n <= 0) return '';
    if (n === 1) return filePreviewT('file_preview_page', '1 page');
    return filePreviewT('file_preview_pages', '{count} pages').replace('{count}', String(n));
}

function buildFileMetaLine(file) {
    const parts = [];
    const pages = formatPageCountLabel(file && file.page_count);
    if (pages) parts.push(pages);
    parts.push(getFileTypeLabel(file));
    const sizeText = file && file.size ? formatFileSize(file.size) : '';
    if (sizeText) parts.push(sizeText);
    return parts.join(' • ');
}

const FILE_PREVIEW_STORE = {};
const _filePreviewOrder = [];
const FILE_PREVIEW_STORE_MAX_ENTRIES = 32;
let _filePreviewSeq = 0;
let _pdfPreviewSeq = 0;
const FILE_PREVIEW_HYDRATE_TIMEOUT_MS = 4000;
const FILE_PREVIEW_THUMB_WIDTH_PX = 280;
const FILE_PREVIEW_PDF_MAX_PAGES = 40;
// Bundled for PyWebView file:// — CDN often blocked offline or in locked-down WebView2.
const PDFJS_SCRIPT_URL = 'vendor/pdfjs/pdf.min.js';
const PDFJS_WORKER_URL = 'vendor/pdfjs/pdf.worker.min.js';

function trimFilePreviewStore() {
    while (_filePreviewOrder.length > FILE_PREVIEW_STORE_MAX_ENTRIES) {
        const evictId = _filePreviewOrder.shift();
        if (evictId) delete FILE_PREVIEW_STORE[evictId];
    }
}

function rememberFileForPreview(file) {
    if (!file || typeof file !== 'object') return '';
    if (!file.preview_id) {
        _filePreviewSeq += 1;
        file.preview_id = 'fp_' + _filePreviewSeq + '_' + Date.now();
    }
    if (isImageFile(file) && file.base64 && !file.preview_base64) {
        file.preview_base64 = file.base64;
        file.preview_mime = file.mime_type || file.preview_mime || 'image/jpeg';
    }
    const prev = FILE_PREVIEW_STORE[file.preview_id] || {};
    FILE_PREVIEW_STORE[file.preview_id] = {
        preview_id: file.preview_id,
        name: file.name || prev.name || 'file',
        mime_type: file.mime_type || prev.mime_type || 'application/octet-stream',
        size: file.size != null ? file.size : prev.size,
        base64: file.base64 || prev.base64 || '',
        preview_base64: file.preview_base64 || prev.preview_base64 || '',
        preview_mime: file.preview_mime || prev.preview_mime || 'image/jpeg',
        page_count: file.page_count || prev.page_count || 0,
        path: file.path || prev.path || ''
    };
    const idx = _filePreviewOrder.indexOf(file.preview_id);
    if (idx !== -1) _filePreviewOrder.splice(idx, 1);
    _filePreviewOrder.push(file.preview_id);
    trimFilePreviewStore();
    return file.preview_id;
}

function fileHasInlineBytes(file) {
    const rec = mergeFileForPreview(file);
    return Boolean(rec && (rec.base64 || rec.preview_base64));
}

function shouldOpenNativePathOnly(file) {
    const rec = mergeFileForPreview(file);
    if (!rec || !rec.path || rec.base64) return false;
    if (canPreviewMediaInOverlay(rec)) return false;
    return true;
}

function getRememberedFile(previewId) {
    if (!previewId) return null;
    return FILE_PREVIEW_STORE[previewId] || null;
}

function findRememberedFileByName(name) {
    if (!name) return null;
    for (let i = _filePreviewOrder.length - 1; i >= 0; i--) {
        const id = _filePreviewOrder[i];
        const rec = FILE_PREVIEW_STORE[id];
        if (rec && rec.name === name) {
            return Object.assign({ preview_id: id }, rec);
        }
    }
    return null;
}

function assignDefined(target, source) {
    if (!source) return target;
    Object.keys(source).forEach((key) => {
        const val = source[key];
        if (val !== undefined && val !== null && val !== '') {
            target[key] = val;
        }
    });
    return target;
}

function mergeFileForPreview(file) {
    const remembered = file && file.preview_id ? getRememberedFile(file.preview_id) : null;
    const out = {};
    assignDefined(out, remembered);
    assignDefined(out, file);
    if (remembered) {
        if (!out.base64) out.base64 = remembered.base64 || '';
        if (!out.preview_base64) out.preview_base64 = remembered.preview_base64 || '';
        if (!out.preview_id) out.preview_id = remembered.preview_id || (file && file.preview_id) || '';
    }
    return out;
}

function fileBytesFromBase64(b64) {
    const clean = String(b64 || '').replace(/\s/g, '');
    const binary = atob(clean);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
}

function createFileObjectUrl(file) {
    const rec = mergeFileForPreview(file);
    if (!rec.base64) return null;
    try {
        const bytes = fileBytesFromBase64(rec.base64);
        let mime = rec.mime_type || 'application/octet-stream';
        if (isAudioFile(rec)) mime = resolveAudioMimeType(rec);
        const blob = new Blob([bytes], { type: mime });
        return URL.createObjectURL(blob);
    } catch (err) {
        console.warn('Failed to build file object URL:', err);
        return null;
    }
}

async function resolveMediaPlaybackUrl(file) {
    const rec = mergeFileForPreview(file);
    if (rec.base64) {
        return createFileObjectUrl(rec);
    }
    if (rec.path && window.pywebview && window.pywebview.api) {
        const api = window.pywebview.api;
        if (typeof api.get_local_file_media_url === 'function') {
            try {
                const res = await api.get_local_file_media_url(rec.path);
                if (res && res.status === 'success' && res.url) return res.url;
            } catch (err) {
                console.warn('get_local_file_media_url failed:', err);
            }
        }
    }
    if (rec.path) return pathToFileUrl(rec.path);
    return null;
}

function resolvePdfWorkerSrc() {
    try {
        return new URL(PDFJS_WORKER_URL, window.location.href).href;
    } catch (err) {
        return PDFJS_WORKER_URL;
    }
}

async function configurePdfjsWorker(pdfjsLib) {
    const workerHref = resolvePdfWorkerSrc();
    try {
        const resp = await fetch(workerHref);
        if (!resp.ok) throw new Error('pdf.worker fetch failed');
        const text = await resp.text();
        const blob = new Blob([text], { type: 'application/javascript' });
        pdfjsLib.GlobalWorkerOptions.workerSrc = URL.createObjectURL(blob);
    } catch (err) {
        console.warn('pdf.js worker blob fallback:', err);
        pdfjsLib.GlobalWorkerOptions.workerSrc = workerHref;
    }
}

let _pdfjsLoader = null;
function ensurePdfjsLoaded() {
    if (window.pdfjsLib && window.pdfjsLib.GlobalWorkerOptions.workerSrc) {
        return Promise.resolve(window.pdfjsLib);
    }
    if (window.pdfjsLib) {
        return configurePdfjsWorker(window.pdfjsLib).then(() => window.pdfjsLib);
    }
    if (_pdfjsLoader) return _pdfjsLoader;
    _pdfjsLoader = new Promise((resolve, reject) => {
        const existing = document.querySelector('script[data-ignite-pdfjs="1"]');
        if (existing && window.pdfjsLib) {
            resolve(window.pdfjsLib);
            return;
        }
        const script = document.createElement('script');
        script.src = PDFJS_SCRIPT_URL;
        script.async = true;
        script.dataset.ignitePdfjs = '1';
        script.onload = () => {
            if (!window.pdfjsLib) {
                reject(new Error('pdf.js loaded without pdfjsLib'));
                return;
            }
            resolve(window.pdfjsLib);
        };
        script.onerror = () => reject(new Error('Failed to load pdf.js'));
        document.head.appendChild(script);
    }).then((pdfjsLib) => configurePdfjsWorker(pdfjsLib).then(() => pdfjsLib)).catch((err) => {
        _pdfjsLoader = null;
        throw err;
    });
    return _pdfjsLoader;
}

async function openPdfDocument(base64) {
    const pdfjsLib = await ensurePdfjsLoaded();
    const bytes = fileBytesFromBase64(base64);
    return pdfjsLib.getDocument({
        data: bytes,
        disableAutoFetch: true,
        disableStream: true,
        disableRange: true
    }).promise;
}

function withTimeout(promise, ms, label) {
    let timer = null;
    const timeout = new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(label || 'timeout')), ms);
    });
    return Promise.race([promise, timeout]).finally(() => {
        if (timer) clearTimeout(timer);
    });
}

async function hydrateFilePreview(file) {
    if (!file || typeof file !== 'object') return file;
    rememberFileForPreview(file);
    if (file._previewHydrated) return file;
    if (isImageFile(file) && file.base64 && !file.preview_base64) {
        file.preview_base64 = file.base64;
        file.preview_mime = file.mime_type || 'image/jpeg';
        file._previewHydrated = true;
        rememberFileForPreview(file);
        return file;
    }
    if (!isPdfFile(file) || !file.base64) {
        file._previewHydrated = true;
        rememberFileForPreview(file);
        return file;
    }
    try {
        await withTimeout(
            ensurePdfjsLoaded(),
            FILE_PREVIEW_HYDRATE_TIMEOUT_MS,
            'pdf.js load timeout'
        );
        const pdf = await withTimeout(
            openPdfDocument(file.base64),
            FILE_PREVIEW_HYDRATE_TIMEOUT_MS,
            'pdf parse timeout'
        );
        file.page_count = pdf.numPages;
        const page = await pdf.getPage(1);
        const unscaled = page.getViewport({ scale: 1 });
        const scale = FILE_PREVIEW_THUMB_WIDTH_PX / (unscaled.width || FILE_PREVIEW_THUMB_WIDTH_PX);
        const viewport = page.getViewport({ scale: scale });
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(viewport.width));
        canvas.height = Math.max(1, Math.round(viewport.height));
        await page.render({ canvasContext: canvas.getContext('2d'), viewport: viewport }).promise;
        const dataUrl = canvas.toDataURL('image/jpeg', 0.72);
        file.preview_base64 = dataUrl.split(',')[1] || '';
        file.preview_mime = 'image/jpeg';
    } catch (err) {
        console.warn('PDF first-page preview failed:', err);
    }
    file._previewHydrated = true;
    rememberFileForPreview(file);
    return file;
}

function previewImageSrc(file) {
    const rec = mergeFileForPreview(file);
    if (rec.preview_base64) {
        return `data:${rec.preview_mime || 'image/jpeg'};base64,${rec.preview_base64}`;
    }
    if (isImageFile(rec) && rec.base64) {
        return `data:${rec.mime_type};base64,${rec.base64}`;
    }
    return '';
}

function buildWhatsAppAttachmentCardHTML(file) {
    const rec = mergeFileForPreview(file);
    rememberFileForPreview(rec);
    const name = escapeHtml(rec.name || 'file');
    const previewId = escapeHtml(rec.preview_id || '');
    const path = escapeHtml(rec.path || '');
    const meta = escapeHtml(buildFileMetaLine(rec));
    const officeKind = getOfficeFileKind(rec);
    const kindClass = officeKind
        ? ` wa-file-card--${officeKind}`
        : (isPdfFile(rec) ? ' wa-file-card--pdf' : (isAudioFile(rec) ? ' wa-file-card--audio' : ''));
    const thumb = previewImageSrc(rec);
    const previewInner = thumb
        ? `<img class="wa-file-card-thumb" src="${thumb}" alt="${name}" />`
        : `<div class="wa-file-card-placeholder">${typeof getFileIcon === 'function' ? getFileIcon(rec) : ''}</div>`;
    return `
        <button type="button" class="wa-file-card${kindClass}" data-preview-id="${previewId}" data-path="${path}" data-file-name="${name}" data-mime="${escapeHtml(rec.mime_type || '')}">
            <div class="wa-file-card-preview">${previewInner}</div>
            <div class="wa-file-card-footer">
                <div class="wa-file-card-icon">${typeof getFileIcon === 'function' ? getFileIcon(rec) : ''}</div>
                <div class="wa-file-card-details">
                    <span class="wa-file-card-name" title="${name}">${name}</span>
                    <span class="wa-file-card-meta">${meta}</span>
                </div>
            </div>
        </button>
    `;
}

let _activePreviewObjectUrl = null;
let _activePreviewGroup = [];
let _activePreviewIndex = 0;

function revokeActivePreviewUrl() {
    if (_activePreviewObjectUrl) {
        URL.revokeObjectURL(_activePreviewObjectUrl);
        _activePreviewObjectUrl = null;
    }
}

function closeWhatsAppFileViewer() {
    const overlay = document.getElementById('file-preview-overlay');
    if (overlay) overlay.classList.add('hidden');
    const stage = document.getElementById('file-preview-stage');
    if (stage) stage.innerHTML = '';
    revokeActivePreviewUrl();
}

function renderFilePreviewThumbs() {
    const thumbs = document.getElementById('file-preview-thumbs');
    if (!thumbs) return;
    if (_activePreviewGroup.length < 2) {
        thumbs.classList.add('hidden');
        thumbs.innerHTML = '';
        return;
    }
    thumbs.classList.remove('hidden');
    thumbs.innerHTML = _activePreviewGroup.map((file, idx) => {
        const rec = mergeFileForPreview(file);
        const src = previewImageSrc(rec);
        const active = idx === _activePreviewIndex ? ' is-active' : '';
        const label = escapeHtml(rec.name || 'file');
        const inner = src
            ? `<img src="${src}" alt="${label}" />`
            : `<span>${escapeHtml(getFileTypeLabel(rec))}</span>`;
        return `<button type="button" class="file-preview-thumb${active}" data-preview-index="${idx}" title="${label}">${inner}</button>`;
    }).join('');
}

async function paintWhatsAppFileViewer(file) {
    const rec = mergeFileForPreview(file);
    rememberFileForPreview(rec);
    const nameEl = document.getElementById('file-preview-name');
    const metaEl = document.getElementById('file-preview-meta');
    const stage = document.getElementById('file-preview-stage');
    if (nameEl) nameEl.textContent = rec.name || 'file';
    if (metaEl) metaEl.textContent = buildFileMetaLine(rec);
    if (!stage) return;

    revokeActivePreviewUrl();
    stage.innerHTML = '';
    const paintToken = ++_pdfPreviewSeq;

    if (isImageFile(rec) && (rec.base64 || rec.preview_base64)) {
        const img = document.createElement('img');
        img.className = 'file-preview-media';
        img.alt = rec.name || 'image';
        img.src = rec.base64
            ? `data:${rec.mime_type};base64,${rec.base64}`
            : previewImageSrc(rec);
        stage.appendChild(img);
        return;
    }
    if (isAudioFile(rec) && (rec.base64 || rec.path)) {
        const loading = document.createElement('div');
        loading.className = 'file-preview-empty';
        loading.textContent = filePreviewT('file_preview_loading', 'Loading preview…');
        stage.appendChild(loading);
        const url = await resolveMediaPlaybackUrl(rec);
        if (paintToken !== _pdfPreviewSeq || !stage.isConnected) return;
        stage.innerHTML = '';
        if (url) {
            _activePreviewObjectUrl = url.startsWith('blob:') ? url : null;
            const audio = document.createElement('audio');
            audio.className = 'file-preview-media file-preview-audio';
            audio.controls = true;
            audio.preload = 'metadata';
            audio.src = url;
            stage.appendChild(audio);
            return;
        }
    }
    if (isVideoFile(rec) && (rec.base64 || rec.path)) {
        const loading = document.createElement('div');
        loading.className = 'file-preview-empty';
        loading.textContent = filePreviewT('file_preview_loading', 'Loading preview…');
        stage.appendChild(loading);
        const url = await resolveMediaPlaybackUrl(rec);
        if (paintToken !== _pdfPreviewSeq || !stage.isConnected) return;
        stage.innerHTML = '';
        if (url) {
            _activePreviewObjectUrl = url.startsWith('blob:') ? url : null;
            const video = document.createElement('video');
            video.className = 'file-preview-media';
            video.controls = true;
            video.preload = 'metadata';
            video.src = url;
            stage.appendChild(video);
            return;
        }
    }
    if (isPdfFile(rec) && rec.base64) {
        const host = document.createElement('div');
        host.className = 'file-preview-pdf-pages';
        stage.appendChild(host);
        _pdfPreviewSeq += 1;
        void renderPdfPagesInto(host, rec, _pdfPreviewSeq);
        return;
    }
    const thumb = previewImageSrc(rec);
    if (thumb) {
        const img = document.createElement('img');
        img.className = 'file-preview-media file-preview-media--doc';
        img.alt = rec.name || 'file';
        img.src = thumb;
        stage.appendChild(img);
        return;
    }
    if (rec.path && window.pywebview && window.pywebview.api && window.pywebview.api.open_file_path) {
        const hint = document.createElement('div');
        hint.className = 'file-preview-empty';
        hint.textContent = filePreviewT('file_preview_open_native', 'Opening in your default app…');
        stage.appendChild(hint);
        window.pywebview.api.open_file_path(rec.path).catch((err) => {
            console.warn('Native file open failed:', err);
        });
        return;
    }
    const empty = document.createElement('div');
    empty.className = 'file-preview-empty';
    empty.textContent = filePreviewT('file_preview_unavailable', 'Preview unavailable');
    stage.appendChild(empty);
}

async function renderPdfPagesInto(host, rec, token) {
    const thumb = previewImageSrc(rec);
    if (thumb) {
        const img = document.createElement('img');
        img.className = 'file-preview-media file-preview-media--doc';
        img.alt = rec.name || 'PDF';
        img.src = thumb;
        host.appendChild(img);
    }
    try {
        const pdf = await openPdfDocument(rec.base64);
        if (token !== _pdfPreviewSeq || !host.isConnected) return;
        host.innerHTML = '';
        rec.page_count = pdf.numPages;
        rememberFileForPreview(rec);
        const metaEl = document.getElementById('file-preview-meta');
        if (metaEl) metaEl.textContent = buildFileMetaLine(rec);
        const maxPages = Math.min(pdf.numPages, FILE_PREVIEW_PDF_MAX_PAGES);
        const hostWidth = Math.max(host.clientWidth || 720, 320);
        for (let n = 1; n <= maxPages; n++) {
            if (token !== _pdfPreviewSeq || !host.isConnected) return;
            const page = await pdf.getPage(n);
            const unscaled = page.getViewport({ scale: 1 });
            const scale = Math.min(1.4, hostWidth / (unscaled.width || hostWidth));
            const viewport = page.getViewport({ scale: scale });
            const canvas = document.createElement('canvas');
            canvas.width = Math.max(1, Math.round(viewport.width));
            canvas.height = Math.max(1, Math.round(viewport.height));
            await page.render({ canvasContext: canvas.getContext('2d'), viewport: viewport }).promise;
            host.appendChild(canvas);
            if (n === 1 && !rec.preview_base64) {
                rec.preview_base64 = canvas.toDataURL('image/jpeg', 0.72).split(',')[1] || '';
                rec.preview_mime = 'image/jpeg';
                rememberFileForPreview(rec);
            }
        }
    } catch (err) {
        console.warn('PDF overlay render failed:', err);
        if (token !== _pdfPreviewSeq || !host.isConnected) return;
        if (host.querySelector('img, canvas')) return;
        host.innerHTML = '';
        const empty = document.createElement('div');
        empty.className = 'file-preview-empty';
        empty.textContent = filePreviewT('file_preview_unavailable', 'Preview unavailable');
        host.appendChild(empty);
    }
}

function openWhatsAppFileViewer(file, group) {
    const overlay = document.getElementById('file-preview-overlay');
    if (!overlay) return;
    _activePreviewGroup = Array.isArray(group) && group.length ? group : [file];
    _activePreviewIndex = Math.max(0, _activePreviewGroup.findIndex((item) => {
        const a = mergeFileForPreview(item);
        const b = mergeFileForPreview(file);
        return (a.preview_id && a.preview_id === b.preview_id) || (a.name && a.name === b.name);
    }));
    if (_activePreviewIndex < 0) _activePreviewIndex = 0;
    overlay.classList.remove('hidden');
    void paintWhatsAppFileViewer(_activePreviewGroup[_activePreviewIndex]);
    renderFilePreviewThumbs();
}

function collectMessageFileGroup(startEl) {
    const wrap = startEl && startEl.closest ? startEl.closest('.message-attachments') : null;
    if (!wrap) return [];
    return Array.from(wrap.querySelectorAll('.wa-file-card, .attachment-image-preview, .attachment-video-preview'))
        .map((el) => fileFromPreviewElement(el))
        .filter(Boolean);
}

function thumbSrcFromElement(el) {
    if (!el) return '';
    if (el.tagName === 'IMG' && el.src) return el.src;
    const thumb = el.querySelector ? el.querySelector('.wa-file-card-thumb') : null;
    return (thumb && thumb.src) || '';
}

function fileFromPreviewElement(el) {
    if (!el) return null;
    const previewId = el.getAttribute('data-preview-id') || '';
    const name = el.getAttribute('data-file-name') || el.getAttribute('alt') || 'file';
    const remembered = getRememberedFile(previewId) || findRememberedFileByName(name);
    const thumbSrc = thumbSrcFromElement(el);
    let thumbB64 = '';
    let thumbMime = 'image/jpeg';
    if (thumbSrc && thumbSrc.indexOf('data:') === 0) {
        const header = thumbSrc.split(',')[0] || '';
        thumbB64 = thumbSrc.split(',')[1] || '';
        thumbMime = header.replace('data:', '').split(';')[0] || 'image/jpeg';
    }
    if (remembered) {
        return Object.assign({ preview_id: remembered.preview_id || previewId }, remembered, {
            name: remembered.name || name,
            preview_base64: remembered.preview_base64 || thumbB64,
            preview_mime: remembered.preview_mime || thumbMime
        });
    }
    if (el.tagName === 'IMG' && thumbB64) {
        return {
            name: name || 'image',
            mime_type: el.getAttribute('data-mime') || thumbMime || 'image/jpeg',
            base64: thumbB64,
            preview_base64: thumbB64,
            preview_mime: thumbMime,
            preview_id: previewId
        };
    }
    return {
        preview_id: previewId,
        name: name,
        path: el.getAttribute('data-path') || '',
        mime_type: el.getAttribute('data-mime') || '',
        preview_base64: thumbB64,
        preview_mime: thumbMime
    };
}

function downloadPayloadForFile(file) {
    const rec = mergeFileForPreview(file);
    if (rec.base64) {
        return {
            data: rec.base64,
            mime: rec.mime_type || 'application/octet-stream',
            filename: rec.name || 'file'
        };
    }
    if (rec.preview_base64 && isImageFile(rec)) {
        return {
            data: rec.preview_base64,
            mime: rec.preview_mime || rec.mime_type || 'image/jpeg',
            filename: rec.name || 'image'
        };
    }
    return null;
}

function triggerBrowserDownload(payload) {
    const rec = { base64: payload.data, mime_type: payload.mime, name: payload.filename };
    const url = createFileObjectUrl(rec);
    if (!url) return;
    const a = document.createElement('a');
    a.href = url;
    a.download = payload.filename || 'file';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1500);
}

function downloadRememberedFile(file) {
    const rec = mergeFileForPreview(file);
    const payload = downloadPayloadForFile(rec);
    if (payload && window.pywebview && window.pywebview.api && typeof window.pywebview.api.save_file_to_downloads === 'function') {
        const dataUri = String(payload.data).indexOf(',') >= 0
            ? payload.data
            : `data:${payload.mime};base64,${payload.data}`;
        window.pywebview.api.save_file_to_downloads(dataUri, payload.filename)
            .then((res) => {
                if (res && res.status === 'success') {
                    console.log('File saved to Downloads:', res.filepath);
                } else if (res && res.message) {
                    console.error('save_file_to_downloads message:', res.message);
                }
            })
            .catch((err) => console.error('save_file_to_downloads error:', err));
        return;
    }
    if (payload) {
        triggerBrowserDownload(payload);
        return;
    }
    if (rec.path && window.pywebview && window.pywebview.api && window.pywebview.api.open_file_path) {
        window.pywebview.api.open_file_path(rec.path);
    }
}

function initWhatsAppFilePreviewUi() {
    const overlay = document.getElementById('file-preview-overlay');
    if (!overlay || overlay.dataset.bound === '1') return;
    overlay.dataset.bound = '1';

    const closeBtn = document.getElementById('file-preview-close');
    if (closeBtn) {
        closeBtn.title = filePreviewT('file_preview_close', 'Close preview');
        closeBtn.setAttribute('aria-label', closeBtn.title);
        closeBtn.addEventListener('click', closeWhatsAppFileViewer);
    }
    const downloadBtn = document.getElementById('file-preview-download');
    if (downloadBtn) {
        downloadBtn.title = filePreviewT('file_preview_download', 'Download');
        downloadBtn.setAttribute('aria-label', downloadBtn.title);
        downloadBtn.addEventListener('click', () => {
            const current = _activePreviewGroup[_activePreviewIndex];
            if (current) downloadRememberedFile(current);
        });
    }
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeWhatsAppFileViewer();
    });
    const thumbs = document.getElementById('file-preview-thumbs');
    if (thumbs) {
        thumbs.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-preview-index]');
            if (!btn) return;
            const idx = Number(btn.getAttribute('data-preview-index'));
            if (Number.isNaN(idx) || !_activePreviewGroup[idx]) return;
            _activePreviewIndex = idx;
            void paintWhatsAppFileViewer(_activePreviewGroup[idx]);
            renderFilePreviewThumbs();
        });
    }
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && overlay && !overlay.classList.contains('hidden')) {
            closeWhatsAppFileViewer();
        }
    });
    document.addEventListener('click', (e) => {
        const target = e.target.closest('.wa-file-card, .attachment-image-preview');
        if (!target) return;
        if (target.closest('#file-preview-overlay')) return;
        const file = fileFromPreviewElement(target);
        if (!file) return;
        e.preventDefault();
        if (shouldOpenNativePathOnly(file) && !fileHasInlineBytes(file)) {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.open_file_path) {
                window.pywebview.api.open_file_path(file.path || mergeFileForPreview(file).path);
            }
            return;
        }
        openWhatsAppFileViewer(file, collectMessageFileGroup(target));
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initWhatsAppFilePreviewUi);
} else {
    initWhatsAppFilePreviewUi();
}

window.hydrateFilePreview = hydrateFilePreview;
window.rememberFileForPreview = rememberFileForPreview;
window.buildWhatsAppAttachmentCardHTML = buildWhatsAppAttachmentCardHTML;
window.openWhatsAppFileViewer = openWhatsAppFileViewer;
window.closeWhatsAppFileViewer = closeWhatsAppFileViewer;
window.renderAttachmentPreview = renderPendingFiles;
window.escapeHtml = escapeHtml;
window.isPdfFile = isPdfFile;

// Render pending files
function renderPendingFiles() {
    const container = document.getElementById('attachments-preview');
    container.innerHTML = '';
    pendingFiles.forEach((file, index) => {
        rememberFileForPreview(file);
        const chip = document.createElement('div');
        const officeKind = getOfficeFileKind(file);
        const chipKind = officeKind
            ? `attachment-chip attachment-chip--${officeKind}`
            : 'attachment-chip';
        chip.className = (isPdfFile(file) || isImageFile(file) || previewImageSrc(file))
            ? `${chipKind} attachment-chip--wa-preview`
            : chipKind;

        const thumbSrc = previewImageSrc(file);
        if (thumbSrc) {
            const previewPane = document.createElement('div');
            previewPane.className = 'attachment-chip-preview';
            const thumb = document.createElement('img');
            thumb.src = thumbSrc;
            thumb.alt = file.name || 'file';
            previewPane.appendChild(thumb);
            chip.appendChild(previewPane);
        }

        // Icon
        const iconDiv = document.createElement('div');
        iconDiv.className = 'file-icon';
        iconDiv.innerHTML = getFileIcon(file);
        chip.appendChild(iconDiv);

        // Details
        const detailsDiv = document.createElement('div');
        detailsDiv.className = 'file-details';

        const nameRow = document.createElement('div');
        nameRow.className = 'file-name-row';

        const nameSpan = document.createElement('span');
        nameSpan.className = 'file-name';
        nameSpan.textContent = file.name;
        nameSpan.title = file.name; // Tooltip for full name
        nameRow.appendChild(nameSpan);

        // Close button next to filename
        const removeBtn = document.createElement('span');
        removeBtn.className = 'remove-btn';
        removeBtn.textContent = '✖';
        removeBtn.onclick = (e) => {
            e.stopPropagation();
            pendingFiles.splice(index, 1);
            renderPendingFiles();
            updateInputButtonsState();
        };
        nameRow.appendChild(removeBtn);

        detailsDiv.appendChild(nameRow);

        // Size
        if (file.size !== undefined) {
            const sizeDiv = document.createElement('div');
            sizeDiv.className = 'file-size';
            sizeDiv.textContent = formatFileSize(file.size);
            detailsDiv.appendChild(sizeDiv);
        }

        chip.appendChild(detailsDiv);
        container.appendChild(chip);
    });
    updateInputButtonsState();
}

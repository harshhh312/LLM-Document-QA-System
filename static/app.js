// ============================================================
// NexusDoc AI — app.js
// All DOM queries happen inside DOMContentLoaded so every
// getElementById call is guaranteed to find the element.
// ============================================================

// --------------- Application State ---------------
const state = {
    provider: 'ollama',
    providerReady: false,
    activeDocuments: [],
    chatHistory: [],
    isUploading: false,
    isGenerating: false,
    isConnected: true
};

let reconnectIntervalId = null;

// --------------- Boot ---------------
document.addEventListener('DOMContentLoaded', () => {
    initApp();
    setupEventListeners();
});

// ============================================================
// INIT
// ============================================================
async function initApp() {
    await checkConnectionStatus();
    if (state.isConnected) {
        await loadConfig();
        await loadDocuments();
    }
}

// ============================================================
// EVENT LISTENERS  (all element lookups are safe here)
// ============================================================
function setupEventListeners() {

    // --- Temperature slider ---
    const temperatureSlider = document.getElementById('temperature-slider');
    const tempVal            = document.getElementById('temp-val');
    if (temperatureSlider && tempVal) {
        temperatureSlider.addEventListener('input', (e) => {
            tempVal.textContent = e.target.value;
        });
    }

    // --- Save settings ---
    const saveSettingsBtn = document.getElementById('save-settings-btn');
    if (saveSettingsBtn) {
        saveSettingsBtn.addEventListener('click', saveConfig);
    }

    // --- Provider select (hidden input change is not user-triggered,
    //     but keep the listener for programmatic changes) ---
    const providerSelect = document.getElementById('provider-select');
    if (providerSelect) {
        providerSelect.addEventListener('change', toggleProviderFields);
    }

    // --- Drag & Drop ---
    const dropZone = document.getElementById('drop-zone');
    if (dropZone) {
        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropZone.classList.add('dragover');
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropZone.classList.remove('dragover');
            }, false);
        });

        dropZone.addEventListener('drop', (e) => {
            handleFiles(e.dataTransfer.files);
        });
    }

    // --- File input ---
    const fileInput = document.getElementById('file-input');
    if (fileInput) {
        fileInput.addEventListener('change', (e) => {
            handleFiles(e.target.files);
        });
    }

    // --- Chat input auto-resize ---
    const chatInput = document.getElementById('chat-input');
    const charCount = document.getElementById('char-count');
    const sendBtn   = document.getElementById('send-btn');
    if (chatInput) {
        chatInput.addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = this.scrollHeight + 'px';
            if (charCount) charCount.textContent = this.value.length;
            if (sendBtn)   sendBtn.disabled = this.value.trim() === '' || state.isGenerating;
        });

        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                const chatForm = document.getElementById('chat-form');
                if (chatForm) chatForm.requestSubmit();
            }
        });
    }

    // --- Chat form submit ---
    const chatForm = document.getElementById('chat-form');
    if (chatForm) {
        chatForm.addEventListener('submit', (e) => {
            e.preventDefault();
            sendQuery();
        });
    }

    // --- Clear chat ---
    const clearChatBtn = document.getElementById('clear-chat-btn');
    if (clearChatBtn) {
        clearChatBtn.addEventListener('click', clearChat);
    }

    // --- Retry connection ---
    const retryBtn = document.getElementById('retry-connection-btn');
    if (retryBtn) {
        retryBtn.addEventListener('click', async () => {
            retryBtn.disabled = true;
            const originalHTML = retryBtn.innerHTML;
            retryBtn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Retrying...';
            
            await checkConnectionStatus();
            
            retryBtn.disabled = false;
            retryBtn.innerHTML = originalHTML;
        });
    }

    // --- Workspace Spliter Resizing ---
    const splitter = document.getElementById('workspace-splitter');
    const explorer = document.getElementById('document-explorer');
    const workspace = document.querySelector('.workspace-area');
    if (splitter && explorer && workspace) {
        let isDragging = false;
        splitter.addEventListener('mousedown', (e) => {
            isDragging = true;
            splitter.classList.add('dragging');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
        });
        document.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            const containerRect = workspace.getBoundingClientRect();
            const relativeX = e.clientX - containerRect.left;
            let percentage = (relativeX / containerRect.width) * 100;
            percentage = Math.max(20, Math.min(80, percentage));
            explorer.style.width = `${percentage}%`;
        });
        document.addEventListener('mouseup', () => {
            if (isDragging) {
                isDragging = false;
                splitter.classList.remove('dragging');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
            }
        });
    }

    // --- Text Selection Floating Toolbar ---
    const viewport = document.getElementById('explorer-pages-viewport');
    const toolbar = document.getElementById('text-selection-toolbar');
    if (viewport && toolbar) {
        document.addEventListener('mouseup', (e) => {
            setTimeout(() => {
                const selection = window.getSelection();
                const selectedText = selection.toString().trim();
                
                if (selectedText && viewport.contains(selection.anchorNode)) {
                    const range = selection.getRangeAt(0);
                    const rect = range.getBoundingClientRect();
                    toolbar.style.top = `${rect.top - 45}px`;
                    toolbar.style.left = `${rect.left + rect.width / 2}px`;
                    toolbar.style.transform = 'translateX(-50%)';
                    toolbar.classList.remove('hidden');
                } else {
                    if (!e.target.closest('#text-selection-toolbar')) {
                        toolbar.classList.add('hidden');
                    }
                }
            }, 10);
        });
    }
}

// ============================================================
// UI PANEL TOGGLES  (called from onclick in HTML)
// ============================================================
function toggleSection(sectionId) {
    const section = document.getElementById(sectionId);
    if (!section) return;

    if (sectionId === 'advanced-settings') {
        section.classList.toggle('hidden');
        const icon = document.getElementById('advanced-toggle-icon');
        if (icon) {
            icon.className = section.classList.contains('hidden')
                ? 'fa-solid fa-plus icon-small'
                : 'fa-solid fa-minus icon-small';
        }
    } else if (sectionId === 'settings-body') {
        section.classList.toggle('hidden');
        const icon = document.getElementById('settings-toggle-icon');
        if (icon) {
            icon.className = section.classList.contains('hidden')
                ? 'fa-solid fa-chevron-down toggle-icon'
                : 'fa-solid fa-chevron-up toggle-icon';
        }
    }
}

function toggleProviderFields() {
    const providerSelect = document.getElementById('provider-select');
    const provider = providerSelect ? providerSelect.value : 'ollama';

    const geminiFields     = document.getElementById('gemini-fields');
    const ollamaFields     = document.getElementById('ollama-fields');
    const geminiModelGroup = document.getElementById('gemini-model-group');

    if (geminiFields)     geminiFields.classList.toggle('hidden', provider !== 'gemini');
    if (ollamaFields)     ollamaFields.classList.toggle('hidden', provider === 'gemini');
    if (geminiModelGroup) geminiModelGroup.classList.toggle('hidden', provider !== 'gemini');
}

// ============================================================
// API / CONNECTION STATUS
// ============================================================
async function pingBackend() {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 3000);
    try {
        const res = await fetch('/api/status', { signal: controller.signal });
        clearTimeout(timeoutId);
        if (!res.ok) return false;
        const data = await res.json();
        return data.status === 'healthy';
    } catch (e) {
        clearTimeout(timeoutId);
        return false;
    }
}

function startAutoReconnect() {
    if (reconnectIntervalId) return;
    reconnectIntervalId = setInterval(async () => {
        console.log('Attempting to reconnect to backend...');
        await checkConnectionStatus();
    }, 10000);
}

function handleFetchError(e, prefix = "Network error") {
    console.error(e);
    if (e.message && (e.message.includes("Failed to fetch") || e.message.includes("fetch") || e.name === "TypeError")) {
        return `${prefix}: Cannot reach the backend server. Ensure it's running on port 8000. Check your firewall or use "netstat -ano | findstr :8000" to see if the port is in use.`;
    }
    return `${prefix}: ${e.message || e}`;
}

async function checkConnectionStatus() {
    const isHealthy = await pingBackend();
    const banner    = document.getElementById('connection-banner');
    const badge     = document.getElementById('api-status-badge');
    const statusTxt = badge ? badge.querySelector('.status-text') : null;

    if (isHealthy) {
        // Hide warning banner
        if (banner) {
            banner.classList.add('hidden');
            document.body.classList.remove('banner-active');
        }

        // Stop polling
        if (reconnectIntervalId) {
            clearInterval(reconnectIntervalId);
            reconnectIntervalId = null;
        }

        const wasDisconnected = !state.isConnected;
        state.isConnected = true;

        try {
            const res  = await fetch('/api/status');
            const data = await res.json();

            state.provider      = data.provider      || 'ollama';
            state.providerReady = data.provider_ready || false;

            if (badge && statusTxt) {
                if (state.providerReady) {
                    badge.className         = 'badge badge-connected';
                    statusTxt.textContent   = state.provider === 'gemini'
                        ? 'Active (Gemini Ready)'
                        : 'Active (Ollama Ready)';
                } else {
                    badge.className       = 'badge badge-disconnected';
                    statusTxt.textContent = state.provider === 'gemini'
                        ? 'Gemini Offline (No Key)'
                        : 'Ollama Offline';

                    if (state.provider === 'gemini') {
                        showToast('Gemini API key is not configured. Please add one in settings.', 'warning');
                    } else {
                        showToast('Could not connect to local Ollama. Make sure Ollama is running.', 'warning');
                    }
                }
            }
        } catch (e) {
            console.error('Error fetching backend status details:', e);
        }

        if (wasDisconnected) {
            showToast('Reconnected to backend server!', 'success');
            await loadConfig();
            await loadDocuments();
        }
    } else {
        // Offline
        state.isConnected = false;

        if (banner) {
            banner.classList.remove('hidden');
            document.body.classList.add('banner-active');
        }

        if (badge)     badge.className       = 'badge badge-disconnected';
        if (statusTxt) statusTxt.textContent = 'Backend Offline';

        startAutoReconnect();
    }
}

// ============================================================
// CONFIG  (load & save)
// ============================================================
async function loadConfig() {
    try {
        const res    = await fetch('/api/config');
        const config = await res.json();

        const providerSelect        = document.getElementById('provider-select');
        const ollamaUrlInput        = document.getElementById('ollama-url-input');
        const ollamaChatModelInput  = document.getElementById('ollama-chat-model-input');
        const ollamaEmbModelInput   = document.getElementById('ollama-emb-model-input');
        const chunkSizeInput        = document.getElementById('chunk-size-input');
        const chunkOverlapInput     = document.getElementById('chunk-overlap-input');
        const temperatureSlider     = document.getElementById('temperature-slider');
        const tempVal               = document.getElementById('temp-val');

        if (providerSelect)       providerSelect.value       = config.llm_provider          || 'ollama';
        if (ollamaUrlInput)       ollamaUrlInput.value       = config.ollama_base_url        || 'http://localhost:11434';
        if (ollamaChatModelInput) ollamaChatModelInput.value = config.ollama_chat_model      || 'llama3';
        if (ollamaEmbModelInput)  ollamaEmbModelInput.value  = config.ollama_embedding_model || 'nomic-embed-text';
        if (chunkSizeInput)       chunkSizeInput.value       = config.chunk_size             || 600;
        if (chunkOverlapInput)    chunkOverlapInput.value    = config.chunk_overlap          || 100;
        if (temperatureSlider)    temperatureSlider.value    = config.temperature            || 0.3;
        if (tempVal)              tempVal.textContent        = config.temperature            || 0.3;

        toggleProviderFields();
    } catch (e) {
        console.error('Failed to load settings from server:', e);
    }
}

async function saveConfig() {
    const saveSettingsBtn      = document.getElementById('save-settings-btn');
    const chunkSizeInput       = document.getElementById('chunk-size-input');
    const chunkOverlapInput    = document.getElementById('chunk-overlap-input');
    const temperatureSlider    = document.getElementById('temperature-slider');
    const providerSelect       = document.getElementById('provider-select');
    const ollamaUrlInput       = document.getElementById('ollama-url-input');
    const ollamaChatModelInput = document.getElementById('ollama-chat-model-input');
    const ollamaEmbModelInput  = document.getElementById('ollama-emb-model-input');

    const payload = {
        chunk_size:              parseInt(chunkSizeInput       ? chunkSizeInput.value       : 600),
        chunk_overlap:           parseInt(chunkOverlapInput    ? chunkOverlapInput.value    : 100),
        temperature:             parseFloat(temperatureSlider  ? temperatureSlider.value    : 0.3),
        llm_provider:            providerSelect       ? providerSelect.value                : 'ollama',
        ollama_base_url:         ollamaUrlInput       ? ollamaUrlInput.value.trim()        : 'http://localhost:11434',
        ollama_chat_model:       ollamaChatModelInput ? ollamaChatModelInput.value.trim()  : 'llama3',
        ollama_embedding_model:  ollamaEmbModelInput  ? ollamaEmbModelInput.value.trim()   : 'nomic-embed-text'
    };

    try {
        if (saveSettingsBtn) {
            saveSettingsBtn.disabled   = true;
            saveSettingsBtn.innerHTML  = '<i class="fa-solid fa-circle-notch fa-spin"></i> Saving...';
        }

        const res = await fetch('/api/config', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(payload)
        });

        if (res.ok) {
            showToast('Configuration applied successfully!', 'success');
            await checkConnectionStatus();
            await loadConfig();
        } else {
            const err = await res.json();
            showToast(err.detail || 'Failed to save configuration.', 'error');
        }
    } catch (e) {
        showToast(handleFetchError(e, 'Failed to save configuration'), 'error');
    } finally {
        if (saveSettingsBtn) {
            saveSettingsBtn.disabled  = false;
            saveSettingsBtn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> Apply Settings';
        }
    }
}

// ============================================================
// FILE UPLOAD
// ============================================================
function handleFiles(files) {
    if (!files || files.length === 0) return;

    const uploadQueue = Array.from(files);

    const uploadNext = async () => {
        if (uploadQueue.length === 0) {
            const container = document.getElementById('upload-progress-container');
            if (container) container.classList.add('hidden');
            await loadDocuments();
            return;
        }

        const file    = uploadQueue.shift();
        const fileExt = '.' + file.name.split('.').pop().toLowerCase();

        // Validate extension
        if (!['.pdf', '.txt', '.md', '.markdown'].includes(fileExt)) {
            showToast(`"${file.name}" has an unsupported format.`, 'error');
            uploadNext();
            return;
        }

        // Validate size (10 MB)
        if (file.size > 10 * 1024 * 1024) {
            showToast(`"${file.name}" is too large. Max size is 10 MB.`, 'error');
            uploadNext();
            return;
        }

        await performUpload(file);
        uploadNext();
    };

    uploadNext();
}

async function performUpload(file) {
    const container    = document.getElementById('upload-progress-container');
    const filenameEl   = document.getElementById('upload-filename');
    const statusTextEl = document.getElementById('upload-status-text');
    const progressBar  = document.getElementById('upload-progress-bar');

    if (container)    container.classList.remove('hidden');
    if (filenameEl)   filenameEl.textContent   = file.name;
    if (statusTextEl) statusTextEl.textContent = 'Uploading file...';
    if (progressBar)  progressBar.style.width  = '20%';

    // Animated progress while waiting for server
    const progressInterval = setInterval(() => {
        if (!progressBar) return;
        const current = parseInt(progressBar.style.width) || 20;
        if (current < 80) progressBar.style.width = (current + 10) + '%';
    }, 400);

    try {
        if (statusTextEl) statusTextEl.textContent = 'Parsing & Indexing...';

        const formData = new FormData();
        formData.append('file', file);

        const res = await fetch('/api/documents/upload', {
            method: 'POST',
            body:   formData
        });

        clearInterval(progressInterval);

        if (res.ok) {
            if (progressBar) progressBar.style.width = '100%';
            showToast(`"${file.name}" indexed successfully!`, 'success');
        } else {
            const err = await res.json().catch(() => ({}));
            showToast(err.detail || `Failed to process "${file.name}".`, 'error');
            if (progressBar) progressBar.style.width = '0%';
        }
    } catch (e) {
        clearInterval(progressInterval);
        showToast(handleFetchError(e, `Failed to upload "${file.name}"`), 'error');
        if (progressBar) progressBar.style.width = '0%';
    }
}

// ============================================================
// DOCUMENT LIST
// ============================================================
async function loadDocuments() {
    const docCount    = document.getElementById('doc-count');
    const documentList = document.getElementById('document-list');

    try {
        const res  = await fetch('/api/documents');
        const docs = await res.json();

        state.activeDocuments = docs;
        if (docCount) docCount.textContent = docs.length;

        if (!documentList) return;

        if (docs.length === 0) {
            documentList.innerHTML = `
                <div class="empty-docs-placeholder">
                    <i class="fa-solid fa-file-excel placeholder-icon"></i>
                    <p>No documents uploaded yet.</p>
                </div>`;
            return;
        }

        documentList.innerHTML = '';
        docs.forEach(doc => {
            let iconClass = 'fa-file-lines';
            if (doc.doc_name.endsWith('.pdf')) iconClass = 'fa-file-pdf';
            if (doc.doc_name.endsWith('.md') || doc.doc_name.endsWith('.markdown')) iconClass = 'fa-file-code';

            const item = document.createElement('div');
            item.className = 'document-item';
            item.innerHTML = `
                <div class="doc-info" title="${escapeHtml(doc.doc_name)}">
                    <i class="fa-solid ${iconClass} doc-icon"></i>
                    <div>
                        <div class="doc-name">${escapeHtml(doc.doc_name)}</div>
                        <div class="doc-meta">${doc.file_size} • ${doc.chunk_count} chunks</div>
                    </div>
                </div>
                <div class="doc-actions">
                    <button class="btn-insight-doc"
                        onclick="viewDocInsights('${encodeURIComponent(doc.doc_name)}')"
                        title="View insights dashboard">
                        <i class="fa-solid fa-chart-line"></i>
                    </button>
                    <button class="btn-delete-doc"
                        onclick="deleteDocument('${encodeURIComponent(doc.doc_name)}')"
                        title="Delete from index">
                        <i class="fa-solid fa-trash-can"></i>
                    </button>
                    <button class="btn-explore-doc"
                        onclick="openDocumentExplorer('${encodeURIComponent(doc.doc_name)}')"
                        title="Explore document">
                        <i class="fa-solid fa-compass"></i>
                    </button>
                </div>`;
            documentList.appendChild(item);
        });

        if (typeof populateDocumentDropdowns === 'function') {
            populateDocumentDropdowns();
        }
    } catch (e) {
        console.error('Failed to load document list:', e);
    }
}

async function deleteDocument(encodedDocName) {
    const docName = decodeURIComponent(encodedDocName);
    if (!confirm(`Delete "${docName}"? This removes its chunks from the index.`)) return;

    try {
        const res = await fetch(`/api/documents/${encodeURIComponent(docName)}`, { method: 'DELETE' });
        if (res.ok) {
            showToast(`Deleted "${docName}" successfully.`, 'success');
            await loadDocuments();
            await checkConnectionStatus();
        } else {
            showToast('Failed to delete document.', 'error');
        }
    } catch (e) {
        showToast(handleFetchError(e, 'Failed to delete document'), 'error');
    }
}

// ============================================================
// CHAT
// ============================================================
function useSuggestion(text) {
    const chatInput = document.getElementById('chat-input');
    const sendBtn   = document.getElementById('send-btn');
    if (!chatInput) return;
    chatInput.value        = text;
    chatInput.style.height = 'auto';
    chatInput.style.height = chatInput.scrollHeight + 'px';
    if (sendBtn) sendBtn.disabled = false;
    chatInput.focus();
}

async function sendQuery() {
    const chatInput = document.getElementById('chat-input');
    const charCount = document.getElementById('char-count');
    const sendBtn   = document.getElementById('send-btn');

    if (!chatInput) return;
    const query = chatInput.value.trim();
    if (!query || state.isGenerating) return;

    if (state.provider === 'ollama' && !state.providerReady) {
        showToast('Ollama seems to be offline. Make sure it is running and apply settings.', 'warning');
        return;
    }

    // Reset input
    chatInput.value        = '';
    chatInput.style.height = 'auto';
    if (charCount) charCount.textContent = 0;
    if (sendBtn)   sendBtn.disabled = true;

    appendMessage('user', query);

    state.isGenerating = true;
    appendTypingIndicator();

    try {
        const res = await fetch('/api/chat', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ query, history: state.chatHistory })
        });

        removeTypingIndicator();

        if (res.ok) {
            const data = await res.json();
            appendMessage('assistant', data.answer, data.sources);
            state.chatHistory.push({ role: 'user',      content: query });
            state.chatHistory.push({ role: 'assistant', content: data.answer });
        } else {
            const err = await res.json().catch(() => ({}));
            appendMessage('assistant', `⚠️ **Error**: ${err.detail || 'Something went wrong.'}`);
        }
    } catch (e) {
        removeTypingIndicator();
        appendMessage('assistant', `⚠️ **Network error**: ${handleFetchError(e, 'Could not reach the chatbot API')}`);
    } finally {
        state.isGenerating = false;
        if (sendBtn && chatInput) {
            sendBtn.disabled = chatInput.value.trim() === '';
        }
    }
}

// ============================================================
// DOM RENDERING HELPERS
// ============================================================
function scrollToBottom(force = false) {
    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) return;

    const threshold = 150; // pixels from the bottom
    const isNearBottom = chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight <= threshold;

    if (force || isNearBottom) {
        chatMessages.scrollTo({
            top: chatMessages.scrollHeight,
            behavior: 'smooth'
        });
    }
}

function appendMessage(role, content, sources = []) {
    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) return;

    // Remove welcome card on first user message
    const welcome = chatMessages.querySelector('.welcome-card');
    if (welcome) welcome.remove();

    const container = document.createElement('div');
    container.className = `message message-${role}`;

    const bubble = document.createElement('div');
    bubble.className  = 'message-bubble';
    bubble.innerHTML  = formatMarkdown(content);
    container.appendChild(bubble);

    if (sources && sources.length > 0 && role === 'assistant') {
        const details = document.createElement('details');
        details.className = 'citations-panel';
        details.innerHTML = `
            <summary class="citations-summary">
                <i class="fa-solid fa-scroll"></i> Referenced Documents (${sources.length})
            </summary>
            <div class="citations-list">
                ${sources.map((src, i) => `
                    <div class="citation-item">
                        <div class="citation-header">
                            <span>#${i + 1} • ${escapeHtml(src.doc_name)}</span>
                            <span>Page ${src.metadata?.page || 1} (${(src.similarity * 100).toFixed(0)}% match)</span>
                        </div>
                        <div class="citation-snippet">"${escapeHtml(src.text)}"</div>
                    </div>`).join('')}
            </div>`;
        container.appendChild(details);
        
        // Adjust scroll when references details are toggled open
        details.addEventListener('toggle', () => {
            if (details.open) {
                setTimeout(() => scrollToBottom(true), 50);
            }
        });
    }

    chatMessages.appendChild(container);
    scrollToBottom(role === 'user');
}

function appendTypingIndicator() {
    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) return;
    const indicator   = document.createElement('div');
    indicator.id        = 'chat-typing-indicator';
    indicator.className = 'typing-indicator';
    indicator.innerHTML = `
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>`;
    chatMessages.appendChild(indicator);
    scrollToBottom(false);
}

function removeTypingIndicator() {
    const el = document.getElementById('chat-typing-indicator');
    if (el) el.remove();
}

function clearChat() {
    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) return;

    if (!confirm('Clear chat history? (Your documents will remain indexed.)')) return;

    state.chatHistory = [];
    chatMessages.innerHTML = `
        <div class="welcome-card">
            <div class="welcome-icon"><i class="fa-solid fa-wand-magic-sparkles"></i></div>
            <h2>Ask anything about your documents</h2>
            <p>Upload files like manuals, code documentation, or PDFs, and chat with them instantly using local Ollama. Your context stays strictly relevant.</p>
            <div class="quick-start-suggestions">
                <h4>Quick start examples:</h4>
                <div class="suggestions-grid">
                    <button class="suggestion-btn" onclick="useSuggestion('Summarize the main points of the uploaded document.')">
                        "Summarize the main points..."
                    </button>
                    <button class="suggestion-btn" onclick="useSuggestion('What are the key findings or takeaways?')">
                        "What are the key findings?"
                    </button>
                    <button class="suggestion-btn" onclick="useSuggestion('Find any action items or critical deadlines.')">
                        "Find action items..."
                    </button>
                </div>
            </div>
        </div>`;
}

// ============================================================
// TOAST NOTIFICATIONS
// ============================================================
let toastTimeout;
function showToast(message, type = 'info') {
    const toast        = document.getElementById('toast-notification');
    const toastMessage = toast ? toast.querySelector('.toast-message') : null;
    const toastIcon    = toast ? toast.querySelector('.toast-icon')    : null;

    if (!toast || !toastMessage) return;

    clearTimeout(toastTimeout);
    toastMessage.textContent = message;
    toast.className = `toast show toast-${type}`;

    if (toastIcon) {
        const icons = {
            success: 'fa-circle-check',
            error:   'fa-circle-exclamation',
            warning: 'fa-triangle-exclamation'
        };
        toastIcon.className = `toast-icon fa-solid ${icons[type] || 'fa-circle-info'}`;
    }

    toastTimeout = setTimeout(() => toast.classList.remove('show'), 4500);
}

// ============================================================
// MARKDOWN FORMATTER
// ============================================================
function formatMarkdown(text) {
    if (!text) return '';

    let out = escapeHtml(text);

    // Fenced code blocks  (``` ... ```)
    out = out.replace(/```(\w*)\n([\s\S]*?)```/g, (_m, lang, code) =>
        `<pre><code class="language-${lang || 'plaintext'}">${code.trim()}</code></pre>`
    );

    // Inline code
    out = out.replace(/`([^`\n]+)`/g, '<code>$1</code>');

    // Bold
    out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Italic
    out = out.replace(/\*([^*]+)\*/g, '<em>$1</em>');

    // Bullet lists
    out = out.replace(/^\s*[-*]\s+(.+)$/gm, '<li>$1</li>');
    out = out.replace(/(<li>[\s\S]*?<\/li>)/g, '<ul>$1</ul>');

    // Paragraphs
    const parts = out.split(/\n\n+/);
    out = parts.map(p => {
        const t = p.trim();
        if (t.startsWith('<pre>') || t.startsWith('<ul>') || t.startsWith('<li>')) return p;
        return `<p>${p.replace(/\n/g, '<br>')}</p>`;
    }).join('');

    return out;
}

// ============================================================
// UTILITY
// ============================================================
function escapeHtml(str) {
    return String(str)
        .replace(/&/g,  '&amp;')
        .replace(/</g,  '&lt;')
        .replace(/>/g,  '&gt;')
        .replace(/"/g,  '&quot;')
        .replace(/'/g,  '&#039;');
}

// ============================================================
// DOCUMENT SUMMARY & DASHBOARD INSIGHTS LOGIC
// ============================================================

// Extend application state
state.activeTab = 'chat';
state.activeInsights = null;
state.comparisonMode = false;
state.activeEntityTab = 'people';

// Global references to Chart.js instances to properly destroy/re-create them
let topicChartInstance = null;
let keywordChartInstance = null;
let compKeywordChartInstance = null;

// Tab management
window.switchTab = function(tab) {
    state.activeTab = tab;
    
    const tabChat = document.getElementById('tab-chat');
    const tabInsights = document.getElementById('tab-insights');
    const chatMessages = document.getElementById('chat-messages');
    const chatInputArea = document.getElementById('chat-input-container');
    const insightsView = document.getElementById('insights-view');
    
    if (!tabChat || !tabInsights || !chatMessages || !chatInputArea || !insightsView) return;
    
    if (tab === 'chat') {
        tabChat.classList.add('active');
        tabInsights.classList.remove('active');
        chatMessages.classList.remove('hidden');
        chatInputArea.classList.remove('hidden');
        insightsView.classList.add('hidden');
    } else {
        tabChat.classList.remove('active');
        tabInsights.classList.add('active');
        chatMessages.classList.add('hidden');
        chatInputArea.classList.add('hidden');
        insightsView.classList.remove('hidden');
        
        // Auto load insights if a document is selected in dropdown
        const select = document.getElementById('insight-doc-select');
        if (select && select.value) {
            loadActiveDocInsights();
        } else if (state.activeDocuments.length > 0 && select) {
            // Default to first doc if none selected
            select.value = state.activeDocuments[0].doc_name;
            loadActiveDocInsights();
        }
    }
};

// Populate selector dropdowns for dashboard and comparison
window.populateDocumentDropdowns = function() {
    const select = document.getElementById('insight-doc-select');
    const comp1 = document.getElementById('comp-doc-1');
    const comp2 = document.getElementById('comp-doc-2');
    
    if (!select || !comp1 || !comp2) return;
    
    const prevSelectVal = select.value;
    const prevComp1Val = comp1.value;
    const prevComp2Val = comp2.value;
    
    // Clear
    select.innerHTML = '<option value="">-- Select a document --</option>';
    comp1.innerHTML = '<option value="">-- Select document 1 --</option>';
    comp2.innerHTML = '<option value="">-- Select document 2 --</option>';
    
    state.activeDocuments.forEach(doc => {
        const optionHTML = `<option value="${escapeHtml(doc.doc_name)}">${escapeHtml(doc.doc_name)}</option>`;
        select.insertAdjacentHTML('beforeend', optionHTML);
        comp1.insertAdjacentHTML('beforeend', optionHTML);
        comp2.insertAdjacentHTML('beforeend', optionHTML);
    });
    
    // Restore previous selection if still exists
    if (state.activeDocuments.some(d => d.doc_name === prevSelectVal)) select.value = prevSelectVal;
    if (state.activeDocuments.some(d => d.doc_name === prevComp1Val)) comp1.value = prevComp1Val;
    if (state.activeDocuments.some(d => d.doc_name === prevComp2Val)) comp2.value = prevComp2Val;
};

// Sidebar click triggers
window.viewDocInsights = function(encodedDocName) {
    const docName = decodeURIComponent(encodedDocName);
    switchTab('insights');
    
    const select = document.getElementById('insight-doc-select');
    if (select) {
        select.value = docName;
        loadActiveDocInsights();
    }
};

// Fetch and load dashboard insights details
window.loadActiveDocInsights = async function() {
    const select = document.getElementById('insight-doc-select');
    if (!select) return;
    
    const docName = select.value;
    const emptyState = document.getElementById('insights-empty-state');
    const loadingState = document.getElementById('insights-loading-state');
    const dashboard = document.getElementById('insights-dashboard');
    
    if (!docName) {
        if (emptyState) emptyState.classList.remove('hidden');
        if (loadingState) loadingState.classList.add('hidden');
        if (dashboard) dashboard.classList.add('hidden');
        return;
    }
    
    // Show loading state
    if (emptyState) emptyState.classList.add('hidden');
    if (loadingState) loadingState.classList.remove('hidden');
    if (dashboard) dashboard.classList.add('hidden');
    
    try {
        const res = await fetch(`/api/documents/${encodeURIComponent(docName)}/summary`);
        if (!res.ok) throw new Error('Failed to retrieve summary insights');
        
        const data = await res.json();
        state.activeInsights = data;
        
        // 1. Populate Executive Summary
        document.getElementById('insights-summary-text').innerHTML = formatMarkdown(data.summary);
        document.getElementById('summary-word-count').textContent = data.statistics.total_words;
        document.getElementById('summary-char-count').textContent = data.statistics.total_characters;
        
        // 2. Populate Metrics stats card
        document.getElementById('stat-pages').textContent = data.statistics.total_pages;
        document.getElementById('stat-words').textContent = data.statistics.total_words;
        document.getElementById('stat-reading-time').textContent = data.statistics.reading_time_min + ' min';
        document.getElementById('stat-language').textContent = data.statistics.language;
        document.getElementById('stat-file-size').textContent = data.statistics.file_size;
        document.getElementById('stat-uploaded').textContent = data.statistics.added_at;
        
        // Readability gauge
        const easeScore = data.statistics.readability_score;
        document.getElementById('readability-score').textContent = easeScore;
        document.getElementById('readability-label').textContent = data.statistics.readability_label;
        document.getElementById('readability-progress-bar').style.width = easeScore + '%';
        
        // 3. Populate Key Findings List
        const pointsList = document.getElementById('insights-key-points-list');
        pointsList.innerHTML = '';
        if (data.key_points && data.key_points.length > 0) {
            data.key_points.forEach(pt => {
                const badgeClass = pt.score.toLowerCase() === 'high' ? 'badge-high' : (pt.score.toLowerCase() === 'medium' ? 'badge-medium' : 'badge-low');
                pointsList.insertAdjacentHTML('beforeend', `
                    <div class="key-point-item">
                        <div class="key-point-badge-col">
                            <span class="badge-importance ${badgeClass}">${pt.score}</span>
                            <button class="btn-page-jump" onclick="jumpToPageChat('${escapeHtml(docName)}', ${pt.page}, '${escapeHtml(pt.point.substring(0, 30))}')">
                                Page ${pt.page}
                            </button>
                        </div>
                        <div class="key-point-text">${escapeHtml(pt.point)}</div>
                    </div>`);
            });
        } else {
            pointsList.innerHTML = '<p class="empty-docs-placeholder">No key points extracted.</p>';
        }
        
        // 4. Render Topic Distribution Doughnut
        renderTopicChart(data.topics);
        
        // 5. Populate Sentiment score gauge and section breakdown
        const sentBadge = document.getElementById('sentiment-badge');
        const badgeSentClass = data.sentiment.overall.toLowerCase() === 'positive' ? 'badge-sent-pos' : (data.sentiment.overall.toLowerCase() === 'negative' ? 'badge-sent-neg' : 'badge-sent-neu');
        sentBadge.className = 'sentiment-badge ' + badgeSentClass;
        sentBadge.textContent = data.sentiment.overall;
        
        // Position gauge needle (-1 to +1 range -> 0% to 100%)
        const needlePercent = ((data.sentiment.score + 1) / 2) * 100;
        document.getElementById('sentiment-gauge-needle').style.left = needlePercent + '%';
        
        // Emotional tone tags
        const tonesContainer = document.getElementById('sentiment-tones');
        tonesContainer.innerHTML = '';
        if (data.sentiment.tones && data.sentiment.tones.length > 0) {
            data.sentiment.tones.forEach(t => {
                tonesContainer.insertAdjacentHTML('beforeend', `<span class="tone-tag">${escapeHtml(t)}</span>`);
            });
        }
        
        // Sections breakdown list
        const sectionsList = document.getElementById('sentiment-sections-list');
        sectionsList.innerHTML = '';
        if (data.sentiment.sections && data.sentiment.sections.length > 0) {
            data.sentiment.sections.forEach(sec => {
                const sClass = sec.sentiment.toLowerCase() === 'positive' ? 'sent-pos' : (sec.sentiment.toLowerCase() === 'negative' ? 'sent-neg' : 'sent-neu');
                sectionsList.insertAdjacentHTML('beforeend', `
                    <div class="section-sent-item ${sClass}">
                        <div class="section-sent-header">
                            <span>${escapeHtml(sec.section)}</span>
                            <span>${sec.sentiment}</span>
                        </div>
                        <div class="section-sent-reason">${escapeHtml(sec.reason)}</div>
                    </div>`);
            });
        } else {
            sectionsList.innerHTML = '<p class="empty-docs-placeholder">No section sentiment details.</p>';
        }
        
        // 6. Render Keyword frequency bar & tag cloud
        renderKeywordChart(data.keywords);
        
        // 7. Populate entities tabs
        state.activeEntityTab = 'people';
        switchEntityTab('people');
        
        // Switch view states
        if (loadingState) loadingState.classList.add('hidden');
        if (dashboard) dashboard.classList.remove('hidden');
        
    } catch (e) {
        showToast(handleFetchError(e, 'Error analyzing document'), 'error');
        if (loadingState) loadingState.classList.add('hidden');
        if (emptyState) emptyState.classList.remove('hidden');
    }
};

// Render Doughnut Chart for Topics
function renderTopicChart(topics) {
    if (topicChartInstance) topicChartInstance.destroy();
    
    const listContainer = document.getElementById('insights-topics-list');
    listContainer.innerHTML = '';
    
    if (!topics || topics.length === 0) {
        listContainer.innerHTML = '<p class="empty-docs-placeholder">No topics clustered.</p>';
        return;
    }
    
    const colors = ['#667eea', '#764ba2', '#48bb78', '#ed8936', '#3182ce'];
    
    // Build list items
    topics.forEach((t, i) => {
        const c = colors[i % colors.length];
        listContainer.insertAdjacentHTML('beforeend', `
            <div class="topic-list-item" title="Keywords: ${escapeHtml(t.keywords.join(', '))}">
                <span class="topic-item-left">
                    <span class="topic-color-dot" style="background-color: ${c}"></span>
                    ${escapeHtml(t.topic)}
                </span>
                <span class="topic-item-right">${t.percentage}% (${t.mentions} mentions)</span>
            </div>`);
    });
    
    const ctx = document.getElementById('topicChart').getContext('2d');
    topicChartInstance = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: topics.map(t => t.topic),
            datasets: [{
                data: topics.map(t => t.percentage),
                backgroundColor: colors.slice(0, topics.length),
                borderWidth: 1,
                borderColor: '#ffffff'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return ` ${context.label}: ${context.raw}%`;
                        }
                    }
                }
            },
            cutout: '65%'
        }
    });
}

// Render Bar Chart for Keyword Frequency and keyword cloud
function renderKeywordChart(keywords) {
    if (keywordChartInstance) keywordChartInstance.destroy();
    
    const cloud = document.getElementById('keyword-cloud');
    cloud.innerHTML = '';
    
    if (!keywords || keywords.length === 0) {
        cloud.innerHTML = '<p class="empty-docs-placeholder">No keywords extracted.</p>';
        return;
    }
    
    // Tag cloud: size tags based on count relative to max count
    const counts = keywords.map(k => k.count);
    const maxCount = Math.max(...counts, 1);
    
    keywords.forEach(k => {
        // Font size bounds between 0.75rem and 1.35rem
        const size = 0.75 + ((k.count / maxCount) * 0.6);
        cloud.insertAdjacentHTML('beforeend', `
            <span class="cloud-tag" 
                style="font-size: ${size}rem;" 
                onclick="queryKeywordChat('${escapeHtml(k.word)}')"
                title="${k.count} mentions">${escapeHtml(k.word)}</span>`);
    });
    
    const ctx = document.getElementById('keywordChart').getContext('2d');
    keywordChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: keywords.map(k => k.word),
            datasets: [{
                label: 'Frequency',
                data: keywords.map(k => k.count),
                backgroundColor: 'rgba(102, 126, 234, 0.85)',
                borderColor: 'rgba(102, 126, 234, 1)',
                borderWidth: 1,
                borderRadius: 4,
                hoverBackgroundColor: 'rgba(118, 75, 162, 0.95)'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { display: false } },
                y: { 
                    beginAtZero: true,
                    ticks: { precision: 0 }
                }
            }
        }
    });
}

// Interactive Entity filter switching
window.switchEntityTab = function(entityType) {
    state.activeEntityTab = entityType;
    
    const tabs = ['people', 'organizations', 'dates', 'locations', 'monetary_values'];
    tabs.forEach(t => {
        const id = t === 'organizations' ? 'orgs' : (t === 'monetary_values' ? 'money' : t);
        const btn = document.getElementById('ent-tab-' + id);
        if (btn) btn.classList.toggle('active', t === entityType);
    });
    
    const container = document.getElementById('entity-list-content');
    container.innerHTML = '';
    
    if (!state.activeInsights || !state.activeInsights.entities) return;
    
    const entities = state.activeInsights.entities[entityType] || [];
    if (entities.length > 0) {
        entities.forEach(ent => {
            container.insertAdjacentHTML('beforeend', `
                <span class="entity-pill">
                    <i class="fa-solid fa-tag"></i> ${escapeHtml(ent.name)}
                    <span class="entity-pill-count">${ent.mentions}</span>
                </span>`);
        });
    } else {
        container.innerHTML = '<p class="empty-docs-placeholder" style="width:100%;">No entity metrics detected for this category.</p>';
    }
};

// Copy summary text helper
window.copySummaryToClipboard = function() {
    if (!state.activeInsights || !state.activeInsights.summary) return;
    
    // Create text snippet from summary text block (strip markdown)
    const rawText = state.activeInsights.summary;
    navigator.clipboard.writeText(rawText).then(() => {
        showToast('Summary copied to clipboard!', 'success');
    }).catch(() => {
        showToast('Failed to copy summary to clipboard.', 'error');
    });
};

// Custom focus area summary regeneration
window.regenerateActiveSummary = async function() {
    const select = document.getElementById('insight-doc-select');
    if (!select) return;
    
    const docName = select.value;
    const focusInput = document.getElementById('summary-focus-input');
    const regenerateBtn = document.getElementById('btn-regenerate-summary');
    
    if (!docName || !focusInput || !regenerateBtn) return;
    
    const focusText = focusInput.value.trim();
    if (!focusText) {
        showToast('Please specify a focus topic.', 'warning');
        return;
    }
    
    try {
        regenerateBtn.disabled = true;
        regenerateBtn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Processing...';
        
        const res = await fetch(`/api/documents/${encodeURIComponent(docName)}/regenerate-summary`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ focus: focusText })
        });
        
        if (!res.ok) throw new Error('Regeneration request failed');
        
        const data = await res.json();
        
        // Update summary text block and state
        state.activeInsights.summary = data.summary;
        document.getElementById('insights-summary-text').innerHTML = formatMarkdown(data.summary);
        document.getElementById('summary-word-count').textContent = data.statistics.total_words;
        document.getElementById('summary-char-count').textContent = data.statistics.total_characters;
        
        focusInput.value = '';
        showToast('Focused summary generated successfully!', 'success');
    } catch (e) {
        showToast(handleFetchError(e, 'Error regenerating summary'), 'error');
    } finally {
        regenerateBtn.disabled = false;
        regenerateBtn.innerHTML = '<i class="fa-solid fa-arrows-rotate"></i> Regenerate';
    }
};

// Jump-to-page chat suggestion link trigger
window.jumpToPageChat = function(docName, pageNum, textSnippet) {
    switchTab('chat');
    useSuggestion(`Explain the finding on Page ${pageNum} of "${docName}" regarding "${textSnippet}..."`);
};

// Keyword cloud click query trigger
window.queryKeywordChat = function(keyword) {
    switchTab('chat');
    useSuggestion(`Give me a detailed breakdown of what the documents say about "${keyword}".`);
};

// Comparison Mode layout toggle
window.toggleComparisonMode = function() {
    const dashboard = document.getElementById('insights-dashboard');
    const compDashboard = document.getElementById('comparison-dashboard');
    const select = document.getElementById('insight-doc-select');
    const comp1 = document.getElementById('comp-doc-1');
    const comp2 = document.getElementById('comp-doc-2');
    
    if (!dashboard || !compDashboard || !select || !comp1 || !comp2) return;
    
    state.comparisonMode = !state.comparisonMode;
    
    if (state.comparisonMode) {
        dashboard.classList.add('hidden');
        compDashboard.classList.remove('hidden');
        
        // Auto select current active doc in base selector
        if (select.value) {
            comp1.value = select.value;
            // Set secondary comparison doc to first other available doc
            const otherDoc = state.activeDocuments.find(d => d.doc_name !== select.value);
            if (otherDoc) comp2.value = otherDoc.doc_name;
        } else if (state.activeDocuments.length > 0) {
            comp1.value = state.activeDocuments[0].doc_name;
            if (state.activeDocuments.length > 1) comp2.value = state.activeDocuments[1].doc_name;
        }
        
        runComparison();
    } else {
        compDashboard.classList.add('hidden');
        dashboard.classList.remove('hidden');
        
        // Restore dropdown selection
        if (comp1.value) select.value = comp1.value;
        loadActiveDocInsights();
    }
};

// Run document comparison Side-by-Side computation
window.runComparison = async function() {
    const doc1 = document.getElementById('comp-doc-1').value;
    const doc2 = document.getElementById('comp-doc-2').value;
    
    const compEmpty = document.getElementById('comp-empty-state');
    const compInsights = document.getElementById('comp-insights');
    
    if (!doc1 || !doc2) {
        if (compEmpty) compEmpty.classList.remove('hidden');
        if (compInsights) compInsights.classList.add('hidden');
        return;
    }
    
    if (doc1 === doc2) {
        showToast('Please select two different documents to compare.', 'warning');
        return;
    }
    
    // Show spinner/loading
    if (compEmpty) compEmpty.classList.add('hidden');
    if (compInsights) compInsights.classList.remove('hidden');
    
    try {
        // Fetch summaries for both docs
        const [res1, res2] = await Promise.all([
            fetch(`/api/documents/${encodeURIComponent(doc1)}/summary`),
            fetch(`/api/documents/${encodeURIComponent(doc2)}/summary`)
        ]);
        
        if (!res1.ok || !res2.ok) throw new Error('Failed to fetch document summary cache.');
        
        const data1 = await res1.json();
        const data2 = await res2.json();
        
        // Render summaries
        document.getElementById('comp-title-1').textContent = doc1 + ' Summary';
        document.getElementById('comp-summary-1').innerHTML = formatMarkdown(data1.summary);
        
        document.getElementById('comp-title-2').textContent = doc2 + ' Summary';
        document.getElementById('comp-summary-2').innerHTML = formatMarkdown(data2.summary);
        
        // Render comparison table matrix
        document.getElementById('comp-tbl-header-1').textContent = doc1;
        document.getElementById('comp-tbl-header-2').textContent = doc2;
        
        document.getElementById('comp-pages-1').textContent = data1.statistics.total_pages;
        document.getElementById('comp-pages-2').textContent = data2.statistics.total_pages;
        document.getElementById('comp-words-1').textContent = data1.statistics.total_words;
        document.getElementById('comp-words-2').textContent = data2.statistics.total_words;
        document.getElementById('comp-read-1').textContent = data1.statistics.readability_label + ` (${data1.statistics.readability_score})`;
        document.getElementById('comp-read-2').textContent = data2.statistics.readability_label + ` (${data2.statistics.readability_score})`;
        document.getElementById('comp-sent-1').textContent = data1.sentiment.overall + ` (${data1.sentiment.score})`;
        document.getElementById('comp-sent-2').textContent = data2.sentiment.overall + ` (${data2.sentiment.score})`;
        document.getElementById('comp-time-1').textContent = data1.statistics.reading_time_min + ' min';
        document.getElementById('comp-time-2').textContent = data2.statistics.reading_time_min + ' min';
        
        // Compare topics
        const topics1 = data1.topics.map(t => t.topic.toLowerCase().trim());
        const topics2 = data2.topics.map(t => t.topic.toLowerCase().trim());
        
        const sharedTopics = data1.topics.filter(t => 
            topics2.some(t2 => t2.includes(t.topic.toLowerCase().trim()) || t.topic.toLowerCase().trim().includes(t2))
        );
        
        const sharedContainer = document.getElementById('comp-shared-topics');
        sharedContainer.innerHTML = '';
        if (sharedTopics.length > 0) {
            sharedTopics.forEach(t => {
                sharedContainer.insertAdjacentHTML('beforeend', `<span class="tone-tag">${escapeHtml(t.topic)}</span>`);
            });
        } else {
            sharedContainer.innerHTML = '<span class="meta-tag">No direct theme overlaps detected.</span>';
        }
        
        // Unique topics
        document.getElementById('comp-unique-hdr-1').textContent = 'Unique to ' + doc1;
        document.getElementById('comp-unique-hdr-2').textContent = 'Unique to ' + doc2;
        
        const unique1List = document.getElementById('comp-unique-1');
        const unique2List = document.getElementById('comp-unique-2');
        unique1List.innerHTML = '';
        unique2List.innerHTML = '';
        
        const unique1 = data1.topics.filter(t => !topics2.some(t2 => t2.includes(t.topic.toLowerCase().trim()) || t.topic.toLowerCase().trim().includes(t2)));
        const unique2 = data2.topics.filter(t => !topics1.some(t1 => t1.includes(t.topic.toLowerCase().trim()) || t.topic.toLowerCase().trim().includes(t1)));
        
        if (unique1.length > 0) {
            unique1.forEach(t => unique1List.insertAdjacentHTML('beforeend', `<li>${escapeHtml(t.topic)}</li>`));
        } else {
            unique1List.innerHTML = '<li>None</li>';
        }
        
        if (unique2.length > 0) {
            unique2.forEach(t => unique2List.insertAdjacentHTML('beforeend', `<li>${escapeHtml(t.topic)}</li>`));
        } else {
            unique2List.innerHTML = '<li>None</li>';
        }
        
        // Keyword cross comparison chart
        renderCompKeywordChart(data1.keywords, data2.keywords, doc1, doc2);
        
    } catch (e) {
        showToast(handleFetchError(e, 'Error during document comparison'), 'error');
    }
};

// Render comparative double bar chart for keyword frequencies
function renderCompKeywordChart(kw1, kw2, label1, label2) {
    if (compKeywordChartInstance) compKeywordChartInstance.destroy();
    
    // Collate union of top keywords
    const unionWordsSet = new Set([
        ...kw1.slice(0, 8).map(k => k.word),
        ...kw2.slice(0, 8).map(k => k.word)
    ]);
    const unionWords = Array.from(unionWordsSet).slice(0, 12);
    
    const dataset1 = unionWords.map(w => {
        const item = kw1.find(k => k.word === w);
        return item ? item.count : 0;
    });
    
    const dataset2 = unionWords.map(w => {
        const item = kw2.find(k => k.word === w);
        return item ? item.count : 0;
    });
    
    const ctx = document.getElementById('compKeywordChart').getContext('2d');
    compKeywordChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: unionWords,
            datasets: [
                {
                    label: label1,
                    data: dataset1,
                    backgroundColor: 'rgba(102, 126, 234, 0.85)',
                    borderRadius: 4
                },
                {
                    label: label2,
                    data: dataset2,
                    backgroundColor: 'rgba(118, 75, 162, 0.85)',
                    borderRadius: 4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { grid: { display: false } },
                y: { beginAtZero: true, ticks: { precision: 0 } }
            }
        }
    });
}

// Print dashboard export helper
window.exportDashboardPDF = function() {
    window.print();
};

// ============================================================
// INTERACTIVE DOCUMENT EXPLORER LOGIC
// ============================================================

state.currentDocName = null;
state.totalPages = 0;
state.currentPage = 1;
state.docPagesText = {}; // cache of page text: { pageNum: text }
state.bookmarks = [];
state.highlights = [];
state.searchQuery = "";
state.searchResults = [];
state.currentSearchIndex = -1;
state.searchCaseSensitive = false;
state.searchWholeWord = false;

window.openDocumentExplorer = async function(encodedDocName) {
    const docName = decodeURIComponent(encodedDocName);
    state.currentDocName = docName;
    state.docPagesText = {};
    state.currentPage = 1;
    state.searchQuery = "";
    state.searchResults = [];
    state.currentSearchIndex = -1;
    
    // Show explorer and splitter
    const explorer = document.getElementById('document-explorer');
    const splitter = document.getElementById('workspace-splitter');
    if (explorer) explorer.classList.remove('hidden');
    if (splitter) splitter.classList.remove('hidden');
    
    // Set breadcrumb
    const breadcrumb = document.getElementById('explorer-breadcrumb');
    if (breadcrumb) {
        breadcrumb.innerHTML = `Explorer <span class="bc-sep">></span> <span class="bc-current">${escapeHtml(docName)}</span>`;
    }
    
    // Reset pages viewport
    const viewport = document.getElementById('explorer-pages-viewport');
    if (viewport) {
        viewport.innerHTML = `<div class="explorer-loading"><i class="fa-solid fa-circle-notch fa-spin"></i> Initializing Document Explorer...</div>`;
    }
    
    try {
        const res = await fetch(`/api/documents/${encodeURIComponent(docName)}/structure`);
        if (!res.ok) throw new Error("Failed to load document structure");
        const data = await res.json();
        
        state.totalPages = data.total_pages;
        
        // Render empty page cards placeholders
        if (viewport) {
            viewport.innerHTML = '';
            for (let p = 1; p <= state.totalPages; p++) {
                const card = document.createElement('div');
                card.className = 'page-card';
                card.id = `page-card-${p}`;
                card.setAttribute('data-page', p);
                card.innerHTML = `
                    <div class="page-card-header">
                        <span class="page-card-num">Page ${p}</span>
                        <button class="page-bookmark-btn" onclick="togglePageBookmark(${p})" id="bookmark-btn-${p}">
                            <i class="fa-regular fa-bookmark"></i>
                        </button>
                    </div>
                    <div class="page-card-text" id="page-text-${p}">
                        <div class="page-loading-spinner"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading page text...</div>
                    </div>
                `;
                viewport.appendChild(card);
            }
        }
        
        const totalPageSpan = document.getElementById('explorer-page-total');
        if (totalPageSpan) totalPageSpan.textContent = `/ ${state.totalPages}`;
        
        const pageInput = document.getElementById('explorer-page-input');
        if (pageInput) {
            pageInput.value = 1;
            pageInput.max = state.totalPages;
        }
        
        // Setup lazy loading with IntersectionObserver
        setupIntersectionObserver();
        
        // Load TOC
        await loadTOC();
        
        // Load Mindmap Tree tab
        renderStructureMap(data.structure);
        
        // Load annotations (bookmarks & highlights)
        await loadBookmarks();
        await loadHighlights();
        
        // Render Thumbnails
        renderThumbnails();
        
        // Background pre-fetching of page texts
        prefetchAllPages();
        
    } catch (e) {
        showToast(handleFetchError(e, "Error loading document explorer"), "error");
        if (viewport) {
            viewport.innerHTML = `<div class="no-doc-placeholder"><i class="fa-solid fa-triangle-exclamation"></i><p>Failed to load explorer workspace.</p></div>`;
        }
    }
};

async function loadPageText(p) {
    if (state.docPagesText[p] !== undefined) return state.docPagesText[p];
    
    state.docPagesText[p] = null; // loading state
    try {
        const res = await fetch(`/api/documents/${encodeURIComponent(state.currentDocName)}/page/${p}`);
        if (res.ok) {
            const data = await res.json();
            state.docPagesText[p] = data.text;
            renderPageCardContent(p);
            
            // Highlight search matches on this page if active
            if (state.searchQuery) {
                // If there's an active query, we rerun search to update searchResults
                // but only re-render if matches are found.
                // Simple search re-trigger to update search matches on newly loaded pages:
                const prevQuery = state.searchQuery;
                state.searchQuery = ""; // temporary reset to avoid recursive call
                const input = document.getElementById('explorer-search-input');
                if (input) input.value = prevQuery;
                onSearchInput();
            }
            
            updateThumbnailContent(p);
            return data.text;
        }
    } catch (e) {
        console.error(`Failed to load page ${p}`, e);
        state.docPagesText[p] = undefined;
    }
}

function renderPageCardContent(p) {
    const txtEl = document.getElementById(`page-text-${p}`);
    if (!txtEl) return;
    let text = state.docPagesText[p];
    if (text === null) {
        txtEl.innerHTML = `<div class="page-loading-spinner"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading page text...</div>`;
        return;
    }
    if (text === undefined) {
        txtEl.innerHTML = `<div class="page-error">Failed to load page content. <button class="btn btn-xs" onclick="loadPageText(${p})">Retry</button></div>`;
        return;
    }
    
    const tags = [];
    
    // Highlights
    if (state.highlights) {
        const pageHighlights = state.highlights.filter(h => h.page === p);
        pageHighlights.forEach(hl => {
            let startIdx = 0;
            while ((startIdx = text.indexOf(hl.text, startIdx)) !== -1) {
                tags.push({
                    start: startIdx,
                    end: startIdx + hl.text.length,
                    type: 'highlight',
                    color: hl.color,
                    id: hl.id
                });
                startIdx += hl.text.length;
            }
        });
    }
    
    // Search matches
    if (state.searchQuery && state.searchResults) {
        const pageMatches = state.searchResults.filter(m => m.page === p);
        pageMatches.forEach(match => {
            const isCurrent = state.searchResults[state.currentSearchIndex] === match;
            tags.push({
                start: match.index,
                end: match.index + match.length,
                type: isCurrent ? 'search-current' : 'search'
            });
        });
    }
    
    // Sort tags by start index ascending, end index descending
    tags.sort((a, b) => {
        if (a.start !== b.start) return a.start - b.start;
        return b.end - a.end;
    });
    
    // Resolve overlaps
    const cleanTags = [];
    let lastEnd = 0;
    tags.forEach(tag => {
        if (tag.start >= lastEnd) {
            cleanTags.push(tag);
            lastEnd = tag.end;
        }
    });
    
    // Build HTML string
    let html = '';
    let cursor = 0;
    cleanTags.forEach(tag => {
        html += escapeHtml(text.substring(cursor, tag.start));
        const tagText = escapeHtml(text.substring(tag.start, tag.end));
        if (tag.type === 'highlight') {
            html += `<mark class="hl-mark-${tag.color}" data-highlight-id="${tag.id}" onclick="onHighlightClick(event, '${tag.id}')">${tagText}</mark>`;
        } else if (tag.type === 'search') {
            html += `<span class="search-hl">${tagText}</span>`;
        } else if (tag.type === 'search-current') {
            html += `<span class="search-hl search-hl-current">${tagText}</span>`;
        }
        cursor = tag.end;
    });
    
    html += escapeHtml(text.substring(cursor));
    txtEl.innerHTML = html;
}

window.onHighlightClick = async function(event, hlId) {
    event.stopPropagation();
    if (confirm("Delete this highlight?")) {
        try {
            const res = await fetch(`/api/documents/${encodeURIComponent(state.currentDocName)}/highlights/${hlId}`, {
                method: 'DELETE'
            });
            if (res.ok) {
                showToast("Highlight deleted", "success");
                await loadHighlights();
                for (let p = 1; p <= state.totalPages; p++) {
                    if (state.docPagesText[p]) {
                        renderPageCardContent(p);
                    }
                }
                updateThumbnailsHeatmap();
            }
        } catch (e) {
            console.error("Failed to delete highlight", e);
        }
    }
};

async function loadHighlights() {
    try {
        const res = await fetch(`/api/documents/${encodeURIComponent(state.currentDocName)}/highlights`);
        if (res.ok) {
            state.highlights = await res.json();
            renderHighlightsList();
        }
    } catch (e) {
        console.error("Failed to load highlights", e);
    }
}

async function loadBookmarks() {
    try {
        const res = await fetch(`/api/documents/${encodeURIComponent(state.currentDocName)}/bookmarks`);
        if (res.ok) {
            state.bookmarks = await res.json();
            renderBookmarksList();
            updateBookmarkButtons();
        }
    } catch (e) {
        console.error("Failed to load bookmarks", e);
    }
}

function renderBookmarksList() {
    const list = document.getElementById('explorer-bookmarks-list');
    if (!list) return;
    if (state.bookmarks.length === 0) {
        list.innerHTML = `<div class="empty-annotation-placeholder">No bookmarks added yet.</div>`;
        return;
    }
    list.innerHTML = '';
    state.bookmarks.forEach(bm => {
        const item = document.createElement('div');
        item.className = 'bookmark-item';
        item.onclick = () => jumpToPage(bm.page);
        item.innerHTML = `
            <i class="fa-solid fa-bookmark bm-icon"></i>
            <div class="bm-info">
                <div class="bm-title">${escapeHtml(bm.title)}</div>
                <div class="bm-meta">Page ${bm.page} • ${bm.created_at || ''}</div>
            </div>
            <button class="bm-delete" onclick="deleteBookmarkClick(event, '${bm.id}')" title="Delete bookmark">
                <i class="fa-solid fa-trash-can"></i>
            </button>
        `;
        list.appendChild(item);
    });
}

window.deleteBookmarkClick = async function(event, bmId) {
    event.stopPropagation();
    if (confirm("Delete this bookmark?")) {
        try {
            const res = await fetch(`/api/documents/${encodeURIComponent(state.currentDocName)}/bookmarks/${bmId}`, {
                method: 'DELETE'
            });
            if (res.ok) {
                showToast("Bookmark deleted", "success");
                await loadBookmarks();
                updateThumbnailsHeatmap();
            }
        } catch (e) {
            console.error("Failed to delete bookmark", e);
        }
    }
};

function renderHighlightsList() {
    const list = document.getElementById('explorer-highlights-list');
    if (!list) return;
    if (state.highlights.length === 0) {
        list.innerHTML = `<div class="empty-annotation-placeholder">No highlights created yet.</div>`;
        return;
    }
    list.innerHTML = '';
    state.highlights.forEach(hl => {
        const item = document.createElement('div');
        item.className = 'highlight-item';
        item.onclick = () => jumpToPage(hl.page);
        item.innerHTML = `
            <span class="highlight-color-dot hl-dot-${hl.color}"></span>
            <div class="hl-info">
                <div class="hl-text">${escapeHtml(hl.text)}</div>
                <div class="hl-meta">Page ${hl.page} • ${hl.created_at || ''}</div>
            </div>
            <button class="hl-delete" onclick="deleteHighlightClick(event, '${hl.id}')" title="Delete highlight">
                <i class="fa-solid fa-trash-can"></i>
            </button>
        `;
        list.appendChild(item);
    });
}

window.deleteHighlightClick = async function(event, hlId) {
    event.stopPropagation();
    if (confirm("Delete this highlight?")) {
        try {
            const res = await fetch(`/api/documents/${encodeURIComponent(state.currentDocName)}/highlights/${hlId}`, {
                method: 'DELETE'
            });
            if (res.ok) {
                showToast("Highlight deleted", "success");
                await loadHighlights();
                for (let p = 1; p <= state.totalPages; p++) {
                    if (state.docPagesText[p]) {
                        renderPageCardContent(p);
                    }
                }
                updateThumbnailsHeatmap();
            }
        } catch (e) {
            console.error("Failed to delete highlight", e);
        }
    }
};

function updateBookmarkButtons() {
    for (let p = 1; p <= state.totalPages; p++) {
        const btn = document.getElementById(`bookmark-btn-${p}`);
        if (!btn) continue;
        const isBookmarked = state.bookmarks.some(b => b.page === p);
        if (isBookmarked) {
            btn.classList.add('bookmarked');
            btn.innerHTML = `<i class="fa-solid fa-bookmark"></i>`;
        } else {
            btn.classList.remove('bookmarked');
            btn.innerHTML = `<i class="fa-regular fa-bookmark"></i>`;
        }
    }
}

window.togglePageBookmark = async function(page) {
    const isBookmarked = state.bookmarks.some(b => b.page === page);
    if (isBookmarked) {
        const bm = state.bookmarks.find(b => b.page === page);
        if (bm) {
            try {
                const res = await fetch(`/api/documents/${encodeURIComponent(state.currentDocName)}/bookmarks/${bm.id}`, {
                    method: 'DELETE'
                });
                if (res.ok) {
                    showToast(`Page ${page} unbookmarked`, "success");
                    await loadBookmarks();
                    updateThumbnailsHeatmap();
                }
            } catch (e) {
                console.error(e);
            }
        }
    } else {
        try {
            const snippet = state.docPagesText[page] ? state.docPagesText[page].substring(0, 100) : `Page ${page}`;
            const res = await fetch(`/api/documents/${encodeURIComponent(state.currentDocName)}/bookmarks`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    page: page,
                    title: `Page ${page}`,
                    snippet: snippet
                })
            });
            if (res.ok) {
                showToast(`Page ${page} bookmarked`, "success");
                await loadBookmarks();
                updateThumbnailsHeatmap();
            }
        } catch (e) {
            console.error(e);
        }
    }
};

window.addCurrentPageBookmark = function() {
    if (state.currentPage) {
        togglePageBookmark(state.currentPage);
    }
};

window.highlightSelection = async function(color) {
    const selection = window.getSelection();
    const selectedText = selection.toString().trim();
    if (!selectedText) return;
    
    let pageCard = selection.anchorNode.parentElement.closest('.page-card');
    if (!pageCard) return;
    const pageNum = parseInt(pageCard.getAttribute('data-page'));
    
    try {
        const res = await fetch(`/api/documents/${encodeURIComponent(state.currentDocName)}/highlights`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                page: pageNum,
                text: selectedText,
                color: color
            })
        });
        if (res.ok) {
            showToast("Highlight added", "success");
            selection.removeAllRanges();
            document.getElementById('text-selection-toolbar').classList.add('hidden');
            
            await loadHighlights();
            renderPageCardContent(pageNum);
            updateThumbnailsHeatmap();
        }
    } catch (e) {
        console.error(e);
    }
};

window.askAboutSelection = function() {
    const selection = window.getSelection();
    const selectedText = selection.toString().trim();
    if (!selectedText) return;
    
    selection.removeAllRanges();
    document.getElementById('text-selection-toolbar').classList.add('hidden');
    
    switchTab('chat');
    useSuggestion(`Regarding the following text from "${state.currentDocName}":\n\n"${selectedText}"\n\nCan you explain...`);
};

async function loadTOC() {
    const list = document.getElementById('explorer-toc-list');
    if (!list) return;
    list.innerHTML = '';
    
    try {
        const res = await fetch(`/api/documents/${encodeURIComponent(state.currentDocName)}/toc`);
        if (res.ok) {
            const data = await res.json();
            const sections = data.sections || [];
            if (sections.length === 0) {
                list.innerHTML = `<div class="empty-annotation-placeholder">No TOC sections found.</div>`;
                return;
            }
            sections.forEach(sec => {
                const entry = document.createElement('div');
                entry.className = `toc-entry level-${sec.level || 1}`;
                entry.onclick = () => jumpToPage(sec.page);
                entry.innerHTML = `
                    <i class="fa-solid fa-hashtag icon-small"></i>
                    <span>${escapeHtml(sec.title)}</span>
                    <span class="toc-page-badge">P. ${sec.page}</span>
                `;
                list.appendChild(entry);
            });
        }
    } catch (e) {
        console.error("Failed to load TOC", e);
    }
}

function renderStructureMap(structure) {
    const container = document.getElementById('explorer-map-tree');
    if (!container) return;
    container.innerHTML = '';
    
    if (!structure || structure.length === 0) {
        container.innerHTML = `<div class="empty-annotation-placeholder">No document structure map.</div>`;
        return;
    }
    
    function createNodeElement(node) {
        const div = document.createElement('div');
        div.className = 'tree-node';
        
        const label = document.createElement('div');
        label.className = 'tree-node-label';
        
        const hasChildren = node.children && node.children.length > 0;
        const iconClass = hasChildren ? 'fa-solid fa-square-minus' : 'fa-solid fa-circle';
        
        label.innerHTML = `
            <i class="node-icon ${iconClass}"></i>
            <span>${escapeHtml(node.title)}</span>
            <span class="toc-page-badge">P. ${node.page}</span>
        `;
        
        label.onclick = (e) => {
            e.stopPropagation();
            jumpToPage(node.page);
        };
        
        div.appendChild(label);
        
        if (hasChildren) {
            const childrenContainer = document.createElement('div');
            childrenContainer.className = 'tree-node-children';
            
            node.children.forEach(child => {
                childrenContainer.appendChild(createNodeElement(child));
            });
            
            const nodeIcon = label.querySelector('.node-icon');
            nodeIcon.onclick = (e) => {
                e.stopPropagation();
                childrenContainer.classList.toggle('hidden');
                nodeIcon.className = childrenContainer.classList.contains('hidden')
                    ? 'node-icon fa-solid fa-square-plus'
                    : 'node-icon fa-solid fa-square-minus';
            };
            
            div.appendChild(childrenContainer);
        }
        
        return div;
    }
    
    structure.forEach(node => {
        container.appendChild(createNodeElement(node));
    });
}

let pageObserver = null;
function setupIntersectionObserver() {
    if (pageObserver) {
        pageObserver.disconnect();
    }
    
    const options = {
        root: document.getElementById('explorer-pages-viewport'),
        rootMargin: '100px 0px 100px 0px',
        threshold: 0.1
    };
    
    pageObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const pageNum = parseInt(entry.target.getAttribute('data-page'));
                loadPageText(pageNum);
            }
        });
    }, options);
    
    document.querySelectorAll('.page-card').forEach(card => {
        pageObserver.observe(card);
    });
    
    const viewport = document.getElementById('explorer-pages-viewport');
    if (viewport) {
        viewport.addEventListener('scroll', handleViewportScroll);
    }
}

let scrollTimeout = null;
function handleViewportScroll() {
    if (scrollTimeout) clearTimeout(scrollTimeout);
    
    scrollTimeout = setTimeout(() => {
        const cards = document.querySelectorAll('.page-card');
        const viewport = document.getElementById('explorer-pages-viewport');
        const viewportRect = viewport.getBoundingClientRect();
        
        let activePage = state.currentPage;
        let maxOverlap = 0;
        
        cards.forEach(card => {
            const rect = card.getBoundingClientRect();
            const overlap = Math.max(0, Math.min(rect.bottom, viewportRect.bottom) - Math.max(rect.top, viewportRect.top));
            if (overlap > maxOverlap) {
                maxOverlap = overlap;
                activePage = parseInt(card.getAttribute('data-page'));
            }
        });
        
        if (activePage !== state.currentPage) {
            state.currentPage = activePage;
            const input = document.getElementById('explorer-page-input');
            if (input) input.value = activePage;
            
            document.querySelectorAll('.thumbnail-card').forEach(card => {
                card.classList.toggle('active', parseInt(card.getAttribute('data-page')) === activePage);
            });
        }
        
        updateReadingProgress();
    }, 100);
}

window.jumpToPage = function(page) {
    page = parseInt(page);
    if (isNaN(page) || page < 1 || page > state.totalPages) return;
    
    state.currentPage = page;
    const pageInput = document.getElementById('explorer-page-input');
    if (pageInput) pageInput.value = page;
    
    const card = document.getElementById(`page-card-${page}`);
    if (card) {
        card.scrollIntoView({ behavior: 'smooth', block: 'start' });
        loadPageText(page);
    }
};

window.jumpToPageInput = function() {
    const input = document.getElementById('explorer-page-input');
    if (input) {
        jumpToPage(input.value);
    }
};

window.prevSection = function() {
    if (state.currentPage > 1) {
        jumpToPage(state.currentPage - 1);
    }
};

window.nextSection = function() {
    if (state.currentPage < state.totalPages) {
        jumpToPage(state.currentPage + 1);
    }
};

async function prefetchAllPages() {
    const batchSize = 5;
    for (let i = 1; i <= state.totalPages; i += batchSize) {
        const promises = [];
        for (let j = i; j < i + batchSize && j <= state.totalPages; j++) {
            if (state.docPagesText[j] === undefined) {
                promises.push(loadPageText(j));
            }
        }
        await Promise.all(promises);
    }
}

window.onSearchInput = function() {
    const input = document.getElementById('explorer-search-input');
    if (!input) return;
    const query = input.value.trim();
    state.searchQuery = query;
    
    const caseSensitive = document.getElementById('search-case-sensitive')?.checked || false;
    const wholeWord = document.getElementById('search-whole-word')?.checked || false;
    
    state.searchCaseSensitive = caseSensitive;
    state.searchWholeWord = wholeWord;
    
    if (!query) {
        state.searchResults = [];
        state.currentSearchIndex = -1;
        document.getElementById('search-match-count').textContent = '0/0';
        document.getElementById('btn-search-prev').disabled = true;
        document.getElementById('btn-search-next').disabled = true;
        
        applySearchHighlights();
        updateThumbnailsHeatmap();
        return;
    }
    
    state.searchResults = [];
    let regexFlags = caseSensitive ? 'g' : 'gi';
    let pattern = escapeRegExp(query);
    if (wholeWord) {
        pattern = `\\b${pattern}\\b`;
    }
    
    try {
        const regex = new RegExp(pattern, regexFlags);
        
        for (let p = 1; p <= state.totalPages; p++) {
            const text = state.docPagesText[p];
            if (!text) continue;
            
            let match;
            regex.lastIndex = 0;
            while ((match = regex.exec(text)) !== null) {
                state.searchResults.push({
                    page: p,
                    index: match.index,
                    length: query.length
                });
                if (match.index === regex.lastIndex) {
                    regex.lastIndex++;
                }
            }
        }
    } catch (e) {
        console.error("Regex search failed", e);
    }
    
    const countSpan = document.getElementById('search-match-count');
    if (countSpan) {
        countSpan.textContent = state.searchResults.length > 0 
            ? `1/${state.searchResults.length}` 
            : '0/0';
    }
    
    const prevBtn = document.getElementById('btn-search-prev');
    const nextBtn = document.getElementById('btn-search-next');
    if (prevBtn) prevBtn.disabled = state.searchResults.length === 0;
    if (nextBtn) nextBtn.disabled = state.searchResults.length === 0;
    
    applySearchHighlights();
    
    if (state.searchResults.length > 0) {
        state.currentSearchIndex = 0;
        navigateToCurrentSearchMatch();
    } else {
        state.currentSearchIndex = -1;
    }
    
    updateThumbnailsHeatmap();
};

function applySearchHighlights() {
    for (let p = 1; p <= state.totalPages; p++) {
        if (state.docPagesText[p] !== undefined) {
            renderPageCardContent(p);
        }
    }
}

window.navigateSearch = function(direction) {
    if (state.searchResults.length === 0) return;
    
    let newIndex = state.currentSearchIndex + direction;
    if (newIndex < 0) newIndex = state.searchResults.length - 1;
    if (newIndex >= state.searchResults.length) newIndex = 0;
    
    const oldIndex = state.currentSearchIndex;
    state.currentSearchIndex = newIndex;
    
    const countSpan = document.getElementById('search-match-count');
    if (countSpan) {
        countSpan.textContent = `${state.currentSearchIndex + 1}/${state.searchResults.length}`;
    }
    
    if (oldIndex >= 0 && oldIndex < state.searchResults.length) {
        renderPageCardContent(state.searchResults[oldIndex].page);
    }
    renderPageCardContent(state.searchResults[newIndex].page);
    
    navigateToCurrentSearchMatch();
};

function navigateToCurrentSearchMatch() {
    if (state.currentSearchIndex < 0 || state.currentSearchIndex >= state.searchResults.length) return;
    const match = state.searchResults[state.currentSearchIndex];
    
    jumpToPage(match.page);
    
    setTimeout(() => {
        const pageCard = document.getElementById(`page-card-${match.page}`);
        if (pageCard) {
            const currentHl = pageCard.querySelector('.search-hl-current');
            if (currentHl) {
                currentHl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        }
    }, 150);
}

window.toggleSearchOptions = function() {
    const dropdown = document.getElementById('search-options-dropdown');
    if (dropdown) dropdown.classList.toggle('hidden');
};

document.addEventListener('click', (e) => {
    const dropdown = document.getElementById('search-options-dropdown');
    const optionsBtn = document.getElementById('btn-search-options');
    if (dropdown && optionsBtn && !optionsBtn.contains(e.target) && !dropdown.contains(e.target)) {
        dropdown.classList.add('hidden');
    }
});

function updateReadingProgress() {
    const viewport = document.getElementById('explorer-pages-viewport');
    if (!viewport) return;
    
    const scrollTop = viewport.scrollTop;
    const scrollHeight = viewport.scrollHeight;
    const clientHeight = viewport.clientHeight;
    
    let progressPercent = 0;
    if (scrollHeight > clientHeight) {
        progressPercent = Math.round((scrollTop / (scrollHeight - clientHeight)) * 100);
    }
    
    const fill = document.getElementById('explorer-progress-fill');
    if (fill) fill.style.width = `${progressPercent}%`;
    
    const percent = document.getElementById('explorer-progress-percent');
    if (percent) percent.textContent = `${progressPercent}%`;
    
    let totalWords = 0;
    if (state.activeInsights && state.activeInsights.statistics && state.activeInsights.statistics.total_words) {
        totalWords = state.activeInsights.statistics.total_words;
    } else {
        for (let p in state.docPagesText) {
            if (state.docPagesText[p]) {
                totalWords += state.docPagesText[p].split(/\s+/).length;
            }
        }
    }
    
    const remainingWords = totalWords * (1 - (progressPercent / 100));
    const readingTime = Math.ceil(remainingWords / 200);
    
    const timeEl = document.getElementById('explorer-reading-time');
    if (timeEl) {
        timeEl.textContent = `Remaining: ${readingTime} min`;
    }
}

function renderThumbnails() {
    const list = document.getElementById('explorer-thumbnails-list');
    if (!list) return;
    list.innerHTML = '';
    
    for (let p = 1; p <= state.totalPages; p++) {
        const card = document.createElement('div');
        card.className = `thumbnail-card ${p === state.currentPage ? 'active' : ''}`;
        card.id = `thumbnail-card-${p}`;
        card.setAttribute('data-page', p);
        card.onclick = () => jumpToPage(p);
        
        card.innerHTML = `
            <span class="thumbnail-page-num">${p}</span>
            <div class="thumbnail-preview">
                <div class="thumbnail-text-snippet" id="thumb-text-${p}">Loading...</div>
            </div>
            <span class="thumbnail-heatmap-dot heat-none" id="thumb-heat-${p}" title="0 items"></span>
        `;
        list.appendChild(card);
        updateThumbnailContent(p);
    }
}

function updateThumbnailContent(p) {
    const snippetEl = document.getElementById(`thumb-text-${p}`);
    if (!snippetEl) return;
    
    const text = state.docPagesText[p];
    if (text) {
        snippetEl.textContent = text.substring(0, 100) + '...';
    } else {
        snippetEl.textContent = 'Loading content...';
    }
    updatePageHeatmapDot(p);
}

function updatePageHeatmapDot(p) {
    const dot = document.getElementById(`thumb-heat-${p}`);
    if (!dot) return;
    
    let count = 0;
    if (state.bookmarks) {
        count += state.bookmarks.filter(b => b.page === p).length;
    }
    if (state.highlights) {
        count += state.highlights.filter(h => h.page === p).length;
    }
    if (state.searchResults) {
        count += state.searchResults.filter(m => m.page === p).length;
    }
    
    dot.setAttribute('title', `${count} items on this page`);
    
    dot.className = 'thumbnail-heatmap-dot';
    if (count === 0) {
        dot.classList.add('heat-none');
    } else if (count <= 2) {
        dot.classList.add('heat-low');
    } else if (count <= 5) {
        dot.classList.add('heat-mid');
    } else {
        dot.classList.add('heat-high');
    }
}

function updateThumbnailsHeatmap() {
    for (let p = 1; p <= state.totalPages; p++) {
        updatePageHeatmapDot(p);
    }
}

window.switchExplorerTab = function(tabId) {
    const tabs = ['ex-toc', 'ex-map', 'ex-annotations', 'ex-thumbnails'];
    
    tabs.forEach(t => {
        const content = document.getElementById(t);
        if (content) content.classList.toggle('hidden', t !== tabId);
        
        const id = t.replace('ex-', 'btn-ex-');
        const btn = document.getElementById(id);
        if (btn) btn.classList.toggle('active', t === tabId);
    });
};

window.toggleExplorerSidebar = function() {
    const sidebar = document.getElementById('explorer-sidebar');
    if (sidebar) {
        sidebar.classList.toggle('collapsed');
    }
};

window.closeExplorer = function() {
    const explorer = document.getElementById('document-explorer');
    const splitter = document.getElementById('workspace-splitter');
    if (explorer) explorer.classList.add('hidden');
    if (splitter) splitter.classList.add('hidden');
    
    if (explorer) explorer.style.width = '';
    
    state.currentDocName = null;
};

window.exportAnnotations = function() {
    if (!state.currentDocName) return;
    
    let md = `# Annotations for ${state.currentDocName}\n\n`;
    
    md += `## Bookmarks\n\n`;
    if (state.bookmarks && state.bookmarks.length > 0) {
        state.bookmarks.forEach(bm => {
            md += `- **Page ${bm.page}**: ${bm.title}\n`;
            if (bm.snippet) {
                md += `  > ${bm.snippet}\n`;
            }
            md += `  *(Created at ${bm.created_at || 'unknown'})*\n\n`;
        });
    } else {
        md += `*No bookmarks added.*\n\n`;
    }
    
    md += `## Highlights\n\n`;
    if (state.highlights && state.highlights.length > 0) {
        state.highlights.forEach(hl => {
            md += `- **Page ${hl.page}** (${hl.color}):\n`;
            md += `  > ${hl.text}\n\n`;
        });
    } else {
        md += `*No highlights created.*\n\n`;
    }
    
    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${state.currentDocName.replace(/\.[^/.]+$/, "")}_annotations.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
};

function escapeRegExp(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

<<<<<<< HEAD
// ============================================================
// VOICE INPUT — VoiceInputController
// Uses the browser Web Speech API (no dependencies, no backend).
// Supported: Chrome, Edge. Gracefully hidden in Firefox/Safari.
// ============================================================
class VoiceInputController {
    constructor() {
        this.recognition   = null;
        this.isRecording   = false;
        this.finalText     = '';
        this.interimText   = '';

        // DOM refs (set in init after DOMContentLoaded)
        this.voiceBtn      = null;
        this.voiceBtnIcon  = null;
        this.voiceWaveform = null;
        this.statusBadge   = null;
        this.statusText    = null;
        this.cancelBtn     = null;
        this.chatInput     = null;
        this.sendBtn       = null;

        this._init();
    }

    _init() {
        // Guard: only initialise once DOM is ready
        const setup = () => {
            this.voiceBtn      = document.getElementById('voice-btn');
            this.voiceBtnIcon  = document.getElementById('voice-btn-icon');
            this.voiceWaveform = document.getElementById('voice-waveform');
            this.statusBadge   = document.getElementById('voice-status-badge');
            this.statusText    = document.getElementById('voice-status-text');
            this.cancelBtn     = document.getElementById('voice-cancel-btn');
            this.chatInput     = document.getElementById('chat-input');
            this.sendBtn       = document.getElementById('send-btn');

            // Check browser support
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRecognition) {
                if (this.voiceBtn) this.voiceBtn.classList.add('unsupported');
                console.info('[VoiceInput] Web Speech API not supported in this browser.');
                return;
            }

            // Build recognition engine
            this.recognition = new SpeechRecognition();
            this.recognition.continuous      = true;
            this.recognition.interimResults  = true;
            this.recognition.lang            = 'en-US';
            this.recognition.maxAlternatives = 1;

            // Events
            this.recognition.onstart   = () => this._onStart();
            this.recognition.onend     = () => this._onEnd();
            this.recognition.onerror   = (e) => this._onError(e);
            this.recognition.onresult  = (e) => this._onResult(e);

            // Mic button click
            if (this.voiceBtn) {
                this.voiceBtn.addEventListener('click', () => this.toggle());
            }
            // Cancel button in badge
            if (this.cancelBtn) {
                this.cancelBtn.addEventListener('click', () => this.cancel());
            }
        };

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', setup);
        } else {
            setup();
        }
    }

    /** Toggle start / stop */
    toggle() {
        if (this.isRecording) {
            this.stop();
        } else {
            this.start();
        }
    }

    start() {
        if (!this.recognition) return;
        this.finalText   = '';
        this.interimText = '';
        try {
            this.recognition.start();
        } catch (err) {
            // Already started — ignore
        }
    }

    stop() {
        if (!this.recognition) return;
        this.recognition.stop();
    }

    cancel() {
        if (!this.recognition) return;
        this.finalText   = '';
        this.interimText = '';
        this.recognition.abort();
        this._setIdle();
        // Restore placeholder
        if (this.chatInput) {
            this.chatInput.value = '';
            this.chatInput.style.height = 'auto';
            const charCount = document.getElementById('char-count');
            if (charCount) charCount.textContent = 0;
            if (this.sendBtn) this.sendBtn.disabled = true;
        }
    }

    // ---- Private lifecycle callbacks ----

    _onStart() {
        this.isRecording = true;
        this._setRecording();
    }

    _onEnd() {
        // Triggered when recognition stops (either by stop() or silence timeout)
        const transcript = this.finalText.trim();
        if (transcript) {
            this._setProcessing();
            this._fillAndSubmit(transcript);
        } else {
            this._setIdle();
        }
    }

    _onError(event) {
        const msg = event.error;
        if (msg === 'aborted' || msg === 'no-speech') {
            // Normal — user cancelled or no audio
        } else {
            console.warn('[VoiceInput] Speech recognition error:', msg);
            const toastMsg = {
                'not-allowed'  : 'Microphone access denied. Please allow mic permissions in browser settings.',
                'network'      : 'Network error during voice recognition.',
                'audio-capture': 'No microphone found.',
            }[msg] || `Voice recognition error: ${msg}`;
            if (typeof showToast === 'function') showToast(toastMsg, 'error');
        }
        this._setIdle();
        if (this.chatInput) this.chatInput.value = '';
    }

    _onResult(event) {
        let interim = '';
        let final   = '';

        for (let i = event.resultIndex; i < event.results.length; i++) {
            const alt = event.results[i][0].transcript;
            if (event.results[i].isFinal) {
                final += alt + ' ';
            } else {
                interim += alt;
            }
        }

        this.finalText   += final;
        this.interimText  = interim;

        // Show live transcript in textarea
        if (this.chatInput) {
            const displayed = (this.finalText + this.interimText).trim();
            this.chatInput.value = displayed;
            this.chatInput.style.height = 'auto';
            this.chatInput.style.height = this.chatInput.scrollHeight + 'px';
            const charCount = document.getElementById('char-count');
            if (charCount) charCount.textContent = displayed.length;
            if (this.sendBtn) this.sendBtn.disabled = displayed === '';
        }

        // Update status badge with live word count hint
        if (this.statusText) {
            const wordCount = (this.finalText + this.interimText).trim().split(/\s+/).filter(Boolean).length;
            this.statusText.textContent = wordCount > 0 ? `Listening… (${wordCount} word${wordCount > 1 ? 's' : ''})` : 'Listening…';
        }
    }

    // ---- UI state helpers ----

    _setRecording() {
        if (this.voiceBtn)      { this.voiceBtn.classList.add('recording'); this.voiceBtn.classList.remove('processing'); }
        if (this.voiceBtnIcon)  { this.voiceBtnIcon.className = 'fa-solid fa-microphone-lines'; }
        if (this.voiceWaveform) { this.voiceWaveform.classList.add('active'); }
        if (this.statusBadge)   { this.statusBadge.classList.remove('hidden'); }
        if (this.statusText)    { this.statusText.textContent = 'Listening…'; }
        if (this.chatInput)     { this.chatInput.placeholder = 'Speak now — I\'m listening…'; }
    }

    _setProcessing() {
        if (this.voiceBtn)      { this.voiceBtn.classList.remove('recording'); this.voiceBtn.classList.add('processing'); }
        if (this.voiceBtnIcon)  { this.voiceBtnIcon.className = 'fa-solid fa-circle-notch fa-spin'; }
        if (this.voiceWaveform) { this.voiceWaveform.classList.remove('active'); }
        if (this.statusBadge)   { this.statusBadge.classList.remove('hidden'); }
        if (this.statusText)    { this.statusText.textContent = 'Sending to AI…'; }
    }

    _setIdle() {
        this.isRecording = false;
        if (this.voiceBtn)      { this.voiceBtn.classList.remove('recording', 'processing'); }
        if (this.voiceBtnIcon)  { this.voiceBtnIcon.className = 'fa-solid fa-microphone'; }
        if (this.voiceWaveform) { this.voiceWaveform.classList.remove('active'); }
        if (this.statusBadge)   { this.statusBadge.classList.add('hidden'); }
        if (this.chatInput)     { this.chatInput.placeholder = 'Ask a question about your documents... (Shift + Enter for new line)'; }
    }

    _fillAndSubmit(transcript) {
        if (!this.chatInput) { this._setIdle(); return; }

        // Place the final transcript and trigger submit
        this.chatInput.value = transcript;
        this.chatInput.style.height = 'auto';
        this.chatInput.style.height = this.chatInput.scrollHeight + 'px';
        if (this.sendBtn) this.sendBtn.disabled = false;

        // Auto-submit after tiny delay so the textarea renders first
        setTimeout(() => {
            const chatForm = document.getElementById('chat-form');
            if (chatForm) chatForm.requestSubmit();
            this._setIdle();
        }, 120);
    }
}

// Instantiate once — hooks into DOMContentLoaded internally
const voiceInput = new VoiceInputController();
=======

>>>>>>> 0b277982b6513d3180ebb54eb7ade1cc6ba0fc9e

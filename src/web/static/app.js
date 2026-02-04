// TTS Warehouse Frontend

const API_BASE = '';

// --- Utility Functions ---

async function api(endpoint, options = {}) {
    const url = `${API_BASE}${endpoint}`;
    const response = await fetch(url, {
        headers: {
            'Content-Type': 'application/json',
            ...options.headers,
        },
        ...options,
    });
    
    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Request failed' }));
        throw new Error(error.detail || 'Request failed');
    }
    
    return response.json();
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.remove();
    }, 4000);
}

function showView(viewId) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    
    document.getElementById(`${viewId}-view`).classList.add('active');
    document.querySelector(`[data-view="${viewId}"]`)?.classList.add('active');
}

function formatDate(isoString) {
    if (!isoString) return 'Unknown date';
    return new Date(isoString).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
    });
}

// --- Dashboard ---

async function loadSources() {
    const container = document.getElementById('sources-list');
    
    try {
        const sources = await api('/api/sources');
        
        if (sources.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <h3>No feeds yet</h3>
                    <p>Add an article, RSS feed, or Royal Road book to get started.</p>
                </div>
            `;
            return;
        }
        
        container.innerHTML = sources.map(source => `
            <div class="source-card">
                <div class="source-header">
                    <span class="source-title" onclick="viewSourceDetail(${source.id})">${source.name}</span>
                    <span class="source-type ${source.type}">${source.type.replace('_', ' ')}</span>
                </div>
                <div class="source-meta">
                    <span>📦 ${source.item_count} items</span>
                    <span class="processing-mode ${source.processing_mode}">${source.processing_mode}</span>
                    <span>🔄 ${source.last_refreshed_at ? formatDate(source.last_refreshed_at) : 'Never'}</span>
                </div>
                <div class="source-actions">
                    <input type="text" class="feed-url" value="${source.feed_url}" readonly>
                    <button class="btn btn-small btn-secondary" onclick="copyFeedUrl('${source.feed_url}')">Copy</button>
                    ${source.type !== 'article' ? `<button class="btn btn-small btn-primary" onclick="refreshSource(${source.id}, this)">🔄 Refresh</button>` : ''}
                    <button class="btn btn-small btn-danger" onclick="deleteSource(${source.id})">Delete</button>
                </div>
            </div>
        `).join('');
    } catch (error) {
        container.innerHTML = `<p class="loading">Error loading sources: ${error.message}</p>`;
    }
}

async function loadQueueStatus() {
    try {
        const status = await api('/api/jobs');
        const container = document.getElementById('queue-status');
        
        container.innerHTML = `
            ${status.processing > 0 ? `<span class="queue-stat processing">⚡ ${status.processing} processing</span>` : ''}
            ${status.pending > 0 ? `<span class="queue-stat pending">⏳ ${status.pending} pending</span>` : ''}
        `;
    } catch (error) {
        console.error('Failed to load queue status:', error);
    }
}

function copyFeedUrl(url) {
    navigator.clipboard.writeText(url).then(() => {
        showToast('Feed URL copied to clipboard!', 'success');
    });
}

async function deleteSource(sourceId) {
    if (!confirm('Are you sure you want to delete this source and all its items?')) {
        return;
    }
    
    try {
        await api(`/api/sources/${sourceId}`, { method: 'DELETE' });
        showToast('Source deleted', 'success');
        loadSources();
    } catch (error) {
        showToast(`Error: ${error.message}`, 'error');
    }
}

async function refreshSource(sourceId, button) {
    const originalText = button.textContent;
    button.textContent = '⏳';
    button.disabled = true;
    
    try {
        const result = await api(`/api/sources/${sourceId}/refresh`, { method: 'POST' });
        showToast(result.message, result.new_items > 0 ? 'success' : 'info');
        loadSources();
        loadQueueStatus();
    } catch (error) {
        showToast(`Error: ${error.message}`, 'error');
    } finally {
        button.textContent = originalText;
        button.disabled = false;
    }
}

async function viewSourceDetail(sourceId) {
    showView('source-detail');
    const container = document.getElementById('source-detail');
    container.innerHTML = '<p class="loading">Loading...</p>';
    
    try {
        const source = await api(`/api/sources/${sourceId}`);
        const items = await api(`/api/items?source_id=${sourceId}`);
        
        container.innerHTML = `
            <h2>${source.name}</h2>
            <div class="source-meta">
                <span class="source-type ${source.type}">${source.type.replace('_', ' ')}</span>
                <span>📦 ${source.item_count} items</span>
                <span class="processing-mode ${source.processing_mode}">${source.processing_mode}</span>
                <span>🔄 Last refreshed: ${source.last_refreshed_at ? formatDate(source.last_refreshed_at) : 'Never'}</span>
            </div>
            <div class="source-actions" style="margin-top: 16px;">
                <input type="text" class="feed-url" value="${source.feed_url}" readonly style="max-width: 400px;">
                <button class="btn btn-small btn-secondary" onclick="copyFeedUrl('${source.feed_url}')">Copy Feed URL</button>
                ${source.type !== 'article' ? `<button class="btn btn-small btn-primary" onclick="refreshSource(${source.id}, this)">🔄 Check for New Items</button>` : ''}
            </div>
            
            <div class="items-list">
                <h3>Items</h3>
                ${items.length === 0 ? '<p class="empty-state">No items yet</p>' : items.map(item => `
                    <div class="item-card">
                        <div class="item-info">
                            <h4>${item.title}</h4>
                            <span style="color: var(--text-muted); font-size: 0.85rem;">${formatDate(item.published_at)}</span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span class="item-status ${item.status}">${item.status}</span>
                            ${item.audio_url ? `<button class="btn btn-small btn-secondary" onclick="playAudio('${item.audio_url}', '${item.title.replace(/'/g, "\\'")}')">▶ Play</button>` : ''}
                            ${item.status === 'pending' ? `<button class="btn btn-small btn-primary" onclick="processItem(${item.id})">Process</button>` : ''}
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    } catch (error) {
        container.innerHTML = `<p class="loading">Error: ${error.message}</p>`;
    }
}

async function processItem(itemId) {
    try {
        await api(`/api/items/${itemId}/process`, { method: 'POST' });
        showToast('Item queued for processing', 'success');
        loadQueueStatus();
    } catch (error) {
        showToast(`Error: ${error.message}`, 'error');
    }
}

function playAudio(url, title) {
    const player = document.getElementById('audio-player');
    const audio = document.getElementById('audio-element');
    const titleEl = document.getElementById('audio-player-title');

    player.classList.remove('hidden');
    titleEl.textContent = title;
    audio.src = url;
    audio.play();
}

// --- Add Article ---

async function previewArticle() {
    const url = document.getElementById('article-url').value;
    if (!url) {
        showToast('Please enter a URL', 'error');
        return;
    }
    
    const preview = document.getElementById('article-preview');
    preview.innerHTML = '<p class="loading">Loading preview...</p>';
    preview.classList.remove('hidden');
    
    try {
        const data = await api('/api/preview/article', {
            method: 'POST',
            body: JSON.stringify({ url }),
        });
        
        preview.innerHTML = `
            <h3>${data.title}</h3>
            <div class="preview-meta">
                ${data.author ? `<span>✍️ ${data.author}</span>` : ''}
                <span>📝 ${data.content_length} characters</span>
            </div>
            <div class="preview-content">${data.content_preview}</div>
        `;
    } catch (error) {
        preview.innerHTML = `<p class="loading">Error: ${error.message}</p>`;
    }
}

async function addArticle(e) {
    e.preventDefault();
    
    const url = document.getElementById('article-url').value;
    const name = document.getElementById('article-name').value;
    
    try {
        const result = await api('/api/sources/article', {
            method: 'POST',
            body: JSON.stringify({ url, name: name || undefined }),
        });
        
        showToast(result.message, 'success');
        document.getElementById('article-form').reset();
        document.getElementById('article-preview').classList.add('hidden');
        showView('dashboard');
        loadSources();
        loadQueueStatus();
    } catch (error) {
        showToast(`Error: ${error.message}`, 'error');
    }
}

// --- Add RSS Feed ---

async function previewFeed() {
    const url = document.getElementById('feed-url').value;
    if (!url) {
        showToast('Please enter a feed URL', 'error');
        return;
    }
    
    const preview = document.getElementById('feed-preview');
    preview.innerHTML = '<p class="loading">Loading preview...</p>';
    preview.classList.remove('hidden');
    
    try {
        const data = await api('/api/preview/feed', {
            method: 'POST',
            body: JSON.stringify({ url }),
        });
        
        preview.innerHTML = `
            <h3>${data.title}</h3>
            <div class="preview-meta">
                <span>📦 ${data.item_count} items</span>
                <span class="processing-mode ${data.processing_mode}">${data.processing_mode} processing</span>
            </div>
            ${data.description ? `<p style="margin-bottom: 16px;">${data.description}</p>` : ''}
            <div class="preview-items">
                ${data.items.map(item => `
                    <div class="preview-item">
                        <strong>${item.title}</strong>
                        <span style="color: var(--text-muted); font-size: 0.85rem; margin-left: 8px;">${formatDate(item.published_at)}</span>
                    </div>
                `).join('')}
                ${data.item_count > 20 ? `<p style="color: var(--text-muted); padding: 8px 0;">... and ${data.item_count - 20} more items</p>` : ''}
            </div>
        `;
    } catch (error) {
        preview.innerHTML = `<p class="loading">Error: ${error.message}</p>`;
    }
}

async function addFeed(e) {
    e.preventDefault();
    
    const url = document.getElementById('feed-url').value;
    const name = document.getElementById('feed-name').value;
    
    try {
        const result = await api('/api/sources/feed', {
            method: 'POST',
            body: JSON.stringify({ url, name: name || undefined }),
        });
        
        showToast(result.message, 'success');
        document.getElementById('feed-form').reset();
        document.getElementById('feed-preview').classList.add('hidden');
        showView('dashboard');
        loadSources();
        loadQueueStatus();
    } catch (error) {
        showToast(`Error: ${error.message}`, 'error');
    }
}

// --- Add Royal Road ---

async function previewRoyalRoad() {
    const url = document.getElementById('royalroad-url').value;
    if (!url) {
        showToast('Please enter a book URL', 'error');
        return;
    }
    
    const preview = document.getElementById('royalroad-preview');
    preview.innerHTML = '<p class="loading">Loading preview...</p>';
    preview.classList.remove('hidden');
    
    try {
        const data = await api('/api/preview/royalroad', {
            method: 'POST',
            body: JSON.stringify({ url }),
        });
        
        preview.innerHTML = `
            <h3>${data.title}</h3>
            <div class="preview-meta">
                ${data.author ? `<span>✍️ ${data.author}</span>` : ''}
                <span>📚 ${data.chapter_count} chapters</span>
                <span class="processing-mode ${data.processing_mode}">${data.processing_mode} processing</span>
            </div>
            ${data.description ? `<p style="margin-bottom: 16px;">${data.description.substring(0, 300)}...</p>` : ''}
            <div class="preview-items">
                ${data.chapters.map(ch => `
                    <div class="preview-item">
                        <strong>${ch.chapter_number}. ${ch.title}</strong>
                    </div>
                `).join('')}
                ${data.chapter_count > 20 ? `<p style="color: var(--text-muted); padding: 8px 0;">... and ${data.chapter_count - 20} more chapters</p>` : ''}
            </div>
        `;
    } catch (error) {
        preview.innerHTML = `<p class="loading">Error: ${error.message}</p>`;
    }
}

async function addRoyalRoad(e) {
    e.preventDefault();
    
    const url = document.getElementById('royalroad-url').value;
    const name = document.getElementById('royalroad-name').value;
    const maxChapters = document.getElementById('royalroad-max').value;
    
    try {
        const result = await api('/api/sources/royalroad', {
            method: 'POST',
            body: JSON.stringify({
                url,
                name: name || undefined,
                max_chapters: maxChapters ? parseInt(maxChapters) : undefined,
            }),
        });
        
        showToast(result.message, 'success');
        document.getElementById('royalroad-form').reset();
        document.getElementById('royalroad-preview').classList.add('hidden');
        showView('dashboard');
        loadSources();
        loadQueueStatus();
    } catch (error) {
        showToast(`Error: ${error.message}`, 'error');
    }
}

// --- Event Listeners ---

document.addEventListener('DOMContentLoaded', () => {
    // Navigation
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            showView(btn.dataset.view);
        });
    });
    
    // Back button
    document.getElementById('back-to-dashboard').addEventListener('click', () => {
        showView('dashboard');
        loadSources();
    });
    
    // Forms
    document.getElementById('article-form').addEventListener('submit', addArticle);
    document.getElementById('feed-form').addEventListener('submit', addFeed);
    document.getElementById('royalroad-form').addEventListener('submit', addRoyalRoad);
    
    // Preview buttons
    document.getElementById('preview-article-btn').addEventListener('click', previewArticle);
    document.getElementById('preview-feed-btn').addEventListener('click', previewFeed);
    document.getElementById('preview-royalroad-btn').addEventListener('click', previewRoyalRoad);
    
    // Initial load
    loadSources();
    loadQueueStatus();
    
    // Refresh queue status periodically
    setInterval(loadQueueStatus, 5000);
});

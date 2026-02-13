// Soundboard functionality
let folders = [];
let currentlyPlaying = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    loadFolders();
});

async function loadFolders() {
    try {
        const response = await fetch('/soundboard/api/folders');
        const data = await response.json();
        folders = data.folders;
        renderFolders();
    } catch (error) {
        console.error('Error loading folders:', error);
        showError('Failed to load sound folders');
    }
}

function renderFolders() {
    const container = document.getElementById('folders-container');
    
    if (folders.length === 0) {
        container.innerHTML = '<div class="loading">No sound folders found</div>';
        return;
    }
    
    container.innerHTML = folders.map(folder => `
        <div class="folder-card">
            <div class="folder-header">
                <i class="fas fa-folder-open"></i>
                <h2>${escapeHtml(folder.name)}</h2>
            </div>
            <div class="sounds-list">
                ${folder.files.map(file => `
                    <div class="sound-item" data-filepath="${escapeHtml(file.path)}" onclick="playSound('${escapeHtml(file.path)}', '${escapeHtml(file.name)}', this)">
                        <div class="sound-info">
                            <div class="sound-icon">
                                <i class="fas fa-music"></i>
                            </div>
                            <span class="sound-name">${escapeHtml(file.name)}</span>
                        </div>
                        <button class="play-btn" onclick="event.stopPropagation(); playSound('${escapeHtml(file.path)}', '${escapeHtml(file.name)}', this.parentElement)">
                            <i class="fas fa-play"></i>
                        </button>
                    </div>
                `).join('')}
            </div>
        </div>
    `).join('');
}

async function playSound(filepath, name, element) {
    // If already playing this sound, ignore
    if (currentlyPlaying === filepath) return;
    
    // Update UI to show playing state
    setPlayingState(filepath, name, element);
    
    try {
        const response = await fetch('/soundboard/api/play', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filepath: filepath })
        });
        
        const result = await response.json();
        
        if (result.status === 'playing') {
            // Sound is playing - the server will handle it
            // We'll clear the playing state after a reasonable timeout
            // since we don't have real-time feedback when it finishes
            setTimeout(() => {
                clearPlayingState();
            }, 10000); // Clear after 10 seconds as fallback
        } else {
            clearPlayingState();
            showError(result.error || 'Failed to play sound');
        }
    } catch (error) {
        clearPlayingState();
        console.error('Error playing sound:', error);
        showError('Failed to play sound');
    }
}

function setPlayingState(filepath, name, element) {
    // Clear previous playing state
    clearPlayingState();
    
    // Set new playing state
    currentlyPlaying = filepath;
    element.classList.add('playing');
    
    // Update icon to show it's playing
    const icon = element.querySelector('.play-btn i');
    if (icon) {
        icon.classList.remove('fa-play');
        icon.classList.add('fa-volume-up');
    }
    
    // Show now playing indicator
    const nowPlaying = document.getElementById('now-playing');
    const playingText = document.getElementById('playing-text');
    if (nowPlaying && playingText) {
        playingText.textContent = `Playing: ${name}`;
        nowPlaying.classList.remove('hidden');
    }
}

function clearPlayingState() {
    currentlyPlaying = null;
    
    // Remove playing class from all items
    document.querySelectorAll('.sound-item.playing').forEach(item => {
        item.classList.remove('playing');
        const icon = item.querySelector('.play-btn i');
        if (icon) {
            icon.classList.remove('fa-volume-up');
            icon.classList.add('fa-play');
        }
    });
    
    // Hide now playing indicator
    const nowPlaying = document.getElementById('now-playing');
    if (nowPlaying) {
        nowPlaying.classList.add('hidden');
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showError(message) {
    // Create a simple toast notification
    const toast = document.createElement('div');
    toast.style.cssText = `
        position: fixed;
        bottom: 30px;
        left: 50%;
        transform: translateX(-50%);
        background: #e74c3c;
        padding: 16px 32px;
        border-radius: 12px;
        color: white;
        font-weight: 500;
        z-index: 9999;
        animation: fadeInUp 0.3s ease;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
    `;
    toast.textContent = message;
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'fadeOutDown 0.3s ease forwards';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Add fadeOutDown animation if not already defined
if (!document.getElementById('soundboard-animations')) {
    const style = document.createElement('style');
    style.id = 'soundboard-animations';
    style.textContent = `
        @keyframes fadeOutDown {
            from {
                opacity: 1;
                transform: translateX(-50%) translateY(0);
            }
            to {
                opacity: 0;
                transform: translateX(-50%) translateY(20px);
            }
        }
    `;
    document.head.appendChild(style);
}

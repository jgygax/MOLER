// Soundboard functionality
let folders = [];
let currentlyPlaying = null;
let localAudioPlayer = null;
let isLocalPlayback = false;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    loadFolders();
    loadPlaybackMode();
});

// Load saved playback mode preference
function loadPlaybackMode() {
    const saved = localStorage.getItem('soundboard-playback-mode');
    if (saved === 'local') {
        isLocalPlayback = true;
        document.getElementById('playback-mode-toggle').checked = true;
        document.getElementById('playback-mode-label').textContent = 'Local';
    }
}

// Toggle between local and RasPi playback
function togglePlaybackMode() {
    const toggle = document.getElementById('playback-mode-toggle');
    const label = document.getElementById('playback-mode-label');
    
    isLocalPlayback = toggle.checked;
    label.textContent = isLocalPlayback ? 'Local' : 'RasPi';
    
    // Save preference
    localStorage.setItem('soundboard-playback-mode', isLocalPlayback ? 'local' : 'raspi');
    
    // Stop any current playback when switching modes
    stopPlayback();
}

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
    
    if (isLocalPlayback) {
        // Play locally in browser
        playLocalSound(filepath, name);
    } else {
        // Play on RasPi
        await playRasPiSound(filepath, name);
    }
}

function playLocalSound(filepath, name) {
    // Convert filepath to URL for browser playback
    // filepath is like "r2d2/sound.mp3" or "songs/music.mp3"
    const audioUrl = `/soundboard/api/audio/${filepath}`;
    
    // Stop any existing local playback
    if (localAudioPlayer) {
        localAudioPlayer.pause();
        localAudioPlayer.currentTime = 0;
    }
    
    // Create new audio player
    localAudioPlayer = new Audio(audioUrl);
    
    localAudioPlayer.onended = () => {
        clearPlayingState();
    };
    
    localAudioPlayer.onerror = (e) => {
        console.error('Error playing audio:', e);
        clearPlayingState();
        showError('Failed to play sound locally');
    };
    
    localAudioPlayer.play().catch(err => {
        console.error('Error starting playback:', err);
        clearPlayingState();
        showError('Failed to play sound');
    });
}

async function playRasPiSound(filepath, name) {
    try {
        const response = await fetch('/soundboard/api/play', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filepath: filepath })
        });
        
        const result = await response.json();
        
        if (result.status === 'playing') {
            // Sound is playing on RasPi - clear state after estimated duration
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
    
    // Stop local playback if active
    if (localAudioPlayer) {
        localAudioPlayer.pause();
        localAudioPlayer.currentTime = 0;
        localAudioPlayer = null;
    }
    
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

async function stopPlayback() {
    if (isLocalPlayback && localAudioPlayer) {
        // Stop local playback
        clearPlayingState();
        return;
    }
    
    // Stop RasPi playback
    try {
        const response = await fetch('/soundboard/api/stop', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const result = await response.json();
        
        if (result.status === 'stopped') {
            clearPlayingState();
        }
    } catch (error) {
        console.error('Error stopping playback:', error);
        showError('Failed to stop playback');
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

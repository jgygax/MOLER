// Settings management
let currentSettings = {};
let ledSettings = {};

// Presets configuration - easy to add more
const PRESETS = {
    brush: {
        name: "Brush",
        x_offset_amount: 2,
        y_offset_amount: 2,
        start_w: 0.3,
        width_variation: 1
    },
    marker: {
        name: "Marker",
        x_offset_amount: 1,
        y_offset_amount: 0,
        start_w: 0.5,
        width_variation: 0
    }
};

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    loadLedSettings();
});

async function loadSettings() {
    try {
        const response = await fetch('/settings/api');
        currentSettings = await response.json();
        updateUIFromSettings();
        showStatus('Settings loaded');
    } catch (error) {
        showStatus('Error loading settings: ' + error.message, true);
    }
}

async function loadLedSettings() {
    try {
        const response = await fetch('/settings/led');
        ledSettings = await response.json();
        updateLedUIFromSettings();
    } catch (error) {
        console.error('Error loading LED settings:', error);
    }
}

function updateUIFromSettings() {
    // Speed settings
    document.getElementById('speed-up').value = currentSettings.speed_up;
    document.getElementById('speed-down').value = currentSettings.speed_down;
    
    // Width settings
    document.getElementById('start-w').value = currentSettings.start_w;
    document.getElementById('width-variation').value = currentSettings.width_variation;
    
    // Offset settings
    document.getElementById('x-offset-amount').value = currentSettings.x_offset_amount;
    document.getElementById('y-offset-amount').value = currentSettings.y_offset_amount;
}

function updateLedUIFromSettings() {
    // LED settings
    const innenlichtToggle = document.getElementById('innenlicht-toggle');
    const brightnessSlider = document.getElementById('led-brightness');
    const brightnessValue = document.getElementById('brightness-value');
    
    if (innenlichtToggle) {
        innenlichtToggle.checked = ledSettings.innenlicht_enabled;
    }
    if (brightnessSlider) {
        brightnessSlider.value = Math.round(ledSettings.brightness * 100);
        brightnessValue.textContent = Math.round(ledSettings.brightness * 100) + '%';
    }
    
    // Add event listeners for LED controls
    if (innenlichtToggle) {
        innenlichtToggle.addEventListener('change', async () => {
            await saveLedSettings();
        });
    }
    
    if (brightnessSlider) {
        brightnessSlider.addEventListener('input', (e) => {
            brightnessValue.textContent = e.target.value + '%';
        });
        brightnessSlider.addEventListener('change', async () => {
            await saveLedSettings();
        });
    }
}

async function saveLedSettings() {
    const settings = {
        innenlicht_enabled: document.getElementById('innenlicht-toggle').checked,
        brightness: parseInt(document.getElementById('led-brightness').value) / 100
    };
    
    try {
        const response = await fetch('/settings/led', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        
        const result = await response.json();
        if (result.status === 'ok') {
            ledSettings = result.settings;
            showStatus('LED settings saved');
        } else {
            showStatus('Error: ' + result.error, true);
        }
    } catch (error) {
        showStatus('Error saving LED settings: ' + error.message, true);
    }
}

function applyPreset(presetKey) {
    const preset = PRESETS[presetKey];
    if (!preset) return;
    
    // Apply preset values
    document.getElementById('x-offset-amount').value = preset.x_offset_amount;
    document.getElementById('y-offset-amount').value = preset.y_offset_amount;
    document.getElementById('start-w').value = preset.start_w;
    document.getElementById('width-variation').value = preset.width_variation;
    
    showStatus(`Applied ${preset.name} preset`);
}

async function saveSettings() {
    const settings = {
        speed_up: parseFloat(document.getElementById('speed-up').value),
        speed_down: parseFloat(document.getElementById('speed-down').value),
        start_w: parseFloat(document.getElementById('start-w').value),
        width_variation: parseFloat(document.getElementById('width-variation').value),
        x_offset_amount: parseFloat(document.getElementById('x-offset-amount').value),
        y_offset_amount: parseFloat(document.getElementById('y-offset-amount').value)
    };
    
    try {
        const response = await fetch('/settings/api', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        
        const result = await response.json();
        if (result.status === 'ok') {
            currentSettings = result.settings;
            showStatus('Settings saved and applied' + (result.applied ? '' : ' (plotter not available)'));
        } else {
            showStatus('Error: ' + result.error, true);
        }
    } catch (error) {
        showStatus('Error saving settings: ' + error.message, true);
    }
}

async function resetSettings() {
    if (!confirm('Reset all settings to defaults?')) return;
    
    try {
        const response = await fetch('/settings/reset', { method: 'POST' });
        const result = await response.json();
        
        if (result.status === 'ok') {
            currentSettings = result.settings;
            updateUIFromSettings();
            showStatus('Settings reset to defaults' + (result.applied ? '' : ' (plotter not available)'));
        }
    } catch (error) {
        showStatus('Error resetting settings: ' + error.message, true);
    }
}

function showStatus(message, isError = false) {
    // Remove existing toast
    const existingToast = document.querySelector('.status-toast');
    if (existingToast) {
        existingToast.remove();
    }
    
    // Create new toast
    const toast = document.createElement('div');
    toast.className = 'status-toast';
    toast.textContent = message;
    toast.style.background = isError ? '#e74c3c' : '#27ae60';
    document.body.appendChild(toast);
    
    // Animate out and remove
    setTimeout(() => {
        toast.style.animation = 'fadeOutDown 0.3s ease forwards';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

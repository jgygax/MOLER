// Settings management
let currentSettings = {};

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
    
    // Color settings
    document.getElementById('color-idle').value = rgbToHex(
        currentSettings.color_idle.r,
        currentSettings.color_idle.g,
        currentSettings.color_idle.b
    );
    document.getElementById('color-paint-max').value = rgbToHex(
        currentSettings.color_paint_max.r,
        currentSettings.color_paint_max.g,
        currentSettings.color_paint_max.b
    );
    document.getElementById('color-go-start').value = rgbToHex(
        currentSettings.color_go_start.r,
        currentSettings.color_go_start.g,
        currentSettings.color_go_start.b
    );
    document.getElementById('color-go-home').value = rgbToHex(
        currentSettings.color_go_home.r,
        currentSettings.color_go_home.g,
        currentSettings.color_go_home.b
    );
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
        y_offset_amount: parseFloat(document.getElementById('y-offset-amount').value),
        color_idle: hexToRgb(document.getElementById('color-idle').value),
        color_paint_max: hexToRgb(document.getElementById('color-paint-max').value),
        color_go_start: hexToRgb(document.getElementById('color-go-start').value),
        color_go_home: hexToRgb(document.getElementById('color-go-home').value)
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

// Helper functions
function rgbToHex(r, g, b) {
    return '#' + [r, g, b].map(x => {
        const hex = Math.round(x).toString(16);
        return hex.length === 1 ? '0' + hex : hex;
    }).join('');
}

function hexToRgb(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return result ? {
        r: parseInt(result[1], 16),
        g: parseInt(result[2], 16),
        b: parseInt(result[3], 16)
    } : { r: 0, g: 0, b: 0 };
}

"""
Settings persistence module - handles loading and saving settings to disk.
Ensures settings survive application restarts.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Settings file location (in the application root directory)
SETTINGS_FILE = Path(__file__).parent / "settings.json"

# Default settings for VPlotter
DEFAULT_VPLOTTER_SETTINGS = {
    "speed_up": 0.07,
    "speed_down": 0.07,
    "start_w": 0.4,
    "width_variation": 0.6,
    "x_offset_amount": 1,
    "y_offset_amount": 0,
}

# Default settings for LEDs
DEFAULT_LED_SETTINGS = {
    "innenlicht_enabled": True,
    "brightness": 1.0,  # 0.0 to 1.0
}


def load_settings():
    """
    Load settings from the JSON file.
    Returns a dict with 'vplotter' and 'led' keys containing the settings.
    Falls back to defaults if file doesn't exist or is corrupted.
    """
    if not SETTINGS_FILE.exists():
        logger.info(f"Settings file not found at {SETTINGS_FILE}, using defaults")
        return {
            "vplotter": DEFAULT_VPLOTTER_SETTINGS.copy(),
            "led": DEFAULT_LED_SETTINGS.copy(),
        }
    
    try:
        with open(SETTINGS_FILE, 'r') as f:
            data = json.load(f)
        
        # Merge with defaults to ensure all keys exist (handles missing/new settings)
        vplotter = {**DEFAULT_VPLOTTER_SETTINGS, **data.get("vplotter", {})}
        led = {**DEFAULT_LED_SETTINGS, **data.get("led", {})}
        
        logger.info(f"Loaded settings from {SETTINGS_FILE}")
        return {"vplotter": vplotter, "led": led}
        
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to load settings file ({e}), using defaults")
        return {
            "vplotter": DEFAULT_VPLOTTER_SETTINGS.copy(),
            "led": DEFAULT_LED_SETTINGS.copy(),
        }


def save_settings(vplotter_settings=None, led_settings=None):
    """
    Save settings to the JSON file.
    Uses atomic write (write to temp file, then rename) to prevent corruption.
    
    Args:
        vplotter_settings: Dict with VPlotter settings (optional)
        led_settings: Dict with LED settings (optional)
    """
    try:
        # Load existing settings to merge with updates
        current = load_settings()
        
        if vplotter_settings is not None:
            current["vplotter"].update(vplotter_settings)
        
        if led_settings is not None:
            current["led"].update(led_settings)
        
        # Write to temporary file first (atomic write pattern)
        temp_file = SETTINGS_FILE.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(current, f, indent=2)
        
        # Atomic rename
        temp_file.replace(SETTINGS_FILE)
        
        logger.debug("Settings saved successfully")
        return True
        
    except IOError as e:
        logger.error(f"Failed to save settings: {e}")
        return False

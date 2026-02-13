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

# Default settings for Audio
DEFAULT_AUDIO_SETTINGS = {
    "enabled": True,
    "volume": 50,  # 0 to 100
    "idle_frequency": 30,  # Expected seconds between sounds when idle
    "plotting_frequency": 10,  # Expected seconds between sounds when plotting
}


def load_settings():
    """
    Load settings from the JSON file.
    Returns a dict with 'vplotter', 'led', and 'audio' keys containing the settings.
    Falls back to defaults if file doesn't exist or is corrupted.
    """
    if not SETTINGS_FILE.exists():
        logger.info(f"Settings file not found at {SETTINGS_FILE}, using defaults")
        return {
            "vplotter": DEFAULT_VPLOTTER_SETTINGS.copy(),
            "led": DEFAULT_LED_SETTINGS.copy(),
            "audio": DEFAULT_AUDIO_SETTINGS.copy(),
        }

    try:
        with open(SETTINGS_FILE, 'r') as f:
            data = json.load(f)

        # Merge with defaults to ensure all keys exist (handles missing/new settings)
        vplotter = {**DEFAULT_VPLOTTER_SETTINGS, **data.get("vplotter", {})}
        led = {**DEFAULT_LED_SETTINGS, **data.get("led", {})}
        audio = {**DEFAULT_AUDIO_SETTINGS, **data.get("audio", {})}

        logger.info(f"Loaded settings from {SETTINGS_FILE}")
        return {"vplotter": vplotter, "led": led, "audio": audio}

    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to load settings file ({e}), using defaults")
        return {
            "vplotter": DEFAULT_VPLOTTER_SETTINGS.copy(),
            "led": DEFAULT_LED_SETTINGS.copy(),
            "audio": DEFAULT_AUDIO_SETTINGS.copy(),
        }


def save_settings(vplotter_settings=None, led_settings=None, audio_settings=None):
    """
    Save settings to the JSON file.
    Uses atomic write (write to temp file, then rename) to prevent corruption.

    Args:
        vplotter_settings: Dict with VPlotter settings (optional)
        led_settings: Dict with LED settings (optional)
        audio_settings: Dict with audio settings (optional)
    """
    try:
        # Load existing settings to merge with updates
        current = load_settings()

        if vplotter_settings is not None:
            current["vplotter"].update(vplotter_settings)

        if led_settings is not None:
            current["led"].update(led_settings)

        if audio_settings is not None:
            current["audio"].update(audio_settings)

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


def get_audio_settings():
    """Get current audio settings from disk."""
    return load_settings()["audio"]


def _get_pactl_cmd():
    """
    Get the pactl command path.
    The environment variables from _get_pulse_env() will handle the user context.
    """
    import shutil
    
    pactl_path = shutil.which("pactl")
    if not pactl_path:
        return None
    
    return [pactl_path]


def _get_pulse_env():
    """
    Get environment variables for PulseAudio connection.
    When running as sudo, we need the original user's PulseAudio socket.
    """
    import os
    
    env = os.environ.copy()
    sudo_user = os.environ.get('SUDO_USER')
    sudo_uid = os.environ.get('SUDO_UID')
    
    if sudo_user and sudo_uid:
        # Running as sudo, set up original user's PulseAudio environment
        user_runtime_dir = f"/run/user/{sudo_uid}"
        
        if os.path.exists(user_runtime_dir):
            env['XDG_RUNTIME_DIR'] = user_runtime_dir
            pulse_socket = f"{user_runtime_dir}/pulse/native"
            if os.path.exists(pulse_socket):
                env['PULSE_SERVER'] = f"unix:{pulse_socket}"
            logger.debug(f"Using PulseAudio for user: {sudo_user} (UID: {sudo_uid})")
    
    return env


def set_audio_volume(volume_percent):
    """
    Set system audio volume using pactl on the bluetooth speaker.

    Args:
        volume_percent: Volume level 0-100
    """
    import subprocess
    import os

    # Get pactl command with proper user context
    pactl_cmd = _get_pactl_cmd()
    if not pactl_cmd:
        logger.warning("pactl not found, cannot set volume")
        return False

    try:
        # Clamp volume to 0-100
        volume = max(0, min(100, int(volume_percent)))

        # Use the exact bluetooth sink
        sink_name = "bluez_output.8F_DE_53_8F_0A_02.1"
        
        # Get proper environment for PulseAudio
        env = _get_pulse_env()
        
        # Debug info
        current_user = os.environ.get('USER') or os.environ.get('LOGNAME') or str(os.getuid())
        sudo_user = os.environ.get('SUDO_USER', 'none')
        logger.info(f"[DEBUG] Current user env: {current_user}, SUDO_USER: {sudo_user}")
        logger.info(f"[DEBUG] XDG_RUNTIME_DIR: {env.get('XDG_RUNTIME_DIR', 'not set')}")
        logger.info(f"[DEBUG] PULSE_SERVER: {env.get('PULSE_SERVER', 'not set')}")
        logger.info(f"[DEBUG] Running command: {' '.join(pactl_cmd)} set-sink-volume {sink_name} {volume}%")

        result = subprocess.run(
            pactl_cmd + ["set-sink-volume", sink_name, f"{volume}%"],
            capture_output=True,
            text=True,
            timeout=5,
            env=env
        )
        
        if result.returncode != 0:
            logger.error(f"[DEBUG] Failed to set volume. Return code: {result.returncode}")
            logger.error(f"[DEBUG] Stderr: {result.stderr}")
            logger.error(f"[DEBUG] Stdout: {result.stdout}")
            return False
        
        if result.stderr:
            logger.warning(f"[DEBUG] pactl stderr: {result.stderr}")

        logger.info(f"Audio volume set to {volume}% on {sink_name}")
        return True

    except Exception as e:
        logger.error(f"Failed to set audio volume: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def get_current_audio_volume():
    """
    Get current system audio volume using pactl from the bluetooth speaker.
    Returns volume as percentage 0-100, or None if unavailable.
    """
    import subprocess
    import re
    import os
    
    # Get pactl command with proper user context
    pactl_cmd = _get_pactl_cmd()
    if not pactl_cmd:
        logger.warning("pactl not found, cannot get volume")
        return None
    
    try:
        # Use the exact bluetooth sink
        sink_name = "bluez_output.8F_DE_53_8F_0A_02.1"
        
        # Get proper environment for PulseAudio
        env = _get_pulse_env()
        
        # Debug info
        current_user = os.environ.get('USER') or os.environ.get('LOGNAME') or str(os.getuid())
        sudo_user = os.environ.get('SUDO_USER', 'none')
        logger.debug(f"[DEBUG] Current user env: {current_user}, SUDO_USER: {sudo_user}")
        logger.debug(f"[DEBUG] XDG_RUNTIME_DIR: {env.get('XDG_RUNTIME_DIR', 'not set')}")
        logger.debug(f"[DEBUG] PULSE_SERVER: {env.get('PULSE_SERVER', 'not set')}")
        logger.debug(f"[DEBUG] Running command: {' '.join(pactl_cmd)} get-sink-volume {sink_name}")
        
        result = subprocess.run(
            pactl_cmd + ["get-sink-volume", sink_name],
            capture_output=True,
            text=True,
            timeout=5,
            env=env
        )
        
        if result.returncode != 0:
            logger.error(f"[DEBUG] Failed to get volume. Return code: {result.returncode}")
            logger.error(f"[DEBUG] Stderr: {result.stderr}")
            return None
        
        # Parse volume from output like: "Volume: front-left: 26214 /  40% / -23.88 dB"
        for line in result.stdout.split('\n'):
            if 'Volume:' in line and '%' in line:
                match = re.search(r'(\d+)%', line)
                if match:
                    volume = int(match.group(1))
                    logger.debug(f"[DEBUG] Got volume: {volume}%")
                    return volume
        
        logger.warning(f"[DEBUG] Could not parse volume from output: {result.stdout}")
        return None
        
    except Exception as e:
        logger.error(f"Failed to get audio volume: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

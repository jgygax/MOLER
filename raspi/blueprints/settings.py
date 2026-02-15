import logging
from flask import Blueprint, render_template, request, jsonify
import extensions

logger = logging.getLogger(__name__)
settings_bp = Blueprint("settings", __name__)

# Settings file location (in the application root directory)
SETTINGS_FILE = "settings.json"

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
    "dalek_intensity": 50,  # 0 to 100 - Dalek voice effect intensity
}


def _get_pulse_env():
    """Get environment variables for PulseAudio/PipeWire connection."""
    import os
    env = os.environ.copy()
    env['XDG_RUNTIME_DIR'] = '/run/user/1000'  # Hardcoded for user pi
    return env


def load_settings():
    """Load settings from JSON file. Returns dict with 'vplotter', 'led', 'audio' keys."""
    import json
    from pathlib import Path
    
    settings_path = Path(SETTINGS_FILE)
    
    if not settings_path.exists():
        logger.info(f"Settings file not found, using defaults")
        return {
            "vplotter": DEFAULT_VPLOTTER_SETTINGS.copy(),
            "led": DEFAULT_LED_SETTINGS.copy(),
            "audio": DEFAULT_AUDIO_SETTINGS.copy(),
        }

    try:
        with open(settings_path, "r") as f:
            data = json.load(f)

        # Merge with defaults to ensure all keys exist
        return {
            "vplotter": {**DEFAULT_VPLOTTER_SETTINGS, **data.get("vplotter", {})},
            "led": {**DEFAULT_LED_SETTINGS, **data.get("led", {})},
            "audio": {**DEFAULT_AUDIO_SETTINGS, **data.get("audio", {})},
        }
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to load settings ({e}), using defaults")
        return {
            "vplotter": DEFAULT_VPLOTTER_SETTINGS.copy(),
            "led": DEFAULT_LED_SETTINGS.copy(),
            "audio": DEFAULT_AUDIO_SETTINGS.copy(),
        }


def save_settings(vplotter_settings=None, led_settings=None, audio_settings=None):
    """Save settings to JSON file using atomic write."""
    import json
    from pathlib import Path
    
    try:
        current = load_settings()

        if vplotter_settings is not None:
            current["vplotter"].update(vplotter_settings)
        if led_settings is not None:
            current["led"].update(led_settings)
        if audio_settings is not None:
            current["audio"].update(audio_settings)

        settings_path = Path(SETTINGS_FILE)
        temp_file = settings_path.with_suffix(".tmp")
        
        with open(temp_file, "w") as f:
            json.dump(current, f, indent=2)

        temp_file.replace(settings_path)
        logger.debug("Settings saved")
        return True
    except IOError as e:
        logger.error(f"Failed to save settings: {e}")
        return False


def get_audio_settings():
    """Get current audio settings from disk."""
    return load_settings()["audio"]


def _demote_to_user():
    """Demote process to run as user pi (uid 1000)."""
    import os
    try:
        os.setgid(1000)
        os.setuid(1000)
    except Exception:
        pass


def set_audio_volume(volume_percent):
    """Set system audio volume using pactl on the bluetooth speaker."""
    import subprocess
    import shutil
    import os
    
    pactl_path = shutil.which("pactl")
    if not pactl_path:
        logger.warning("pactl not found, cannot set volume")
        return False

    try:
        volume = max(0, min(100, int(volume_percent)))
        sink_name = "bluez_output.8F_DE_53_8F_0A_02.1"
        env = _get_pulse_env()

        result = subprocess.run(
            [pactl_path, "set-sink-volume", sink_name, f"{volume}%"],
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
            preexec_fn=_demote_to_user if os.getuid() == 0 else None,
        )

        if result.returncode == 0:
            logger.info(f"Audio volume set to {volume}%")
            return True
        else:
            logger.error(f"Failed to set volume: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Failed to set audio volume: {e}")
        return False


def get_current_audio_volume():
    """Get current system audio volume from the bluetooth speaker. Returns 0-100 or None."""
    import subprocess
    import re
    import shutil
    import os
    
    pactl_path = shutil.which("pactl")
    if not pactl_path:
        logger.warning("pactl not found, cannot get volume")
        return None

    try:
        sink_name = "bluez_output.8F_DE_53_8F_0A_02.1"
        env = _get_pulse_env()

        result = subprocess.run(
            [pactl_path, "get-sink-volume", sink_name],
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
            preexec_fn=_demote_to_user if os.getuid() == 0 else None,
        )

        if result.returncode != 0:
            logger.error(f"Failed to get volume: {result.stderr}")
            return None

        # Parse volume from output like: "Volume: front-left: 26214 /  40% / -23.88 dB"
        for line in result.stdout.split("\n"):
            if "Volume:" in line and "%" in line:
                match = re.search(r"(\d+)%", line)
                if match:
                    return int(match.group(1))

        return None
    except Exception as e:
        logger.error(f"Failed to get audio volume: {e}")
        return None


def get_settings():
    """Get current settings. Settings are loaded from disk on startup."""
    return extensions.vplotter_settings


def apply_settings_to_plotter():
    """Apply current settings to the VPlotter instance."""
    if not extensions.plotter_instance:
        logger.warning("Cannot apply settings: no plotter instance available")
        return False
    
    settings = get_settings()
    plotter = extensions.plotter_instance
    
    # Apply speeds
    plotter.SPEED_UP = settings["speed_up"]
    plotter.SPEED_DOWN = settings["speed_down"]
    plotter.left_motor.speed_up = settings["speed_up"]
    plotter.left_motor.speed_down = settings["speed_down"]
    plotter.right_motor.speed_up = settings["speed_up"]
    plotter.right_motor.speed_down = settings["speed_down"]
    
    # Apply width settings
    plotter.START_W = settings["start_w"]
    plotter.WIDTH_VARIATION = settings["width_variation"]
    
    # Apply offset settings
    plotter.X_OFFSET_AMOUNT = settings["x_offset_amount"]
    plotter.Y_OFFSET_AMOUNT = settings["y_offset_amount"]
    
    logger.info("Settings applied to VPlotter")
    return True


@settings_bp.route("/settings")
def index():
    """Render the settings page."""
    settings = get_settings()
    return render_template("settings.html", settings=settings)


@settings_bp.route("/settings/api", methods=["GET", "POST"])
def settings_api():
    """API endpoint to get or update settings."""
    if request.method == "GET":
        return jsonify(get_settings())
    
    elif request.method == "POST":
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        current_settings = get_settings()
        
        # Update speed settings
        if "speed_up" in data:
            current_settings["speed_up"] = float(data["speed_up"])
        if "speed_down" in data:
            current_settings["speed_down"] = float(data["speed_down"])
        
        # Update width settings
        if "start_w" in data:
            current_settings["start_w"] = float(data["start_w"])
        if "width_variation" in data:
            current_settings["width_variation"] = float(data["width_variation"])
        
        # Update offset settings
        if "x_offset_amount" in data:
            current_settings["x_offset_amount"] = float(data["x_offset_amount"])
        if "y_offset_amount" in data:
            current_settings["y_offset_amount"] = float(data["y_offset_amount"])
        
        # Apply settings to plotter
        applied = apply_settings_to_plotter()
        
        # Persist settings to disk
        save_settings(vplotter_settings=current_settings)
        
        return jsonify({
            "status": "ok",
            "settings": current_settings,
            "applied": applied
        })


@settings_bp.route("/settings/reset", methods=["POST"])
def reset_settings():
    """Reset settings to defaults."""
    extensions.vplotter_settings = DEFAULT_VPLOTTER_SETTINGS.copy()
    applied = apply_settings_to_plotter()
    
    # Persist reset settings to disk
    save_settings(vplotter_settings=extensions.vplotter_settings)
    
    return jsonify({
        "status": "ok",
        "settings": extensions.vplotter_settings,
        "applied": applied
    })


@settings_bp.route("/settings/led", methods=["GET", "POST"])
def led_settings_api():
    """API endpoint to get or update LED settings."""
    if request.method == "GET":
        return jsonify(extensions.led_settings)

    elif request.method == "POST":
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400

        # Update innenlicht toggle
        if "innenlicht_enabled" in data:
            extensions.led_settings["innenlicht_enabled"] = bool(data["innenlicht_enabled"])

        # Update brightness (0.0 to 1.0)
        if "brightness" in data:
            brightness = float(data["brightness"])
            extensions.led_settings["brightness"] = max(0.0, min(1.0, brightness))

        logger.info(f"LED settings updated: {extensions.led_settings}")

        # Persist LED settings to disk
        save_settings(led_settings=extensions.led_settings)

        return jsonify({
            "status": "ok",
            "settings": extensions.led_settings
        })


@settings_bp.route("/settings/audio", methods=["GET", "POST"])
def audio_settings_api():
    """API endpoint to get or update audio settings."""
    if request.method == "GET":
        # Get current system volume if available
        current_volume = get_current_audio_volume()
        response_settings = extensions.audio_settings.copy()
        if current_volume is not None:
            response_settings["volume"] = current_volume
        return jsonify(response_settings)

    elif request.method == "POST":
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400

        # Update enabled toggle
        if "enabled" in data:
            extensions.audio_settings["enabled"] = bool(data["enabled"])

        # Update volume (0 to 100)
        if "volume" in data:
            volume = int(data["volume"])
            extensions.audio_settings["volume"] = max(0, min(100, volume))
            # Apply volume to system
            set_audio_volume(volume)

        # Update idle frequency (seconds, min 5, max 300)
        if "idle_frequency" in data:
            freq = int(data["idle_frequency"])
            extensions.audio_settings["idle_frequency"] = max(5, min(300, freq))

        # Update plotting frequency (seconds, min 1, max 120)
        if "plotting_frequency" in data:
            freq = int(data["plotting_frequency"])
            extensions.audio_settings["plotting_frequency"] = max(1, min(120, freq))

        # Update Dalek voice effect intensity (0 to 100)
        if "dalek_intensity" in data:
            intensity = int(data["dalek_intensity"])
            extensions.audio_settings["dalek_intensity"] = max(0, min(100, intensity))

        logger.info(f"Audio settings updated: {extensions.audio_settings}")

        # Persist audio settings to disk
        save_settings(audio_settings=extensions.audio_settings)

        return jsonify({
            "status": "ok",
            "settings": extensions.audio_settings
        })

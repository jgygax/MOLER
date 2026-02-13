import logging
from flask import Blueprint, render_template, request, jsonify
import extensions
from settings_storage import save_settings, get_current_audio_volume, set_audio_volume

logger = logging.getLogger(__name__)
settings_bp = Blueprint("settings", __name__)

# Default settings
DEFAULT_SETTINGS = {
    "speed_up": 0.07,
    "speed_down": 0.07,
    "start_w": 0.4,
    "width_variation": 0.6,
    "x_offset_amount": 1,
    "y_offset_amount": 0,
}


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
    from settings_storage import DEFAULT_VPLOTTER_SETTINGS
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

        logger.info(f"Audio settings updated: {extensions.audio_settings}")

        # Persist audio settings to disk
        save_settings(audio_settings=extensions.audio_settings)

        return jsonify({
            "status": "ok",
            "settings": extensions.audio_settings
        })

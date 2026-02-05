import logging
from flask import Blueprint, render_template, request, jsonify
import extensions

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
    "color_idle": {"r": 0, "g": 0, "b": 64},
    "color_paint_max": {"r": 255, "g": 255, "b": 255},
    "color_go_start": {"r": 0, "g": 255, "b": 0},
    "color_go_home": {"r": 255, "g": 0, "b": 0},
}


def get_settings():
    """Get current settings, initializing if needed."""
    if not hasattr(extensions, 'vplotter_settings') or extensions.vplotter_settings is None:
        extensions.vplotter_settings = DEFAULT_SETTINGS.copy()
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
    
    # Apply colors
    plotter.COLOR_IDLE = tuple(settings["color_idle"].values())
    plotter.COLOR_PAINT_MAX = tuple(settings["color_paint_max"].values())
    plotter.COLOR_GO_START = tuple(settings["color_go_start"].values())
    plotter.COLOR_GO_HOME = tuple(settings["color_go_home"].values())
    
    # Update LED to reflect new idle color
    plotter.set_led_idle()
    
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
        
        # Update color settings
        if "color_idle" in data:
            current_settings["color_idle"] = data["color_idle"]
        if "color_paint_max" in data:
            current_settings["color_paint_max"] = data["color_paint_max"]
        if "color_go_start" in data:
            current_settings["color_go_start"] = data["color_go_start"]
        if "color_go_home" in data:
            current_settings["color_go_home"] = data["color_go_home"]
        
        # Apply settings to plotter
        applied = apply_settings_to_plotter()
        
        return jsonify({
            "status": "ok",
            "settings": current_settings,
            "applied": applied
        })


@settings_bp.route("/settings/reset", methods=["POST"])
def reset_settings():
    """Reset settings to defaults."""
    extensions.vplotter_settings = DEFAULT_SETTINGS.copy()
    applied = apply_settings_to_plotter()
    return jsonify({
        "status": "ok",
        "settings": extensions.vplotter_settings,
        "applied": applied
    })

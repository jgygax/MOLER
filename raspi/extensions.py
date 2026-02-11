import threading
from settings_storage import load_settings, DEFAULT_VPLOTTER_SETTINGS, DEFAULT_LED_SETTINGS

# Shared Locks and Lists
job_lock = threading.Lock()
job_list = []

# Global State
plotter_instance = None
led_controller = None
current_job_id = None
current_job_name = None
current_job_stop_event = None
is_processing_job = False

# Configuration
CANVAS_BOUNDS = {"top": 10, "left": 30, "right": 10, "bottom": 30}

# Load persisted settings on module import
_persisted_settings = load_settings()

# VPlotter Settings Storage (loaded from disk or defaults)
vplotter_settings = _persisted_settings["vplotter"]

# LED Settings Storage (loaded from disk or defaults)
led_settings = _persisted_settings["led"]

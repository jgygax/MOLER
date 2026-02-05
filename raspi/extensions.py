import threading

# Shared Locks and Lists
job_lock = threading.Lock()
job_list = []

# Global State
plotter_instance = None
current_job_id = None
current_job_name = None
current_job_stop_event = None
is_processing_job = False

# Configuration
CANVAS_BOUNDS = {"top": 10, "left": 30, "right": 10, "bottom": 30}

# VPlotter Settings Storage
vplotter_settings = None

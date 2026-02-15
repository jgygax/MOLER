import logging
import os
from flask import Flask, render_template
from flask_socketio import SocketIO
from dotenv import load_dotenv
from plot.vplotter import VPlotter
from plot.led_controller import MultiLEDController
import extensions
from blueprints.plotter import (
    plotter_bp,
    start_background_threads as start_plotter_threads,
)
from blueprints.processor import (
    processor_bp,
    start_background_threads as start_processor_threads,
)
from blueprints.settings import (
    settings_bp,
    apply_settings_to_plotter,
)
from blueprints.huid import (
    huid_bp,
    start_background_threads as start_huid_threads,
)
from blueprints.audio import (
    audio_bp,
    start_background_threads as start_audio_threads,
)
from blueprints.soundboard import soundboard_bp, init_sfx_player
from utils.static_manager import ensure_static_files

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Silence verbose PIL logs
logging.getLogger("PIL").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Ensure static dependencies are available (downloads on first run)
ensure_static_files()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "secret!")
app.config["UPLOAD_FOLDER"] = os.path.join(os.getcwd(), "uploads")
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# Always use gevent for WebSocket support (both in Docker and direct execution)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="gevent")

app.register_blueprint(plotter_bp)
app.register_blueprint(processor_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(huid_bp)
app.register_blueprint(audio_bp)
app.register_blueprint(soundboard_bp)

@app.route("/")
def home():
    return render_template("home.html")


# Initialize Plotter and Threads when not in debug/reloader mode (or handle idempotency)
if not extensions.plotter_instance:
    try:
        extensions.plotter_instance = VPlotter()
        extensions.plotter_instance.__enter__()
        extensions.is_processing_job = False # Ensure state
        # Apply default settings to the plotter
        apply_settings_to_plotter()
        
        # Initialize MultiLEDController
        extensions.led_controller = MultiLEDController()
        extensions.led_controller.start()
        logger.info("MultiLEDController initialized and started")

        # Initialize SFX Player
        init_sfx_player()
        logger.info("SFX Player initialized and started")
    except Exception as e:
        logger.error(f"Could not initialize VPlotter: {e}")
        extensions.plotter_instance = None
        extensions.led_controller = None

# Ensure threads are started
start_plotter_threads(socketio)
start_processor_threads(socketio)
start_huid_threads(socketio)
start_audio_threads(socketio)


if __name__ == "__main__":
    logger.info("Starting Plotter Web Server with gevent (WebSocket enabled)...")
    # Use socketio.run() which properly handles WebSocket with gevent
    socketio.run(app, host="0.0.0.0", port=5001, debug=False, use_reloader=False)

import logging
import os
from flask import Flask, render_template
from flask_socketio import SocketIO
from dotenv import load_dotenv
from plot.vplotter import VPlotter
import extensions
from blueprints.plotter import (
    plotter_bp,
    start_background_threads as start_plotter_threads,
)
from blueprints.processor import (
    processor_bp,
    start_background_threads as start_processor_threads,
)

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Silence verbose PIL logs
logging.getLogger("PIL").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "secret!")
app.config["UPLOAD_FOLDER"] = os.path.join(os.getcwd(), "uploads")
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

app.register_blueprint(plotter_bp)
app.register_blueprint(processor_bp)

@app.route("/")
def home():
    return render_template("home.html")


# Initialize Plotter and Threads when not in debug/reloader mode (or handle idempotency)
if not extensions.plotter_instance:
    try:
        extensions.plotter_instance = VPlotter()
        extensions.plotter_instance.__enter__()
        extensions.is_processing_job = False # Ensure state
    except Exception as e:
        logger.error(f"Could not initialize VPlotter: {e}")
        extensions.plotter_instance = None

# Ensure threads are started
start_plotter_threads(socketio)
start_processor_threads(socketio)


if __name__ == "__main__":
    logger.info("Starting Plotter Web Server...")
    socketio.run(app, host="0.0.0.0", port=5001)


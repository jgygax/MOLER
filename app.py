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
app.config["UPLOAD_FOLDER"] = "uploads"

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

app.register_blueprint(plotter_bp)
app.register_blueprint(processor_bp)


@app.route("/")
def home():
    return render_template("home.html")


if __name__ == "__main__":
    try:
        extensions.plotter_instance = VPlotter()
        extensions.plotter_instance.__enter__()
    except Exception as e:
        logger.error(f"Could not initialize VPlotter: {e}")
        extensions.plotter_instance = None

    start_plotter_threads(socketio)
    start_processor_threads(socketio)

    logger.info("Starting Web Server...")
    try:
        socketio.run(app, debug=True, host="0.0.0.0", port=5000, use_reloader=False)
    finally:
        if extensions.plotter_instance:
            extensions.plotter_instance.__exit__(None, None, None)

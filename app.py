import logging
from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit
import yaml
import os
from plot.plot import plot_from_file
from plot import calibrate
from plot.vplotter import VPlotter
import threading
import cv2
import base64
import time

from dotenv import load_dotenv

load_dotenv()

# Logging Configuration
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "secret!")
app.config["CANVAS_BOUNDS"] = {"top": 10, "left": 30, "right": 10, "bottom": 30}
app.plotter = None

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
thread = None
thread_lock = threading.Lock()


def background_status_thread():
    while True:
        if app.plotter:
            plotter_x, plotter_y = app.plotter.get_current_coords()
            state = {
                "active": True,
                "x": plotter_x,
                "y": plotter_y,
                "z": app.plotter.z,
                "motor_distance": app.plotter.MOTOR_DISTANCE,
                "bounds": app.config["CANVAS_BOUNDS"],
            }

            if hasattr(app.plotter, "canvas") and app.plotter.canvas is not None:
                try:
                    _, buffer = cv2.imencode(".jpg", app.plotter.canvas)
                    state["canvas"] = base64.b64encode(buffer).decode("utf-8")
                except Exception as e:
                    logger.error(f"Error encoding canvas: {e}")

            socketio.emit("status_update", state)

        socketio.sleep(0.1)


@socketio.on("connect")
def handle_connect():
    global thread
    logger.info("Client connected")
    with thread_lock:
        if thread is None:
            thread = socketio.start_background_task(background_status_thread)
    emit("config", app.config["CANVAS_BOUNDS"])


@socketio.on("disconnect")
def handle_disconnect():
    logger.info("Client disconnected")


@socketio.on("move_manual")
def handle_move_manual(data):
    direction = data.get("direction")
    speed = int(data.get("speed", 100))
    logger.debug(f"Manual move: {direction} speed: {speed}")

    if direction in ["left_up", "left_down"]:
        act_speed = speed if direction == "left_up" else -speed
        calibrate.steps_left(act_speed, app.plotter)
    elif direction in ["right_up", "right_down"]:
        act_speed = speed if direction == "right_up" else -speed
        calibrate.steps_right(act_speed, app.plotter)
    elif direction == "servo":
        calibrate.calibrate_servo(speed / 10, app.plotter)


@socketio.on("move_joystick")
def handle_joystick(data):
    if app.plotter is None:
        return
    delta_x = data.get("x", 0)
    delta_y = data.get("y", 0)

    # Logging joystick is too verbose for INFO, keep to DEBUG
    # logger.debug(f"Joystick move: {delta_x}, {delta_y}")

    curr_x, curr_y = app.plotter.get_current_coords()
    app.plotter.move_straight_line(curr_x + delta_x, curr_y + delta_y, app.plotter.z)


@socketio.on("set_home")
def handle_home():
    logger.info("Setting Home Position")
    if app.plotter:
        home_x = app.plotter.MOTOR_DISTANCE / 2
        home_y = 12.5
        app.plotter.set_current_position(home_x, home_y)


@socketio.on("clear_canvas")
def handle_clear():
    logger.info("Clearing Canvas")
    if app.plotter:
        app.plotter.clear_canvas()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        logger.warning("Upload attempt with no file")
        return jsonify({"error": "No file"}), 400
    file = request.files["file"]
    if file.filename == "" or not file.filename.endswith(".yaml"):
        logger.warning("Upload attempt with invalid file/extension")
        return jsonify({"error": "Invalid file"}), 400

    try:
        content = file.read().decode("utf-8")
        parsed_data = yaml.safe_load(content)
        logger.info(f"Starting plot from file: {file.filename}")
        threading.Thread(target=plot_from_file, args=(app.plotter, parsed_data)).start()
        return jsonify({"status": "Plot started"}), 200
    except Exception as e:
        logger.error(f"Failed to process file: {str(e)}")
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    with VPlotter() as plotter:
        app.plotter = plotter
        logger.info("Starting Web Server...")
        socketio.run(app, debug=True, host="0.0.0.0", port=5000, use_reloader=False)

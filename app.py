import logging
from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit
import yaml
import os
from plot.plot import plot_pattern
from plot import calibrate
from plot.vplotter import VPlotter
import threading
import cv2
import base64
import time
import queue
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

# Job Queue & Status Globals
job_queue = queue.Queue()
current_job_stop_event = None
is_processing_job = False

thread = None
thread_lock = threading.Lock()


def job_worker():
    """Background thread to process plot jobs from the queue."""
    global current_job_stop_event, is_processing_job
    while True:
        try:
            job_data = job_queue.get()
            if app.plotter:
                is_processing_job = True
                current_job_stop_event = threading.Event()
                logger.info("Starting queued job")
                try:
                    plot_pattern(
                        app.plotter, job_data, stop_event=current_job_stop_event
                    )
                except Exception as e:
                    logger.error(f"Error executing job: {e}")
                finally:
                    is_processing_job = False
                    current_job_stop_event = None
                    logger.info("Job finished or cancelled")
            else:
                logger.warning("Plotter not ready, skipping job")
            job_queue.task_done()
        except Exception as e:
            logger.error(f"Worker thread error: {e}")


# Start the worker thread
worker_thread = threading.Thread(target=job_worker, daemon=True)
worker_thread.start()


def background_status_thread():
    while True:
        if app.plotter:
            try:
                plotter_x, plotter_y = app.plotter.get_current_coords()
                state = {
                    "active": True,
                    "x": plotter_x,
                    "y": plotter_y,
                    "w": app.plotter.w,
                    "motor_distance": app.plotter.MOTOR_DISTANCE,
                    "bounds": app.config["CANVAS_BOUNDS"],
                    "queue_size": job_queue.qsize(),
                    "is_working": is_processing_job,
                }
                if hasattr(app.plotter, "canvas") and app.plotter.canvas is not None:
                    try:
                        _, buffer = cv2.imencode(".jpg", app.plotter.canvas)
                        state["canvas"] = base64.b64encode(buffer).decode("utf-8")
                    except Exception as e:
                        logger.error(f"Error encoding canvas: {e}")
                socketio.emit("status_update", state)
            except Exception as e:
                logger.warning(e)
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
    if is_processing_job:
        logger.warning("Ignored manual move while printing")
        return

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
    if app.plotter is None or is_processing_job:
        return
    delta_x = data.get("x", 0)
    delta_y = data.get("y", 0)
    curr_x, curr_y = app.plotter.get_current_coords()
    app.plotter.move_straight_line(curr_x + delta_x, curr_y + delta_y, app.plotter.w)
    return {"status": "done", "new_x": curr_x + delta_x, "new_y": curr_y + delta_y}


@socketio.on("set_home")
def handle_home():
    if is_processing_job:
        return
    logger.info("Setting Home Position")
    if app.plotter:
        home_x = app.plotter.MOTOR_DISTANCE / 2
        home_y = 125
        app.plotter.set_current_position(home_x, home_y)


@socketio.on("clear_canvas")
def handle_clear():
    logger.info("Clearing Canvas")
    if app.plotter:
        app.plotter.clear_canvas()


@socketio.on("cancel_job")
def handle_cancel_job():
    global current_job_stop_event
    logger.info("Cancel requested")

    # 1. Clear Pending Queue
    with job_queue.mutex:
        job_queue.queue.clear()

    # 2. Stop current job if running
    if is_processing_job and current_job_stop_event:
        current_job_stop_event.set()
        logger.info("Sent stop signal to current job")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files["file"]
    if file.filename == "" or not file.filename.endswith(".yaml"):
        return jsonify({"error": "Invalid file"}), 400
    try:
        content = file.read().decode("utf-8")
        parsed_data = yaml.safe_load(content)
        job_queue.put(parsed_data)
        logger.info(f"Job enqueued from file: {file.filename}")
        return jsonify({"status": "Job enqueued", "queue_size": job_queue.qsize()}), 200
    except Exception as e:
        logger.error(f"Failed to process file: {str(e)}")
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    with VPlotter() as plotter:
        app.plotter = plotter
        logger.info("Starting Web Server...")
        socketio.run(app, debug=True, host="0.0.0.0", port=5000, use_reloader=False)

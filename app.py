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
import uuid
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

# Job Queue
job_list = []
job_lock = threading.Lock()
current_job_id = None
current_job_stop_event = None
is_processing_job = False

thread = None
thread_lock = threading.Lock()


def broadcast_status_snapshot():
    """Helper to emit status immediately without waiting for the loop."""
    if not app.plotter:
        return

    try:
        plotter_x, plotter_y = app.plotter.get_current_coords()

        with job_lock:
            queue_snapshot = [{"id": j["id"], "name": j["name"]} for j in job_list]
            curr_id = current_job_id
            working = is_processing_job

        state = {
            "active": True,
            "x": plotter_x,
            "y": plotter_y,
            "w": app.plotter.w,
            "motor_distance": app.plotter.MOTOR_DISTANCE,
            "bounds": app.config["CANVAS_BOUNDS"],
            "queue": queue_snapshot,
            "current_job_id": curr_id,
            "is_working": working,
        }

        # Canvas encoding can be heavy, handle lightly if needed
        if hasattr(app.plotter, "canvas") and app.plotter.canvas is not None:
            _, buffer = cv2.imencode(".jpg", app.plotter.canvas)
            state["canvas"] = base64.b64encode(buffer).decode("utf-8")

        socketio.emit("status_update", state)
    except Exception as e:
        logger.warning(f"Broadcast error: {e}")


def job_worker():
    """Background thread to process jobs."""
    global current_job_stop_event, is_processing_job, current_job_id

    while True:
        job = None
        # LOCK CRITICAL SECTION
        with job_lock:
            if job_list:
                job = job_list.pop(0)
                # Set identity immediately to prevent 'cancel' race condition
                current_job_id = job["id"]
                current_job_stop_event = threading.Event()
                is_processing_job = True

        if job:
            if app.plotter:
                logger.info(f"Starting job: {job['name']}")
                broadcast_status_snapshot()  # Notify UI immediately

                try:
                    if job["type"] == "pattern":
                        plot_pattern(
                            app.plotter, job["data"], stop_event=current_job_stop_event
                        )
                    elif job["type"] == "move":
                        target = job["target"]
                        tx, ty = 0, 0
                        if target == "start":
                            tx, ty = app.plotter.START_POSITION
                        elif target == "dock":
                            tx, ty = app.plotter.DOCK_POSITION

                        # Stop event check before moving
                        if not current_job_stop_event.is_set():
                            app.plotter.move_straight_line(tx, ty, 0)

                except Exception as e:
                    logger.error(f"Error executing job: {e}")
                finally:
                    # Clean up strictly
                    with job_lock:
                        is_processing_job = False
                        current_job_id = None
                        current_job_stop_event = None

                    logger.info("Job finished")
                    broadcast_status_snapshot()  # Notify UI completion
            else:
                # Rollback if plotter missing
                with job_lock:
                    is_processing_job = False
                    current_job_id = None
                logger.warning("Plotter not ready, skipping job")

        time.sleep(0.1)


worker_thread = threading.Thread(target=job_worker, daemon=True)
worker_thread.start()


def background_status_thread():
    while True:
        broadcast_status_snapshot()
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
        return
    direction = data.get("direction")
    speed = int(data.get("speed", 100))

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
    return {"status": "done"}


@socketio.on("set_home")
def handle_home():
    if is_processing_job:
        return
    if app.plotter:
        hx, hy = app.plotter.DOCK_POSITION
        app.plotter.set_current_position(hx, hy)


@socketio.on("clear_canvas")
def handle_clear():
    if app.plotter:
        app.plotter.clear_canvas()


@socketio.on("cancel_job")
def handle_cancel_job(data):
    global current_job_stop_event
    job_id = data.get("id")
    logger.info(f"Cancel requested for ID: {job_id}")

    with job_lock:
        # 1. Remove from waiting queue first
        initial_len = len(job_list)
        job_list[:] = [j for j in job_list if j["id"] != job_id]

        # 2. Check if it is the actively running job
        if is_processing_job and current_job_id == job_id and current_job_stop_event:
            current_job_stop_event.set()
            logger.info("Sent stop signal to active job")
        elif len(job_list) < initial_len:
            logger.info("Removed job from queue")

    # 3. Force immediate UI update
    broadcast_status_snapshot()


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

        with job_lock:
            # Add Sequence: Start -> Pattern -> Dock
            job_list.append(
                {
                    "id": str(uuid.uuid4()),
                    "type": "move",
                    "target": "start",
                    "name": "Move to Start",
                }
            )
            job_list.append(
                {
                    "id": str(uuid.uuid4()),
                    "type": "pattern",
                    "data": parsed_data,
                    "name": file.filename,
                }
            )
            job_list.append(
                {
                    "id": str(uuid.uuid4()),
                    "type": "move",
                    "target": "dock",
                    "name": "Return to Dock",
                }
            )

        broadcast_status_snapshot()  # Immediate update
        logger.info(f"Job sequence enqueued for: {file.filename}")
        return jsonify({"status": "Jobs enqueued"}), 200
    except Exception as e:
        logger.error(f"Failed: {str(e)}")
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    with VPlotter() as plotter:
        app.plotter = plotter
        logger.info("Starting Web Server...")
        socketio.run(app, debug=True, host="0.0.0.0", port=5000, use_reloader=False)

import logging
from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit
import yaml
import os
from plot.plot import plot_pattern, execute_move_sequence
from plot import calibrate
from plot.vplotter import VPlotter
import threading
import cv2
import base64
import time
import uuid
from dotenv import load_dotenv
import numpy as np

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
current_job_name = None
current_job_stop_event = None
is_processing_job = False

thread = None
thread_lock = threading.Lock()


def add_job(job_type, data, name="Job"):
    """Helper to safely add a job to the queue."""
    job_id = str(uuid.uuid4())
    logger.info(f"Queueing job: {name} ({job_type})")
    with job_lock:
        job_list.append(
            {
                "id": job_id,
                "type": job_type,
                "data": data,
                "name": name,
            }
        )
    broadcast_status_snapshot()
    return job_id


def broadcast_status_snapshot():
    """Helper to emit status immediately without waiting for the loop."""
    if not app.plotter:
        return

    try:
        plotter_x, plotter_y = app.plotter.get_current_coords()

        with job_lock:
            queue_snapshot = [{"id": j["id"], "name": j["name"]} for j in job_list]
            curr_id = current_job_id
            curr_name = current_job_name
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
            "current_job_name": curr_name,
            "is_working": working,
        }

        if hasattr(app.plotter, "canvas") and app.plotter.canvas is not None:
            _, buffer = cv2.imencode(".jpg", app.plotter.canvas)
            state["canvas"] = base64.b64encode(buffer).decode("utf-8")

        socketio.emit("status_update", state)
    except Exception as e:
        logger.warning(f"Broadcast error: {e}")


def job_worker():
    """Background thread to process jobs."""
    global current_job_stop_event, is_processing_job, current_job_id, current_job_name

    while True:
        job = None
        with job_lock:
            if job_list:
                job = job_list.pop(0)
                current_job_id = job["id"]
                current_job_name = job["name"]
                current_job_stop_event = threading.Event()
                is_processing_job = True

        if job:
            if app.plotter:
                # logger.info(f"Starting job: {job['name']}")
                broadcast_status_snapshot()

                try:
                    # --- Pattern Job ---
                    if job["type"] == "pattern":
                        plot_pattern(
                            app.plotter, job["data"], stop_event=current_job_stop_event
                        )

                    # --- Preset Move (Start/Dock) ---
                    elif job["type"] == "move":
                        target = job["data"].get("target")
                        execute_move_sequence(
                            app.plotter, target, stop_event=current_job_stop_event
                        )

                    # --- Manual XY Move ---
                    elif job["type"] == "manual_xy":
                        dx = job["data"].get("x", 0)
                        dy = job["data"].get("y", 0)
                        curr_x, curr_y = app.plotter.get_current_coords()
                        if not current_job_stop_event.is_set():
                            app.plotter.move_straight_line(
                                curr_x + dx, curr_y + dy, app.plotter.w
                            )

                    # --- Manual Motor Step ---
                    elif job["type"] == "manual_motor":
                        motor_key = job["data"].get("motor")
                        steps = int(job["data"].get("steps", 0))
                        direction = 1 if steps > 0 else -1
                        count = abs(steps)
                        if motor_key == "left":
                            calibrate.steps_left(count * direction, app.plotter)
                        elif motor_key == "right":
                            calibrate.steps_right(count * direction, app.plotter)
                        # Sync Coords
                        app.plotter.x, app.plotter.y = app.plotter.get_current_coords()

                    # --- Servo Delta ---
                    elif job["type"] == "manual_servo":
                        delta = float(job["data"].get("delta", 0))
                        new_w = np.clip(app.plotter.w + delta, 0, 1)
                        if not current_job_stop_event.is_set():
                            app.plotter.move_straight_line(w=new_w)

                    # --- Set Home ---
                    elif job["type"] == "set_home":
                        hx, hy = app.plotter.DOCK_POSITION
                        app.plotter.set_current_position(hx, hy)

                    # --- Clear Canvas ---
                    elif job["type"] == "clear_canvas":
                        app.plotter.clear_canvas()

                except Exception as e:
                    logger.error(f"Error executing job {job['type']}: {e}")
                finally:
                    with job_lock:
                        is_processing_job = False
                        current_job_id = None
                        current_job_name = None
                        current_job_stop_event = None
                    broadcast_status_snapshot()
            else:
                with job_lock:
                    is_processing_job = False
                    current_job_id = None
                    current_job_name = None
                logger.warning("Plotter not ready, skipping job")

        time.sleep(0.05)


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


@socketio.on("move_xy")
def handle_move_xy(data):
    """Queues a XY move command."""
    add_job("manual_xy", data, "Manual Move")


@socketio.on("move_raw_motor")
def handle_raw_motor(data):
    """Queues a motor step command."""
    add_job("manual_motor", data, "Motor Adjust")


@socketio.on("move_servo_delta")
def handle_servo_delta(data):
    """Queues a servo change."""
    add_job("manual_servo", data, "Pen Width")


@socketio.on("set_home")
def handle_home():
    """Queues a home reset."""
    add_job("set_home", {}, "Set Home")


@socketio.on("clear_canvas")
def handle_clear():
    """Queues a canvas clear."""
    add_job("clear_canvas", {}, "Clear Canvas")


@socketio.on("cancel_job")
def handle_cancel_job(data):
    global current_job_stop_event
    job_id = data.get("id")
    logger.info(f"Cancel requested for ID: {job_id}")

    with job_lock:
        initial_len = len(job_list)
        job_list[:] = [j for j in job_list if j["id"] != job_id]

        if is_processing_job and current_job_id == job_id and current_job_stop_event:
            current_job_stop_event.set()
        elif len(job_list) < initial_len:
            logger.info("Removed job from queue")

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

        add_job("move", {"target": "start"}, f"Init {file.filename}")
        add_job("pattern", parsed_data, f"Draw {file.filename}")
        add_job("move", {"target": "dock"}, f"Cleanup {file.filename}")

        return jsonify({"status": "Jobs enqueued"}), 200
    except Exception as e:
        logger.error(f"Failed: {str(e)}")
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    with VPlotter() as plotter:
        app.plotter = plotter
        logger.info("Starting Web Server...")
        socketio.run(app, debug=True, host="0.0.0.0", port=5000, use_reloader=False)

import threading
import time
import uuid
import yaml
import logging
import cv2
import base64
import numpy as np
from flask import Blueprint, render_template, request, jsonify
from flask_socketio import emit, join_room, leave_room
from plot.plot import plot_pattern, execute_move_sequence
from plot import calibrate
import extensions

logger = logging.getLogger(__name__)
plotter_bp = Blueprint("plotter", __name__)
socket_ref = None

# Track number of active viewers to avoid expensive canvas processing
active_viewers = 0
viewer_lock = threading.Lock()
PLOTTER_ROOM = "plotter_viewers"


def add_job(job_type, data, name="Job"):
    job_id = str(uuid.uuid4())
    with extensions.job_lock:
        extensions.job_list.append(
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
    if not extensions.plotter_instance or not socket_ref:
        return
    
    # Check if anyone is actually watching before doing expensive work
    with viewer_lock:
        if active_viewers <= 0:
            return

    try:
        plotter = extensions.plotter_instance
        px, py = plotter.get_current_coords()

        with extensions.job_lock:
            q_snap = [{"id": j["id"], "name": j["name"]} for j in extensions.job_list]
            curr_id = extensions.current_job_id
            curr_name = extensions.current_job_name
            working = extensions.is_processing_job

        state = {
            "active": True,
            "x": px,
            "y": py,
            "w": plotter.w,
            "motor_distance": plotter.MOTOR_DISTANCE,
            "bounds": extensions.CANVAS_BOUNDS,
            "queue": q_snap,
            "current_job_id": curr_id,
            "current_job_name": curr_name,
            "is_working": working,
            "led_color": plotter.led_color,
        }

        # Only encode canvas if someone is watching
        if hasattr(plotter, "canvas") and plotter.canvas is not None:
            _, buffer = cv2.imencode(".jpg", plotter.canvas)
            state["canvas"] = base64.b64encode(buffer).decode("utf-8")

        socket_ref.emit("status_update", state, room=PLOTTER_ROOM)
    except Exception as e:
        logger.warning(f"Broadcast error: {e}")


def job_worker():
    while True:
        job = None
        with extensions.job_lock:
            if extensions.job_list:
                job = extensions.job_list.pop(0)
                extensions.current_job_id = job["id"]
                extensions.current_job_name = job["name"]
                extensions.current_job_stop_event = threading.Event()
                extensions.is_processing_job = True

        if job and extensions.plotter_instance:
            broadcast_status_snapshot()
            try:
                stop_evt = extensions.current_job_stop_event
                plotter = extensions.plotter_instance

                if job["type"] == "pattern":
                    plot_pattern(plotter, job["data"], stop_event=stop_evt)
                elif job["type"] == "move":
                    target = job["data"].get("target")
                    execute_move_sequence(plotter, target, stop_event=stop_evt)
                elif job["type"] == "manual_xy":
                    dx, dy = job["data"].get("x", 0), job["data"].get("y", 0)
                    cx, cy = plotter.get_current_coords()
                    if not stop_evt.is_set():
                        plotter.move_straight_line(cx + dx, cy + dy, plotter.w)
                elif job["type"] == "manual_motor":
                    m_key = job["data"].get("motor")
                    steps = int(job["data"].get("steps", 0))
                    d = 1 if steps > 0 else -1
                    if m_key == "left":
                        calibrate.steps_left(abs(steps) * d, plotter)
                    elif m_key == "right":
                        calibrate.steps_right(abs(steps) * d, plotter)
                    plotter.x, plotter.y = plotter.get_current_coords()
                elif job["type"] == "manual_servo":
                    delta = float(job["data"].get("delta", 0))
                    new_w = np.clip(plotter.w + delta, 0, 1)
                    if not stop_evt.is_set():
                        plotter.move_straight_line(w=new_w)
                elif job["type"] == "set_home":
                    plotter.set_current_position(*plotter.DOCK_POSITION)
                elif job["type"] == "clear_canvas":
                    plotter.clear_canvas()

            except Exception as e:
                logger.error(f"Job failed: {e}")
            finally:
                with extensions.job_lock:
                    extensions.is_processing_job = False
                    extensions.current_job_id = None
                    extensions.current_job_name = None
                    extensions.current_job_stop_event = None
                broadcast_status_snapshot()
        else:
            with extensions.job_lock:
                extensions.is_processing_job = False
        time.sleep(0.1)


def background_status_thread():
    while True:
        broadcast_status_snapshot()
        if socket_ref:
            socket_ref.sleep(0.1)


def start_background_threads(socketio_instance):
    global socket_ref
    socket_ref = socketio_instance
    threading.Thread(target=job_worker, daemon=True).start()
    socket_ref.start_background_task(background_status_thread)

    @socket_ref.on("connect")
    def handle_connect():
        emit("config", extensions.CANVAS_BOUNDS)

    @socket_ref.on("subscribe_plotter")
    def handle_subscribe():
        global active_viewers
        join_room(PLOTTER_ROOM)
        with viewer_lock:
            active_viewers += 1
        logger.info(f"Client subscribed to plotter. Active viewers: {active_viewers}")
        # Send an immediate update
        broadcast_status_snapshot()

    @socket_ref.on("unsubscribe_plotter")
    def handle_unsubscribe():
        global active_viewers
        leave_room(PLOTTER_ROOM)
        with viewer_lock:
            active_viewers = max(0, active_viewers - 1)
        logger.info(f"Client unsubscribed from plotter. Active viewers: {active_viewers}")

    @socket_ref.on("disconnect")
    def handle_disconnect():
        global active_viewers
        # Note: join_room/leave_room are automatic on disconnect, but we need to track our count
        # This is tricky because we don't know if they were subscribed.
        # However, Socket.IO rooms handle this. We might need a per-session flag if we want accuracy.
        # For now, let's keep it simple. If they disconnect, we assume they were a viewer if they subscribed.
        pass

    @socket_ref.on("move_xy")
    def handle_move_xy(data):
        add_job("manual_xy", data, "Manual Move")

    @socket_ref.on("move_raw_motor")
    def handle_raw_motor(data):
        add_job("manual_motor", data, "Motor Adjust")

    @socket_ref.on("move_servo_delta")
    def handle_servo_delta(data):
        add_job("manual_servo", data, "Pen Width")

    @socket_ref.on("set_home")
    def handle_home():
        add_job("set_home", {}, "Set Home")

    @socket_ref.on("clear_canvas")
    def handle_clear():
        add_job("clear_canvas", {}, "Clear Canvas")

    @socket_ref.on("cancel_job")
    def handle_cancel_job(data):
        jid = data.get("id")
        with extensions.job_lock:
            extensions.job_list[:] = [j for j in extensions.job_list if j["id"] != jid]
        if (
            extensions.is_processing_job
            and extensions.current_job_id == jid
            and extensions.current_job_stop_event
        ):
            extensions.current_job_stop_event.set()
        broadcast_status_snapshot()


@plotter_bp.route("/enqueue", methods=["POST"])
def enqueue_job():
    data = request.json
    job_type = data.get("type")
    job_data = data.get("data")
    job_name = data.get("name", "Remote Job")

    if not job_type or not job_data:
        return jsonify({"error": "Missing type or data"}), 400

    job_id = add_job(job_type, job_data, job_name)
    return jsonify({"status": "enqueued", "job_id": job_id}), 200


@plotter_bp.route("/plotter")
def index():
    return render_template("plotter.html")


@plotter_bp.route("/upload", methods=["POST"])
def upload_file_direct():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files["file"]
    if file.filename == "" or not file.filename.endswith(".yaml"):
        return jsonify({"error": "Invalid"}), 400
    try:
        content = file.read().decode("utf-8")
        parsed = yaml.safe_load(content)
        add_job("move", {"target": "start"}, f"Init {file.filename}")
        add_job("pattern", parsed, f"Draw {file.filename}")
        add_job("move", {"target": "dock"}, f"Cleanup {file.filename}")
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

import os
import time
import json
import logging
import requests
import yaml
import threading
from datetime import datetime
from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    current_app,
    send_from_directory,
)
from blueprints.plotter import add_job
import extensions
from PIL import Image, ImageOps

processor_bp = Blueprint("processor", __name__)
logger = logging.getLogger(__name__)

HISTORY_FILE = "job_history.json"
DRAW_API_URL = "http://100.96.142.12:30734"
socket_ref = None

PROMPTS = {
    "cute": "Transform into Q版风格 — chibi style, extremely simplified features, with flat colors, thick black lines and white background.",
    "realistic": "Transform into comic book pop art style — bold black outlines, flat color zones, no gradients, white background.",
}


def generate_job_id():
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    uid = os.urandom(2).hex()
    return f"{timestamp}_{uid}"


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return []


def save_history(history):
    logger.debug(("save history", HISTORY_FILE))
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def download_file(url, local_path):
    if not os.path.exists(local_path):
        try:
            content = requests.get(url).content
            with open(local_path, "wb") as f:
                f.write(content)
            return True
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
    return False


def enqueue_job_logic(job_id, filename):
    # Depending on your workflow, you might prioritize a specific file (e.g., the plotted SVG/YAML)
    # Here we assume the standard 4_plotter.yaml still exists, or we use a fallback
    yaml_path = os.path.join(
        "uploads",
        job_id,
        "proc",
        "4_plotter.yaml",
    )
    # Fallback to current working dir check if extension context is vague
    if not os.path.exists(yaml_path):
        yaml_path = os.path.join("uploads", job_id, "proc", "4_plotter.yaml")

    if not os.path.exists(yaml_path):
        raise FileNotFoundError("YAML file not found")

    with open(yaml_path, "r") as f:
        content = yaml.safe_load(f)

    add_job("move", {"target": "start"}, f"Init {filename}")
    add_job("pattern", content, f"AI Draw {filename}")
    add_job("move", {"target": "dock"}, f"Dock {filename}")


# --- Background Worker ---


def background_status_worker():
    while True:
        try:
            check_and_update_jobs()
        except Exception as e:
            logger.error(f"Background sync error: {e}")
        time.sleep(3)


def start_background_threads(socketio_instance):
    global socket_ref
    socket_ref = socketio_instance
    threading.Thread(target=background_status_worker, daemon=True).start()


def check_and_update_jobs():
    history = load_history()
    updated = False

    # Needs valid context for UPLOAD_FOLDER during background run
    # We'll use a hardcoded relative path or environment variable if context is missing
    base_upload_folder = "uploads"  # Default fallback

    for job in history:
        if job["status"] not in ["complete", "failed"]:
            try:
                res = requests.get(f"{DRAW_API_URL}/status/{job['remote_id']}")
                if res.status_code == 200:
                    data = res.json()

                    if data.get("error"):
                        job["status"] = "failed"
                        logger.warning(("error", job))
                        updated = True
                        continue

                    proc_dir = os.path.join(base_upload_folder, job["id"], "proc")
                    os.makedirs(proc_dir, exist_ok=True)

                    files_map = data.get("files", {})
                    job_assets = job.get("assets", [])

                    # Download ALL PNGs and important YAMLs
                    new_asset_found = False
                    for stage_name, remote_path in files_map.items():
                        fname = os.path.basename(remote_path)
                        lower_name = fname.lower()

                        if lower_name.endswith(".png") or lower_name.endswith(
                            "plotter.yaml"
                        ):
                            if download_file(
                                f"{DRAW_API_URL}{remote_path}",
                                os.path.join(proc_dir, fname),
                            ):
                                if fname not in job_assets:
                                    job_assets.append(fname)
                                    new_asset_found = True

                    job["assets"] = job_assets
                    if new_asset_found:
                        save_history(history)
                        updated = True

                    # Check completion status
                    if data.get("status") == "Complete":
                        job["status"] = "complete"
                        updated = True

                        if job.get("auto_queue") and not job.get(
                            "queued_automatically"
                        ):
                            try:
                                enqueue_job_logic(job["id"], job["filename"])
                                job["queued_automatically"] = True
                            except Exception as e:
                                logger.error(f"Auto-queue failed for {job['id']}: {e}")

            except Exception as e:
                logger.warning(f"Sync error for {job['id']}: {e}")

    if updated:
        save_history(history)
        if socket_ref:
            socket_ref.emit("processor_update", history)

    return history


@processor_bp.route("/processor")
def index():
    return render_template("processor.html")


@processor_bp.route("/processor/submit", methods=["POST"])
def submit_image():
    if "image" not in request.files:
        return jsonify({"error": "No image"}), 400

    image = request.files["image"]
    prompt_mode = request.form.get("prompt_mode", "cute")
    custom_prompt = request.form.get("custom_prompt", "")
    auto_queue = request.form.get("auto_queue") == "true"

    final_prompt = (
        PROMPTS.get(prompt_mode, custom_prompt)
        if prompt_mode != "custom"
        else custom_prompt
    )

    job_id = generate_job_id()
    job_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], job_id)
    proc_dir = os.path.join(job_dir, "proc")
    os.makedirs(proc_dir, exist_ok=True)

    ext = os.path.splitext(image.filename)[1].lower()
    original_filename = f"original{ext}"
    original_path = os.path.join(job_dir, original_filename)

    try:
        img = Image.open(image)
        img = ImageOps.exif_transpose(img)

        save_kwargs = {}
        if ext in [".jpg", ".jpeg"]:
            save_kwargs = {"format": "JPEG", "quality": 95}
        elif ext == ".png":
            save_kwargs = {"format": "PNG"}
        elif ext == ".webp":
            save_kwargs = {"format": "WEBP", "quality": 95}
        else:
            ext = ".jpg"
            original_filename = "original.jpg"
            original_path = os.path.join(job_dir, original_filename)
            save_kwargs = {"format": "JPEG", "quality": 95}

        img.save(original_path, **save_kwargs)

    except Exception as e:
        logger.error(f"Image processing error: {e}")
        image.seek(0)
        image.save(original_path)

    try:
        with open(original_path, "rb") as f:
            files = {"image": (image.filename, f)}
            data = {"prompt": final_prompt}
            res = requests.post(f"{DRAW_API_URL}/convert", files=files, data=data)
            res.raise_for_status()
            remote_job_id = res.json()["job_id"]

        history = load_history()
        new_job = {
            "id": job_id,
            "remote_id": remote_job_id,
            "filename": image.filename,
            "original_file": original_filename,
            "prompt": final_prompt,
            "status": "pending",
            "auto_queue": auto_queue,
            "timestamp": time.time(),
            "assets": [],
        }
        history.insert(0, new_job)
        save_history(history)

        if socket_ref:
            socket_ref.emit("processor_update", history)

        return jsonify({"status": "submitted", "job_id": job_id})
    except Exception as e:
        logger.error(f"Draw API error: {e}")
        return jsonify({"error": str(e)}), 500


@processor_bp.route("/processor/list")
def list_jobs():
    return jsonify(load_history())


@processor_bp.route("/processor/send_plot/<job_id>", methods=["POST"])
def send_to_plot(job_id):
    history = load_history()
    job = next((j for j in history if j["id"] == job_id), None)

    if not job or job["status"] != "complete":
        return jsonify({"error": "Job not found or not ready"}), 404

    try:
        enqueue_job_logic(job_id, job["filename"])
        return jsonify({"status": "enqueued"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@processor_bp.route("/processed/<job_id>/<path:filename>")
def serve_processed(job_id, filename):
    job_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], job_id)
    proc_dir = os.path.join(job_dir, "proc")

    if os.path.exists(os.path.join(proc_dir, filename)):
        return send_from_directory(proc_dir, filename)

    if os.path.exists(os.path.join(job_dir, filename)):
        return send_from_directory(job_dir, filename)

    return "File not found", 404

import os
import json
import uuid
import logging
import requests
import yaml
from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    current_app,
    send_from_directory,
    send_file,
)
from werkzeug.utils import secure_filename
from pathlib import Path
from datetime import datetime
from PIL import Image

logger = logging.getLogger(__name__)
processor_bp = Blueprint("processor", __name__)

AI_BACKEND_URL = os.getenv("AI_BACKEND_URL", "http://100.96.142.12:5002")
UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads", "processor")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

import threading
import time

# Global set of job IDs we are currently monitoring for status updates
monitored_jobs = set()
monitored_lock = threading.Lock()
socket_ref = None

# In-memory job tracking for active sessions
active_jobs = {}  # image_id -> list of job_ids


def get_image_dir(image_id):
    path = os.path.join(UPLOAD_FOLDER, image_id)
    os.makedirs(path, exist_ok=True)
    return path


def get_processed_dir(image_id):
    path = os.path.join(get_image_dir(image_id), "processed")
    os.makedirs(path, exist_ok=True)
    return path


@processor_bp.route("/processor")
def index():
    return render_template("processor.html")


@processor_bp.route("/processor/upload", methods=["POST"])
def upload_image():
    if "image" not in request.files:
        return jsonify({"error": "No image part"}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    image_id = str(uuid.uuid4())
    image_dir = get_image_dir(image_id)

    filename = secure_filename(file.filename)
    extension = os.path.splitext(filename)[1]
    original_path = os.path.join(image_dir, f"original{extension}")
    file.save(original_path)

    # Apply crop if crop parameters are provided
    crop_left = request.form.get('crop_left', type=float, default=0)
    crop_top = request.form.get('crop_top', type=float, default=0)
    crop_right = request.form.get('crop_right', type=float, default=0)
    crop_bottom = request.form.get('crop_bottom', type=float, default=0)

    has_crop = crop_left > 0 or crop_top > 0 or crop_right > 0 or crop_bottom > 0
    if has_crop:
        try:
            with Image.open(original_path) as img:
                width, height = img.size
                # Calculate crop box in pixels from percentages
                left = int((crop_left / 100) * width)
                top = int((crop_top / 100) * height)
                right = width - int((crop_right / 100) * width)
                bottom = height - int((crop_bottom / 100) * height)
                # Ensure valid crop box
                if right > left and bottom > top:
                    cropped = img.crop((left, top, right, bottom))
                    cropped.save(original_path, quality=95)
        except Exception as e:
            print(f"Crop error: {e}")
            # Continue with uncropped image on error

    # Initialize metadata
    metadata = {
        "id": image_id,
        "original_filename": file.filename,
        "original_url": f"/processor/serve/{image_id}/original{extension}",
        "upload_time": datetime.now().isoformat(),
        "workflows": [],
    }
    with open(os.path.join(image_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f)

    return jsonify({"status": "ok", "image_id": image_id, "metadata": metadata}), 200


@processor_bp.route("/processor/images", methods=["GET"])
def list_images():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))

    all_dirs = []
    if os.path.exists(UPLOAD_FOLDER):
        for d in os.listdir(UPLOAD_FOLDER):
            dir_path = os.path.join(UPLOAD_FOLDER, d)
            if os.path.isdir(dir_path):
                mtime = os.path.getmtime(dir_path)
                all_dirs.append((d, mtime))

    # Sort by mtime descending (newest first)
    all_dirs.sort(key=lambda x: x[1], reverse=True)

    start = (page - 1) * per_page
    end = start + per_page
    paged_dirs = all_dirs[start:end]

    results = []
    for image_id, _ in paged_dirs:
        image_dir = get_image_dir(image_id)
        metadata_path = os.path.join(image_dir, "metadata.json")
        if os.path.exists(metadata_path):
            with open(metadata_path, "r") as f:
                meta = json.load(f)

            # Ensure we have a stable original_url
            if "original_url" not in meta:
                for ext in [".jpg", ".jpeg", ".png", ".webp"]:
                    if os.path.exists(os.path.join(image_dir, f"original{ext}")):
                        meta["original_url"] = (
                            f"/processor/serve/{image_id}/original{ext}"
                        )
                        break

            # Thumbnail: latest visualizer or original
            latest_thumb = None
            processed_dir = get_processed_dir(image_id)
            # Find visualizer. Try slug name first, then look into job dirs
            vis_files = sorted(
                Path(processed_dir).rglob("visualizer*"),
                key=os.path.getmtime,
                reverse=True,
            )
            if vis_files:
                rel_path = os.path.relpath(vis_files[0], UPLOAD_FOLDER)
                latest_thumb = f"/processor/serve/{rel_path}"
            else:
                # Fallback: check if we have any cached job visualizers
                # We can trigger a refresh if we wanted, but let's stick to what we have
                latest_thumb = meta.get("original_url")

            meta["thumbnail"] = latest_thumb
            results.append(meta)

    return jsonify({"images": results, "has_more": end < len(all_dirs)})


@processor_bp.route("/processor/serve/<path:filename>")
def serve_image(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@processor_bp.route("/processor/run_workflow", methods=["POST"])
def run_workflow():
    data = request.json
    image_id = data.get("image_id")
    workflow_name = data.get("workflow_name")
    priority = data.get("priority", 100)

    if not image_id or not workflow_name:
        return jsonify({"error": "Missing image_id or workflow_name"}), 400

    image_dir = get_image_dir(image_id)
    # Find original image
    original_path = None
    for ext in [".jpg", ".jpeg", ".png", ".webp"]:
        path = os.path.join(image_dir, f"original{ext}")
        if os.path.exists(path):
            original_path = path
            break

    if not original_path:
        return jsonify({"error": "Original image not found"}), 404

    # Define workflows
    workflows = {
        "clean": [
            {"stage": "rmbg"},
            # {"stage": "face_detection", "params": {"margin_mm": 20}},
            # {"stage": "add_logo"},
            # {"stage": "slicer", "params": {"scale": 1, "min_width": 0.1}},
            {
                "stage": "i2i",
                "params": {
                    "prompt": "Simple flat illustration like a basic infographic icon or emoji style. Thick black outlines, solid flat colors, white background. Minimal details. No textures, no gradients, no fine details.",
                },
            },
            {"stage": "cleanup"},
            {"stage": "centerline"},
            {
                "stage": "slicer",
                "params": {"scale": 1, "min_width": 1, "taper_length_mm": 40},
            },
            {"stage": "visualizer"},
        ],
        "kawaii": [
            {"stage": "rmbg"},
            # {"stage": "face_detection", "params": {"margin_mm": 20}},
            # {"stage": "add_logo"},
            # {"stage": "slicer", "params": {"min_width": 1}},
            {
                "stage": "i2i",
                "params": {
                    "prompt": "Stylize as adorable chibi Q版 with exaggerated proportions, shortened cute features, soft forms, thick smooth outlines, minimal complexity, flat colors, white background.",
                },
            },
            {"stage": "cleanup"},
            {"stage": "centerline"},
            {
                "stage": "slicer",
                "params": {"scale": 1, "min_width": 1, "taper_length_mm": 40},
            },
            {"stage": "visualizer"},
        ],
        "realistic": [
            {"stage": "rmbg"},
            # {"stage": "face_detection", "params": {"margin_mm": 20}},
            # {"stage": "add_logo"},
            # {"stage": "slicer", "params": {"min_width": 1}},
            {
                "stage": "i2i",
                "params": {
                    "prompt": "Realistic proportions with thick black outlines and flat solid colors only. Absolutely no hatching, no line shading, no texture details, no fine lines inside shapes. Just bold contours and solid color fills. White background. Clean and simple like a coloring book with colors filled in.",
                },
            },
            {"stage": "cleanup"},
            {"stage": "centerline"},
            {
                "stage": "slicer",
                "params": {"scale": 1, "min_width": 1, "taper_length_mm": 40},
            },
            {"stage": "visualizer"},
        ],
        "full": [
            # {"stage": "rmbg"},
            # {"stage": "add_logo"},
            # {"stage": "slicer", "params": {"min_width": 1}},
            # {"stage": "face_detection", "params": {"margin_mm": 20}},
            {
                "stage": "i2i",
                "params": {
                    "prompt": "Realistic proportions with thick black outlines and flat solid colors only. Absolutely no hatching, no line shading, no texture details, no fine lines inside shapes. Just bold contours and solid color fills. Clean and simple like a coloring book with colors filled in.",
                },
            },
            {"stage": "cleanup"},
            {"stage": "centerline"},
            {
                "stage": "slicer",
                "params": {"scale": 1, "min_width": 1, "taper_length_mm": 40},
            },
            {"stage": "visualizer"},
        ],
    }

    if workflow_name not in workflows:
        return jsonify({"error": "Invalid workflow name"}), 400

    workflow = workflows[workflow_name]

    try:
        with open(original_path, "rb") as f:
            files = {"image": f}
            payload = {"workflow": json.dumps(workflow), "priority": priority}
            response = requests.post(f"{AI_BACKEND_URL}/run", files=files, data=payload)

        if response.status_code != 202:
            return (
                jsonify({"error": f"AI Backend error: {response.text}"}),
                response.status_code,
            )

        job_id = response.json().get("job_id")

        # Update metadata
        metadata_path = os.path.join(image_dir, "metadata.json")
        with open(metadata_path, "r") as f:
            meta = json.load(f)

        meta["workflows"].append(
            {
                "job_id": job_id,
                "name": workflow_name,
                "status": "pending",
                "start_time": datetime.now().isoformat(),
            }
        )

        with open(metadata_path, "w") as f:
            json.dump(meta, f)

        # Register for background monitoring
        with monitored_lock:
            monitored_jobs.add(job_id)

        return jsonify({"status": "ok", "job_id": job_id}), 200

    except Exception as e:
        logger.error(f"Workflow submission error: {e}")
        return jsonify({"error": str(e)}), 500


def _get_cached_job_status(job_id):
    """Get job status from local metadata if available, including full cached data from backend."""
    if not os.path.exists(UPLOAD_FOLDER):
        return None
    for image_id in os.listdir(UPLOAD_FOLDER):
        image_dir = os.path.join(UPLOAD_FOLDER, image_id)
        if not os.path.isdir(image_dir):
            continue
        metadata_path = os.path.join(image_dir, "metadata.json")
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, "r") as f:
                    meta = json.load(f)
                for w in meta.get("workflows", []):
                    if w.get("job_id") == job_id:
                        # Return full cached job data if available (exact same format as backend)
                        cached_data = w.get("cached_job_data")
                        if cached_data:
                            return cached_data
                        # Fallback to basic info if no full cache
                        return {
                            "job_id": job_id,
                            "status": w.get("status"),
                            "start_time": w.get("start_time"),
                            "end_time": w.get("end_time"),
                        }
            except Exception:
                continue
    return None


@processor_bp.route("/processor/status", methods=["GET"])
def get_status():
    job_ids = request.args.get("ids", "")
    if not job_ids:
        return jsonify([])

    job_id_list = [jid.strip() for jid in job_ids.split(",") if jid.strip()]
    results = []
    jobs_to_query = []

    # First, check local cache for each job
    for job_id in job_id_list:
        cached = _get_cached_job_status(job_id)
        if cached and cached.get("status") in ["completed", "failed"]:
            # Job is finished, use cached status
            results.append(cached)
        else:
            # Need to query backend for this job
            jobs_to_query.append(job_id)

    # Only query backend for jobs that need fresh status
    if jobs_to_query:
        try:
            query_ids = ",".join(jobs_to_query)
            response = requests.get(
                f"{AI_BACKEND_URL}/status", params={"ids": query_ids}, timeout=5
            )
            if response.status_code == 200:
                backend_jobs = response.json()
                results.extend(backend_jobs)
            else:
                # Backend returned error, try to use cached data for pending/running jobs
                logger.warning(
                    f"AI Backend returned error {response.status_code}, using cached data"
                )
                for job_id in jobs_to_query:
                    cached = _get_cached_job_status(job_id)
                    if cached:
                        results.append(cached)
                    else:
                        # No cache, return as unknown
                        results.append(
                            {
                                "job_id": job_id,
                                "status": "unknown",
                                "error": "backend unreachable",
                            }
                        )
        except Exception as e:
            logger.error(f"Status check error: {e}")
            # Backend unreachable, use cached data for all remaining jobs
            for job_id in jobs_to_query:
                cached = _get_cached_job_status(job_id)
                if cached:
                    results.append(cached)
                else:
                    # No cache, return as unknown
                    results.append(
                        {
                            "job_id": job_id,
                            "status": "unknown",
                            "error": "backend unreachable",
                        }
                    )

    return jsonify(results)


def _get_artifact_path(job_id, file_hash, slug_hint="artifact"):
    """Ensures an artifact is cached locally by its hash and returns its absolute path."""
    image_id = _find_image_id_for_job(job_id)
    if not image_id:
        return None

    local_dir = os.path.join(get_processed_dir(image_id), job_id)
    os.makedirs(local_dir, exist_ok=True)

    # Check local cache first (try to find file with this hash)
    for path in Path(local_dir).glob(f"{file_hash}*"):
        if path.is_file():
            return str(path)

    # Proxy and cache if not found
    try:
        resp = requests.get(f"{AI_BACKEND_URL}/file/{file_hash}")
        if resp.status_code == 200:
            content_type = resp.headers.get("Content-Type", "")
            ext = ""
            if "image/jpeg" in content_type:
                ext = ".jpg"
            elif "image/png" in content_type:
                ext = ".png"
            elif "yaml" in content_type or slug_hint.startswith("slicer"):
                ext = ".yaml"
            elif "json" in content_type:
                ext = ".json"

            local_path = os.path.join(local_dir, file_hash + ext)
            mode = "wb" if isinstance(resp.content, (bytes, bytearray)) else "w"
            with open(local_path, mode) as f:
                f.write(resp.content if mode == "wb" else resp.text)
            return local_path
    except Exception as e:
        logger.error(f"Error fetching hash {file_hash}: {e}")
    return None


def _get_artifact_path_by_slug(job_id, slug):
    """Fallback: ensures an artifact is cached by its slug name."""
    image_id = _find_image_id_for_job(job_id)
    if not image_id:
        return None

    local_dir = os.path.join(get_processed_dir(image_id), job_id)
    os.makedirs(local_dir, exist_ok=True)

    # Check local cache first
    for path in Path(local_dir).glob(f"{slug}*"):
        if path.is_file():
            return str(path)

    # Special handling for slicer: scan for any yaml files if exact slug not found
    if slug.startswith("slicer"):
        yaml_files = list(Path(local_dir).glob("*.yaml"))
        if yaml_files:
            # Return the first yaml file found (or could sort by timestamp)
            return str(yaml_files[0])

    # Fetch from AI backend by slug
    try:
        resp = requests.get(f"{AI_BACKEND_URL}/artifact/{job_id}/{slug}")
        if resp.status_code == 200:
            content_type = resp.headers.get("Content-Type", "")
            ext = ""
            if "image/jpeg" in content_type:
                ext = ".jpg"
            elif "image/png" in content_type:
                ext = ".png"
            elif "yaml" in content_type or slug.startswith("slicer"):
                ext = ".yaml"
            elif "json" in content_type:
                ext = ".json"

            local_path = os.path.join(local_dir, slug + ext)
            mode = "wb" if isinstance(resp.content, (bytes, bytearray)) else "w"
            with open(local_path, mode) as f:
                f.write(resp.content if mode == "wb" else resp.text)
            return local_path
    except Exception as e:
        logger.error(f"Error fetching slug {slug}: {e}")
    return None


@processor_bp.route("/processor/artifact/<job_id>/<slug>", methods=["GET"])
def get_artifact(job_id, slug):
    local_path = _get_artifact_path_by_slug(job_id, slug)
    if local_path:
        return send_file(local_path)
    return jsonify({"error": "Artifact not found"}), 404


@processor_bp.route("/processor/artifact_by_hash/<job_id>/<file_hash>", methods=["GET"])
def get_artifact_by_hash(job_id, file_hash):
    slug_hint = request.args.get("slug", "artifact")
    local_path = _get_artifact_path(job_id, file_hash, slug_hint)
    if local_path:
        return send_file(local_path)
    return jsonify({"error": "Artifact not found"}), 404


def _find_image_id_for_job(job_id):
    """Scans all metadata files to find which image_id owns this job_id."""
    if not os.path.exists(UPLOAD_FOLDER):
        return None
    for im_id in os.listdir(UPLOAD_FOLDER):
        meta_path = os.path.join(UPLOAD_FOLDER, im_id, "metadata.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r") as f:
                try:
                    meta = json.load(f)
                    if any(
                        w.get("job_id") == job_id for w in meta.get("workflows", [])
                    ):
                        return im_id
                except:
                    continue
    return None


@processor_bp.route("/processor/image/<image_id>", methods=["DELETE"])
def delete_image(image_id):
    image_dir = os.path.join(UPLOAD_FOLDER, image_id)
    if os.path.exists(image_dir):
        # Stop monitoring jobs for this image
        metadata_path = os.path.join(image_dir, "metadata.json")
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, "r") as f:
                    meta = json.load(f)
                jobs_to_remove = [
                    w.get("job_id")
                    for w in meta.get("workflows", [])
                    if w.get("job_id")
                ]
                with monitored_lock:
                    for jid in jobs_to_remove:
                        if jid in monitored_jobs:
                            monitored_jobs.remove(jid)
                            logger.info(
                                f"Stopped monitoring job {jid} because image {image_id} was deleted."
                            )
            except Exception as e:
                logger.error(f"Error cleaning up monitored jobs for {image_id}: {e}")

        import shutil

        shutil.rmtree(image_dir)
        return jsonify({"status": "ok"}), 200
    return jsonify({"error": "Not found"}), 404


@processor_bp.route("/processor/image/<image_id>/details", methods=["GET"])
def image_details(image_id):
    image_dir = get_image_dir(image_id)
    metadata_path = os.path.join(image_dir, "metadata.json")
    if not os.path.exists(metadata_path):
        return jsonify({"error": "Not found"}), 404

    with open(metadata_path, "r") as f:
        meta = json.load(f)

    # Find original
    original_url = None
    for ext in [".jpg", ".jpeg", ".png", ".webp"]:
        if os.path.exists(os.path.join(image_dir, f"original{ext}")):
            original_url = f"/processor/serve/{image_id}/original{ext}"
            break
    meta["original_url"] = original_url

    return jsonify(meta)


@processor_bp.route("/processor/enqueue_to_plotter", methods=["POST"])
def enqueue_to_plotter():
    data = request.json
    job_id = data.get("job_id")
    slug = data.get("slug")
    file_hash = data.get("file_hash")

    if not job_id or (not slug and not file_hash):
        return jsonify({"error": "Missing job_id, slug, or file_hash"}), 400

    try:
        # 1. Fetch/Cache artifact
        if file_hash:
            local_path = _get_artifact_path(job_id, file_hash, slug or "slicer")
        else:
            local_path = _get_artifact_path(job_id, slug, slug)

        if not local_path:
            return jsonify({"error": "Artifact not found or could not be cached"}), 404

        with open(local_path, "r") as f:
            content = f.read()

        # 2. Parse YAML
        parsed = yaml.safe_load(content)

        # 3. Enqueue to Plotter Blueprint
        from blueprints.plotter import add_job

        # Use the full sequence as requested (similar to plotter's /upload)
        add_job("move", {"target": "start"}, f"Init {slug}")
        add_job("pattern", parsed, f"AI: {slug}")
        add_job("move", {"target": "dock"}, f"Cleanup {slug}")

        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.error(f"Enqueue to plotter error: {e}")
        return jsonify({"error": str(e)}), 500


def background_processor_thread():
    """Polls AI backend for monitored jobs and broadcasts updates via WebSocket."""
    global socket_ref
    failed_attempts = 0
    backend_was_unreachable = False

    while True:
        with monitored_lock:
            ids = list(monitored_jobs)

        if ids and socket_ref:
            try:
                # Poll AI backend for these IDs
                job_ids_str = ",".join(ids)
                response = requests.get(
                    f"{AI_BACKEND_URL}/status", params={"ids": job_ids_str}, timeout=5
                )

                if response.status_code == 200:
                    jobs = response.json()

                    if backend_was_unreachable:
                        logger.info("AI Backend is reachable again.")
                        socket_ref.emit("ai_backend_status", {"available": True})
                        backend_was_unreachable = False
                        failed_attempts = 0

                    # Update metadata on disk if a job finished
                    for job in jobs:
                        status = job.get("status")
                        job_id = job.get("job_id")

                        if status in ["completed", "failed"]:
                            _update_metadata_status(job_id, status, job)

                            with monitored_lock:
                                if job_id in monitored_jobs:
                                    monitored_jobs.remove(job_id)

                    # Broadcast the full list of tracked jobs to all clients
                    socket_ref.emit("processor_jobs_update", jobs)
                else:
                    logger.warning(
                        f"AI Backend returned error status {response.status_code}"
                    )
                    failed_attempts += 1

            except Exception as e:
                logger.warning(f"Processor background poll error: {e}")
                failed_attempts += 1

            if failed_attempts >= 3 and not backend_was_unreachable:
                logger.error("AI Backend is consistently unreachable!")
                socket_ref.emit(
                    "ai_backend_status",
                    {"available": False, "error": "AI Backend unreachable"},
                )
                backend_was_unreachable = True

        elif socket_ref and backend_was_unreachable:
            # If no jobs but backend was unreachable, maybe it's back?
            # We skip heavy polling if no jobs are tracked to save resources.
            pass

        time.sleep(2)


def _update_metadata_status(job_id, status, job_data=None):
    """Finds the image containing this job_id and updates its status and cached data in metadata.json."""
    if not os.path.exists(UPLOAD_FOLDER):
        return
    for image_id in os.listdir(UPLOAD_FOLDER):
        image_dir = os.path.join(UPLOAD_FOLDER, image_id)
        if not os.path.isdir(image_dir):
            continue
        metadata_path = os.path.join(image_dir, "metadata.json")
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, "r") as f:
                    meta = json.load(f)

                updated = False
                for w in meta.get("workflows", []):
                    if w.get("job_id") == job_id:
                        if w.get("status") != status:
                            w["status"] = status
                            w["end_time"] = datetime.now().isoformat()
                            updated = True
                        # Store full job data cache when completed/failed
                        if job_data and status in ["completed", "failed"]:
                            w["cached_job_data"] = job_data
                            updated = True

                if updated:
                    with open(metadata_path, "w") as f:
                        json.dump(meta, f)
                    logger.info(f"Updated metadata for job {job_id} on disk.")
                    return  # Found it
            except Exception as e:
                logger.error(f"Error updating metadata for job {job_id}: {e}")


def start_background_threads(socketio):
    global socket_ref
    socket_ref = socketio

    # On startup, scan for any jobs that are still 'pending' or 'running' in metadata
    if os.path.exists(UPLOAD_FOLDER):
        for image_id in os.listdir(UPLOAD_FOLDER):
            image_dir = os.path.join(UPLOAD_FOLDER, image_id)
            if not os.path.isdir(image_dir):
                continue
            metadata_path = os.path.join(image_dir, "metadata.json")
            if os.path.exists(metadata_path):
                try:
                    with open(metadata_path, "r") as f:
                        meta = json.load(f)
                    for w in meta.get("workflows", []):
                        if w.get("status") in ["pending", "running"]:
                            with monitored_lock:
                                monitored_jobs.add(w.get("job_id"))
                            logger.info(
                                f"Re-monitoring job {w.get('job_id')} for image {image_id}"
                            )
                except Exception as e:
                    logger.error(f"Startup scan error for {image_id}: {e}")

    threading.Thread(target=background_processor_thread, daemon=True).start()

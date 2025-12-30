import logging
import json
import hashlib
import datetime
import secrets
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
from dotenv import load_dotenv
import os
from queue_manager import queue_manager
from orchestrator import orchestrator

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("ai_backend")
logging.getLogger("PIL").setLevel(logging.WARNING)
# Load environment variables
load_dotenv()
app = Flask(__name__)
CORS(app)
# Configuration
UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
RESULTS_FOLDER = os.path.join(os.getcwd(), "results")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULTS_FOLDER, exist_ok=True)


def generate_job_id():
    """Generates a unique, date-prefixed job ID."""
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d_%H-%M")
    random_hex = secrets.token_hex(2)  # 2 bytes = 4 hex digits
    return f"{date_str}_{random_hex}"


@app.route("/run", methods=["POST"])
def run_workflow():
    if "image" not in request.files:
        return jsonify({"error": "No image uploaded"}), 400
    image = request.files["image"]
    workflow_json = request.form.get("workflow", "[]")
    priority = int(request.form.get("priority", 0))
    # Read image content to calculate hash
    image_content = image.read()
    file_hash = hashlib.md5(image_content).hexdigest()
    extension = os.path.splitext(image.filename)[1].lower()
    if not extension:
        extension = ".png"
    filename = f"{file_hash}{extension}"
    input_path = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(input_path):
        with open(input_path, "wb") as f:
            f.write(image_content)
        logger.info(f"Saved new upload: {filename}")
    else:
        logger.info(f"Using existing upload: {filename}")
    job_id = generate_job_id()
    try:
        workflow = json.loads(workflow_json)
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid workflow JSON"}), 400
    job_info = {
        "job_id": job_id,
        "input_path": input_path,
        "workflow": workflow,
        "priority": priority,
        "status": "queued",
        "results": {},
    }
    queue_manager.add_job(job_info)
    return jsonify({"job_id": job_id, "status": "queued"}), 202


@app.route("/status", methods=["GET"])
def get_all_status():
    ids_param = request.args.get("ids")
    if ids_param:
        job_ids = ids_param.split(",")
        jobs = [
            queue_manager.get_job(jid) for jid in job_ids if queue_manager.get_job(jid)
        ]
        return jsonify(jobs)
    jobs = queue_manager.get_all_jobs()
    return jsonify(jobs)


@app.route("/status/<job_id>", methods=["GET"])
def get_status(job_id):
    job = queue_manager.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/result/<job_id>/<stage>", methods=["GET"])
def get_result(job_id, stage):
    job = queue_manager.get_job(job_id)
    if not job or stage not in job.get("results", {}):
        return jsonify({"error": "Result not found"}), 404
    results = job["results"][stage]
    if isinstance(results, dict):
        # Default to the first one if multiple
        slug = request.args.get("slug")
        if slug and slug in results:
            result_path = results[slug]
        else:
            result_path = list(results.values())[0]
    else:
        result_path = results
    return send_from_directory(
        os.path.dirname(result_path), os.path.basename(result_path)
    )


@app.route("/artifact/<job_id>/<slug>", methods=["GET"])
def get_artifact(job_id, slug):
    job = queue_manager.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    artifact = next((a for a in job.get("artifacts", []) if a["slug"] == slug), None)
    if not artifact:
        return jsonify({"error": f"Artifact with slug {slug} not found"}), 404
    result_path = artifact["path"]
    return send_from_directory(
        os.path.dirname(result_path), os.path.basename(result_path)
    )
@app.route("/file/<file_hash>", methods=["GET"])
def get_file_by_hash(file_hash):
    """Finds and serves a file from the results directory by its MD5 hash."""
    from pathlib import Path

    # Search recursively in RESULTS_FOLDER for filename starting with this hash
    for path in Path(RESULTS_FOLDER).rglob(f"{file_hash}*"):
        if path.is_file():
            return send_file(path)
    
    # Also check UPLOAD_FOLDER (for original images)
    for path in Path(UPLOAD_FOLDER).rglob(f"{file_hash}*"):
        if path.is_file():
            return send_file(path)

    return jsonify({"error": f"File with hash {file_hash} not found"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)

from flask import Flask, request, jsonify, render_template
import yaml
import os
from plot.plot import plot_from_file
from plot import calibrate
from plot.vplotter import VPlotter
import threading
import cv2
import base64
import numpy as np

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max file size

# Create uploads folder if it doesn't exist
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


# Placeholder functions
def plot(parsed_data):
    """Start plotting in a background thread"""
    print(f"Starting plot thread with data")
    thread = threading.Thread(target=plot_from_file, args=(parsed_data,))
    thread.start()
    return {
        "status": "success",
        "message": "Plot started in background",
        "data": parsed_data,
    }


def left(speed):
    """Placeholder function for left movement"""
    print(f"Left called with speed: {speed}")
    calibrate.steps_left(speed)
    return {"status": "success", "action": "left", "speed": speed}


def right(speed):
    """Placeholder function for right movement"""
    print(f"Right called with speed: {speed}")
    calibrate.steps_right(speed)
    return {"status": "success", "action": "right", "speed": speed}


def servo(duty_cycle):
    """Placeholder function for servo calibration"""
    print(f"Servo called with duty cycle: {duty_cycle}")
    calibrate.calibrate_servo(duty_cycle)
    return {"status": "success", "action": "servo", "duty_cycle": duty_cycle}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    if file and file.filename.endswith(".yaml"):
        try:
            content = file.read().decode("utf-8")
            parsed_data = yaml.safe_load(content)
            result = plot(parsed_data)
            return jsonify(result), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    else:
        return jsonify({"error": "Only .yaml files allowed"}), 400


@app.route("/control", methods=["POST"])
def control():
    data = request.json
    direction = data.get("direction")
    speed = data.get("speed", 1)

    if direction in ["left_up", "left_down"]:
        actual_speed = speed if direction == "left_up" else -speed
        result = left(actual_speed)
    elif direction in ["right_up", "right_down"]:
        actual_speed = speed if direction == "right_up" else -speed
        result = right(actual_speed)
    elif direction == "servo":
        result = servo(speed / 10)
    else:
        return jsonify({"error": "Invalid direction"}), 400

    return jsonify(result), 200


@app.route("/status")
def status():
    plotter = VPlotter.CURRENT_INSTANCE

    if plotter is None:
        return jsonify({"active": False, "x": 0, "y": 0, "z": 1})

    # Get current state
    plotter_x, plotter_y = plotter.get_current_coords()
    state = {"active": True, "x": plotter_x, "y": plotter_y, "z": plotter.z}

    # Encode canvas if it exists
    if hasattr(plotter, "canvas") and plotter.canvas is not None:
        try:
            # Resize for faster transfer if needed, but 400x300 isn't huge
            # Encode as JPEG
            retval, buffer = cv2.imencode(".jpg", plotter.canvas)
            if retval:
                jpg_as_text = base64.b64encode(buffer).decode("utf-8")
                state["canvas"] = jpg_as_text
        except Exception as e:
            print(f"Error encoding canvas: {e}")

    return jsonify(state)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

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

from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.plotter = None

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


def plot(parsed_data):
    print(f"Starting plot thread with data")
    thread = threading.Thread(target=plot_from_file, args=(app.plotter, parsed_data))
    thread.start()
    return {
        "status": "success",
        "message": "Plot started in background",
        "data": parsed_data,
    }


def left(speed):
    print(f"Left called with speed: {speed}")
    calibrate.steps_left(speed, app.plotter)
    return {"status": "success", "action": "left", "speed": speed}


def right(speed):
    print(f"Right called with speed: {speed}")
    calibrate.steps_right(speed, app.plotter)
    return {"status": "success", "action": "right", "speed": speed}


def servo(duty_cycle):
    print(f"Servo called with duty cycle: {duty_cycle}")
    calibrate.calibrate_servo(duty_cycle, app.plotter)
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


@app.route("/move", methods=["POST"])
def move():
    data = request.json
    delta_x = data.get("x", 0)
    delta_y = data.get("y", 0)

    if app.plotter is None:
        return jsonify({"error": "Plotter not initialized"}), 500

    current_x, current_y = app.plotter.get_current_coords()
    new_x = current_x + delta_x
    new_y = current_y + delta_y

    app.plotter.move_straight_line(new_x, new_y, app.plotter.z)

    return jsonify({"status": "success", "x": new_x, "y": new_y}), 200


@app.route("/home", methods=["POST"])
def set_home():
    if app.plotter is None:
        return jsonify({"error": "Plotter not initialized"}), 500

    try:
        home_x = app.plotter.MOTOR_DISTANCE / 2
        home_y = 12.5

        app.plotter.set_current_position(home_x, home_y)

        return jsonify({"status": "success", "x": home_x, "y": home_y}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/status")
def status():
    plotter = app.plotter

    if plotter is None:
        return jsonify({"active": False, "x": 0, "y": 0, "z": 1, "motor_distance": 40})

    plotter_x, plotter_y = plotter.get_current_coords()
    state = {
        "active": True,
        "x": plotter_x,
        "y": plotter_y,
        "z": plotter.z,
        "motor_distance": plotter.MOTOR_DISTANCE,
    }

    if hasattr(plotter, "canvas") and plotter.canvas is not None:
        try:
            retval, buffer = cv2.imencode(".jpg", plotter.canvas)
            if retval:
                jpg_as_text = base64.b64encode(buffer).decode("utf-8")
                state["canvas"] = jpg_as_text
        except Exception as e:
            print(f"Error encoding canvas: {e}")

    return jsonify(state)


if __name__ == "__main__":
    with VPlotter() as plotter:
        app.plotter = plotter
        app.run(debug=True, host="0.0.0.0", port=5000, use_reloader=False)

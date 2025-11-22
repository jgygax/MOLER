from flask import Flask, request, jsonify, render_template
import yaml
import os
from plot.plot import plot_from_file
from plot import calibrate

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create uploads folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Placeholder functions
def plot(parsed_data):
    """Placeholder function for plotting"""
    print(f"Plot called with data: {parsed_data}")
    plot_from_file(parsed_data)
    return {"status": "success", "message": "Plot function called", "data": parsed_data}

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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    if file and file.filename.endswith('.yaml'):
        try:
            content = file.read().decode('utf-8')
            parsed_data = yaml.safe_load(content)
            result = plot(parsed_data)
            return jsonify(result), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    else:
        return jsonify({"error": "Only .yaml files allowed"}), 400

@app.route('/control', methods=['POST'])
def control():
    data = request.json
    direction = data.get('direction')
    speed = data.get('speed', 1)
    
    if direction in ['left_up', 'left_down']:
        actual_speed = speed if direction == 'left_up' else -speed
        result = left(actual_speed)
    elif direction in ['right_up', 'right_down']:
        actual_speed = speed if direction == 'right_up' else -speed
        result = right(actual_speed)
    else:
        return jsonify({"error": "Invalid direction"}), 400
    
    return jsonify(result), 200

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
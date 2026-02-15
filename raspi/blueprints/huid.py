from flask import Blueprint, render_template, jsonify, request, current_app
import os
import uuid
from blueprints.processor import (
    upload_image as processor_upload,
    run_workflow,
    enqueue_to_plotter
)

huid_bp = Blueprint("huid", __name__)
socket_ref = None

def start_background_threads(socketio_instance):
    global socket_ref
    socket_ref = socketio_instance

@huid_bp.route("/huid")
def index():
    return render_template("huid.html")

@huid_bp.route("/huid/upload", methods=["POST"])
def upload_image():
    """Proxy to processor upload endpoint"""
    return processor_upload()

@huid_bp.route("/huid/process", methods=["POST"])
def process_image():
    """Proxy to processor workflow endpoint"""
    return run_workflow()

@huid_bp.route("/huid/plot", methods=["POST"])
def plot_image():
    """Proxy to processor plot endpoint"""
    return enqueue_to_plotter()
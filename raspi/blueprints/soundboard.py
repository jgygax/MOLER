"""
Soundboard Module - Plays sound effects with configurable intervals.
Handles both manual playback via web interface and automatic background playback.
"""

import os
import logging
import threading
import subprocess
import random
import time
from pathlib import Path
from collections import deque
from flask import Blueprint, render_template, jsonify, request, send_from_directory
import extensions

logger = logging.getLogger(__name__)
soundboard_bp = Blueprint("soundboard", __name__)

# Path to sound effects directory
SFX_DIR = Path(__file__).parent.parent / "sfx"

# Default SFX folder for automatic playback
DEFAULT_SFX_FOLDER = "r2d2"

# Variance factor for intervals (std dev as fraction of mean)
INTERVAL_VARIANCE = 0.3

# Track manual playback state
manual_playback_lock = threading.Lock()
is_manual_playing = False

# Track active playback process for cancellation
active_playback_lock = threading.Lock()
active_playback_processes = []  # List of (ffmpeg_proc, aplay_proc) tuples

# Get the original user when running with sudo
ORIGINAL_USER = 1000 # "pi"  # os.environ.get('SUDO_USER')
ORIGINAL_UID = 1000 # "pi"  # os.environ.get('SUDO_UID')
ORIGINAL_GID = 1000 # "pi"  # os.environ.get('SUDO_GID')


def get_sfx_folders():
    """Get all folders in the sfx directory and their contents."""
    folders = []

    if not SFX_DIR.exists():
        logger.warning(f"SFX directory not found: {SFX_DIR}")
        return folders

    for folder in sorted(SFX_DIR.iterdir()):
        if (
            folder.is_dir()
            and not folder.name.startswith("_")
            and folder.name != "scripts"
        ):
            # Get all audio files in this folder
            files = []
            for f in sorted(folder.iterdir()):
                if f.suffix.lower() in (".mp3", ".wav", ".ogg", ".m4a", ".flac"):
                    files.append(
                        {
                            "name": f.stem,
                            "filename": f.name,
                            "path": str(f.relative_to(SFX_DIR.parent)),
                        }
                    )

            if files:  # Only add folders with audio files
                folders.append({"name": folder.name, "files": files})

    return folders


@soundboard_bp.route("/soundboard")
def index():
    """Render the soundboard page."""
    folders = get_sfx_folders()
    return render_template("soundboard.html", folders=folders)


@soundboard_bp.route("/soundboard/api/folders")
def get_folders_api():
    """API endpoint to get all folders and their sound files."""
    folders = get_sfx_folders()
    return jsonify({"folders": folders})


@soundboard_bp.route("/soundboard/api/audio/<path:filepath>")
def serve_audio(filepath):
    """Serve audio files for local browser playback."""
    # Validate the filepath is within sfx directory
    try:
        full_path = (SFX_DIR.parent / filepath).resolve()
        sfx_root = SFX_DIR.resolve()
        if not str(full_path).startswith(str(sfx_root)):
            return jsonify({"error": "Invalid filepath"}), 400
    except Exception:
        return jsonify({"error": "Invalid filepath"}), 400
    
    # Get the directory and filename
    directory = full_path.parent
    filename = full_path.name
    
    return send_from_directory(directory, filename)


@soundboard_bp.route("/soundboard/api/play", methods=["POST"])
def play_sound():
    """API endpoint to play a sound file."""
    global is_manual_playing

    data = request.json
    if not data or "filepath" not in data:
        return jsonify({"error": "No filepath provided"}), 400

    filepath = data["filepath"]

    # Validate path - ensure it's within the sfx directory
    full_path = Path(__file__).parent.parent / filepath
    try:
        full_path = full_path.resolve()
        sfx_root = SFX_DIR.resolve()
        if not str(full_path).startswith(str(sfx_root)):
            return jsonify({"error": "Invalid filepath"}), 400
    except Exception:
        return jsonify({"error": "Invalid filepath"}), 400

    if not full_path.exists():
        return jsonify({"error": "File not found"}), 404

    # Pause automatic background playback
    with manual_playback_lock:
        is_manual_playing = True

    # Play the file in a background thread
    def play_and_resume():
        global is_manual_playing
        try:
            _play_audio_file(full_path)
        finally:
            # Resume automatic playback after sound finishes
            with manual_playback_lock:
                is_manual_playing = False
            logger.info("Manual playback finished, resumed automatic playback")

    thread = threading.Thread(target=play_and_resume, daemon=True)
    thread.start()

    return jsonify({"status": "playing", "file": full_path.name})


def _play_audio_file(filepath):
    """Play an audio file using ffmpeg/aplay as the original user."""
    import shutil

    global active_playback_processes

    try:
        logger.info(f"Attempting to play: {filepath.name}")

        ffmpeg_path = shutil.which("ffmpeg")
        aplay_path = shutil.which("aplay")

        if not ffmpeg_path:
            logger.error("ffmpeg not found")
            return False

        if not aplay_path:
            logger.error("aplay not found")
            return False

        # Prepare environment for the original user
        env = os.environ.copy()

        # If running as sudo, get the original user's environment
        if ORIGINAL_USER:
            # Get the original user's XDG_RUNTIME_DIR and PULSE environment
            user_runtime_dir = f"/run/user/{ORIGINAL_UID}" if ORIGINAL_UID else None

            if user_runtime_dir and os.path.exists(user_runtime_dir):
                env["XDG_RUNTIME_DIR"] = user_runtime_dir
                # Set PulseAudio socket path
                pulse_socket = f"{user_runtime_dir}/pulse/native"
                if os.path.exists(pulse_socket):
                    env["PULSE_SERVER"] = f"unix:{pulse_socket}"

            logger.debug(f"Playing as user: {ORIGINAL_USER} (UID: {ORIGINAL_UID})")

        # Build ffmpeg command
        ffmpeg_cmd = [
            ffmpeg_path,
            "-i",
            str(filepath),
            "-f",
            "wav",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-",
        ]

        # Build aplay command
        aplay_cmd = [aplay_path, "-"]

        logger.debug(f"Running: {' '.join(ffmpeg_cmd)} | {' '.join(aplay_cmd)}")

        # Function to demote process to original user
        def demote_process():
            """Demote the process to run as the original user."""
            if ORIGINAL_UID and ORIGINAL_GID:
                try:
                    # Set group first, then user
                    os.setgid(int(ORIGINAL_GID))
                    os.setuid(int(ORIGINAL_UID))
                except Exception as e:
                    logger.warning(f"Could not demote process: {e}")

        # Start ffmpeg (as original user if running as sudo)
        ffmpeg_proc = subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            preexec_fn=demote_process if ORIGINAL_UID else None,
        )

        # Start aplay (as original user if running as sudo)
        aplay_proc = subprocess.Popen(
            aplay_cmd,
            stdin=ffmpeg_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            preexec_fn=demote_process if ORIGINAL_UID else None,
        )

        # Close ffmpeg's stdout in the parent process
        ffmpeg_proc.stdout.close()

        # Track active processes for cancellation
        with active_playback_lock:
            active_playback_processes.append((ffmpeg_proc, aplay_proc))

        # Wait for aplay to finish (with generous timeout for slow systems)
        aplay_returncode = aplay_proc.wait(timeout=120)  # 2 minutes
        ffmpeg_returncode = ffmpeg_proc.wait(timeout=120)  # 2 minutes

        # Remove from active processes when done
        with active_playback_lock:
            try:
                active_playback_processes.remove((ffmpeg_proc, aplay_proc))
            except ValueError:
                pass  # Already removed by stop function

        # Check for errors (but ignore if we cancelled it)
        if aplay_returncode != 0 and aplay_returncode != -15:  # -15 is SIGTERM
            stderr = (
                aplay_proc.stderr.read().decode("utf-8", errors="ignore")
                if aplay_proc.stderr
                else "No error"
            )
            logger.error(f"aplay failed with code {aplay_returncode}: {stderr}")
            return False

        if ffmpeg_returncode != 0 and ffmpeg_returncode != -15:
            stderr = (
                ffmpeg_proc.stderr.read().decode("utf-8", errors="ignore")
                if ffmpeg_proc.stderr
                else "No error"
            )
            logger.error(f"ffmpeg failed with code {ffmpeg_returncode}: {stderr}")
            return False

        logger.info(f"Finished playing: {filepath.name}")
        return True

    except Exception as e:
        logger.error(f"Error playing audio file {filepath}: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return False


def is_manual_playback_active():
    """Check if manual playback is currently active."""
    with manual_playback_lock:
        return is_manual_playing


def stop_current_playback():
    """Stop any currently playing audio."""
    global active_playback_processes

    with active_playback_lock:
        processes_to_stop = active_playback_processes.copy()
        active_playback_processes.clear()

    stopped = False
    for ffmpeg_proc, aplay_proc in processes_to_stop:
        try:
            # Kill aplay first (child), then ffmpeg (parent)
            if aplay_proc.poll() is None:
                aplay_proc.terminate()
                try:
                    aplay_proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    aplay_proc.kill()
                stopped = True

            if ffmpeg_proc.poll() is None:
                ffmpeg_proc.terminate()
                try:
                    ffmpeg_proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    ffmpeg_proc.kill()
                stopped = True
        except Exception as e:
            logger.error(f"Error stopping playback: {e}")

    if stopped:
        logger.info("Playback stopped by user")

    return stopped


@soundboard_bp.route("/soundboard/api/stop", methods=["POST"])
def stop_sound():
    """API endpoint to stop the currently playing sound."""
    stopped = stop_current_playback()

    # Also clear the manual playback state
    global is_manual_playing
    with manual_playback_lock:
        is_manual_playing = False

    return jsonify(
        {
            "status": "stopped" if stopped else "no_playback",
            "message": "Playback stopped" if stopped else "No audio was playing",
        }
    )


class SFXPlayer:
    """
    Background thread that plays random sound effects.

    Features:
    - Different intervals for idle vs plotting states
    - Random selection avoiding recent repeats
    - Configurable via settings
    """

    def __init__(self):
        self.running = False
        self.thread = None
        self.stop_event = threading.Event()
        self.recent_files = deque(maxlen=10)  # Track last 10 played files
        self.available_files = []
        self._scan_audio_files()

    def _scan_audio_files(self):
        """Scan for available audio files in the default SFX directory."""
        sfx_path = SFX_DIR / DEFAULT_SFX_FOLDER
        if sfx_path.exists():
            self.available_files = [
                f
                for f in sfx_path.iterdir()
                if f.suffix.lower() in (".mp3", ".wav", ".ogg", ".m4a")
            ]
            logger.info(f"Found {len(self.available_files)} audio files in {sfx_path}")
        else:
            logger.warning(f"SFX directory not found: {sfx_path}")
            self.available_files = []

    def _select_random_file(self):
        """
        Select a random audio file that hasn't been played in the last 10 plays.
        Falls back to any file if all have been played recently.
        """
        if not self.available_files:
            self._scan_audio_files()

        if not self.available_files:
            logger.warning("No audio files available")
            return None

        # Filter out recently played files
        recent_set = set(str(f) for f in self.recent_files)
        candidates = [f for f in self.available_files if str(f) not in recent_set]

        # If all files have been played recently, use all files
        if not candidates:
            candidates = self.available_files

        # Select random file
        selected = random.choice(candidates)
        self.recent_files.append(selected)

        return selected

    def _calculate_next_interval(self, base_interval):
        """
        Calculate next interval with variance.
        Uses a log-normal distribution which gives positive values
        with the specified mean and variance.
        """
        import numpy as np

        # For log-normal distribution with mean=mu and variance=sigma^2:
        # We want E[X] = base_interval and Var(X) = (base_interval * INTERVAL_VARIANCE)^2
        import numpy as np

        sigma = np.sqrt(np.log(1 + INTERVAL_VARIANCE**2))
        mu = np.log(base_interval) - sigma**2 / 2

        interval = np.random.lognormal(mu, sigma)

        # Ensure minimum interval of 1 second
        return max(1.0, interval)

    def _player_loop(self):
        """Main player loop running in background thread."""
        logger.info("SFX Player loop started")

        while not self.stop_event.is_set():
            try:
                # Check if audio is enabled
                if not extensions.audio_settings.get("enabled", True):
                    time.sleep(1)
                    continue

                # Check if manual playback is active
                if is_manual_playback_active():
                    logger.debug("Manual playback active, skipping automatic sound")
                    time.sleep(1)
                    continue

                # Determine current mode and interval
                if extensions.is_processing_job:
                    # Plotting mode
                    base_interval = extensions.audio_settings.get(
                        "plotting_frequency", 10
                    )
                else:
                    # Idle mode
                    base_interval = extensions.audio_settings.get("idle_frequency", 30)

                # Calculate interval with variance
                interval = self._calculate_next_interval(base_interval)

                logger.debug(
                    f"Waiting {interval:.1f}s before next sound (base: {base_interval}s)"
                )

                # Wait for the interval (check stop_event periodically)
                wait_start = time.time()
                while time.time() - wait_start < interval:
                    if self.stop_event.is_set():
                        break
                    time.sleep(0.5)

                if self.stop_event.is_set():
                    break

                # Check again if still enabled
                if not extensions.audio_settings.get("enabled", True):
                    continue

                # Check again if manual playback is active before playing
                if is_manual_playback_active():
                    logger.debug("Manual playback active, skipping automatic sound")
                    continue

                # Select and play a random file
                audio_file = self._select_random_file()
                if audio_file:
                    logger.info(f"Playing sound effect: {audio_file.name}")
                    _play_audio_file(audio_file)

            except Exception as e:
                logger.error(f"Error in SFX player loop: {e}")
                time.sleep(5)  # Wait a bit before retrying

        logger.info("SFX Player loop stopped")

    def start(self):
        """Start the SFX player in a background thread."""
        if self.running:
            logger.warning("SFX Player already running")
            return

        self.running = True
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._player_loop, daemon=True)
        self.thread.start()
        logger.info("SFX Player started")

    def stop(self):
        """Stop the SFX player."""
        if not self.running:
            return

        self.stop_event.set()
        self.thread.join(timeout=5)
        self.running = False
        logger.info("SFX Player stopped")

    def is_running(self):
        """Check if the player is running."""
        return self.running and self.thread and self.thread.is_alive()


# Global player instance
_player_instance = None


def init_sfx_player():
    """Initialize and start the SFX player."""
    global _player_instance

    if _player_instance is None:
        _player_instance = SFXPlayer()

    if not _player_instance.is_running():
        _player_instance.start()

    # Store reference in extensions
    extensions.sfx_player = _player_instance

    return _player_instance


def stop_sfx_player():
    """Stop the SFX player."""
    global _player_instance

    if _player_instance:
        _player_instance.stop()
        _player_instance = None
        extensions.sfx_player = None

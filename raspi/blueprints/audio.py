import os
import logging
import threading
import subprocess
import time
import shutil
from pathlib import Path
from flask import Blueprint, request
from flask_socketio import Namespace, emit

logger = logging.getLogger(__name__)
audio_bp = Blueprint("audio", __name__)

# Audio configuration
SAMPLE_RATE = 16000  # 16kHz mono - good for voice
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit
CHUNK_DURATION_MS = 100  # 100ms chunks
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)
CHUNK_BYTES = CHUNK_SAMPLES * SAMPLE_WIDTH * CHANNELS

# Check if running on real Pi (has audio hardware) or mock mode
# Mock mode: Save to file instead of playing
IS_MOCK_MODE = os.getenv("AUDIO_MOCK_MODE", "auto").lower()
if IS_MOCK_MODE == "auto":
    # Auto-detect: if no ALSA devices available, use mock mode
    IS_MOCK_MODE = not os.path.exists("/proc/asound/cards") or os.path.getsize("/proc/asound/cards") == 0
else:
    IS_MOCK_MODE = IS_MOCK_MODE in ("true", "1", "yes")

# Mock audio output folder
AUDIO_MOCK_FOLDER = os.path.join(os.getcwd(), "uploads", "audio_mock")
os.makedirs(AUDIO_MOCK_FOLDER, exist_ok=True)

# Get the original user when running with sudo (same as soundboard.py)
ORIGINAL_USER = os.environ.get('SUDO_USER')
ORIGINAL_UID = os.environ.get('SUDO_UID')
ORIGINAL_GID = os.environ.get('SUDO_GID')

# Track active audio sessions
active_sessions = {}
sessions_lock = threading.Lock()


def _get_pulse_env():
    """Get environment variables for PulseAudio connection when running as root."""
    env = os.environ.copy()
    
    if ORIGINAL_UID:
        # Running as sudo, set up original user's PulseAudio environment
        user_runtime_dir = f"/run/user/{ORIGINAL_UID}"
        
        if os.path.exists(user_runtime_dir):
            env['XDG_RUNTIME_DIR'] = user_runtime_dir
            # Set PulseAudio socket path
            pulse_socket = f"{user_runtime_dir}/pulse/native"
            if os.path.exists(pulse_socket):
                env['PULSE_SERVER'] = f"unix:{pulse_socket}"
            logger.debug(f"Using PulseAudio for user: {ORIGINAL_USER} (UID: {ORIGINAL_UID})")
    
    return env


def _demote_process():
    """Demote the process to run as the original user (same as soundboard.py)."""
    if ORIGINAL_UID and ORIGINAL_GID:
        try:
            # Set group first, then user
            os.setgid(int(ORIGINAL_GID))
            os.setuid(int(ORIGINAL_UID))
        except Exception as e:
            logger.warning(f"Could not demote process: {e}")


def calculate_dalek_params(intensity):
    """
    Calculate Dalek voice effect parameters based on intensity (0-100).
    
    Uses the formula: value = base + (intensity/50)^1.5 * (max - base)
    
    Returns dict with:
        - bits: bit depth for acrusher (1-16)
        - mix: mix ratio for acrusher (0-1.0)
        - tremolo_depth: tremolo depth (0-1.0)
        - eq_gain1: first EQ gain in dB
        - eq_gain2: second EQ gain in dB
        - hp_freq: highpass frequency in Hz
        - lp_freq: lowpass frequency in Hz
        - vibrato_depth: vibrato depth (0-0.8, only at 60%+)
    """
    # Clamp intensity to 0-100
    intensity = max(0, min(100, intensity))
    
    # Calculate curve factor: (intensity/50)^1.5
    if intensity == 0:
        curve = 0
    else:
        curve = (intensity / 50) ** 1.5
    
    # Parameter ranges
    params = {
        'bits': int(16 - curve * 15),  # 16 -> 1
        'mix': min(1.0, curve * 0.5),  # 0 -> 1.0
        'tremolo_depth': min(1.0, curve),  # 0 -> 1.0
        'eq_gain1': int(curve * 20),  # 0 -> +20dB
        'eq_gain2': int(curve * 24),  # 0 -> +24dB
        'hp_freq': int(20 + curve * 200),  # 20 -> 220Hz
        'lp_freq': int(20000 - curve * 12000),  # 20000 -> 8000Hz
        'vibrato_depth': 0.8 if intensity >= 60 else 0,
    }
    
    # Clamp values to valid ranges
    params['bits'] = max(1, min(16, params['bits']))
    params['hp_freq'] = max(20, min(1000, params['hp_freq']))
    params['lp_freq'] = max(1000, min(20000, params['lp_freq']))  # Prevent negative values!
    
    return params


def build_dalek_filter_chain(intensity):
    """
    Build FFmpeg audio filter chain for Dalek voice effect.
    
    Chain order: Pitch(+12st) -> Normalize -> Distort -> Filter -> EQ -> RingMod
    
    Args:
        intensity: 0-100 effect intensity
    
    Returns:
        FFmpeg filter string
    """
    params = calculate_dalek_params(intensity)
    
    filters = []
    
    # 1. Pitch shift +12 semitones (one octave up) with formant preservation
    filters.append("rubberband=pitch=2:formant=preserved")
    
    # 2. Normalize (loudnorm)
    filters.append("loudnorm=I=-12:TP=-3:LRA=11")
    
    # 3. Distortion (acrusher) - only if intensity > 0
    if intensity > 0:
        filters.append(f"acrusher=bits={params['bits']}:mix={params['mix']:.2f}:mode=log")
    
    # 4. Filters (highpass/lowpass)
    filters.append(f"highpass=f={params['hp_freq']}")
    filters.append(f"lowpass=f={params['lp_freq']}")
    
    # 5. EQ (two bands to boost Dalek character)
    if params['eq_gain1'] > 0:
        filters.append(f"equalizer=f=1500:width_type=o:width=2:g={params['eq_gain1']}")
    if params['eq_gain2'] > 0:
        filters.append(f"equalizer=f=2500:width_type=o:width=1.5:g={params['eq_gain2']}")
    
    # 6. Ring modulator (tremolo creates the classic Dalek ring mod effect)
    if params['tremolo_depth'] > 0:
        # Frequency varies slightly with intensity (35-40Hz)
        tremolo_freq = 35 + (intensity / 100) * 5
        filters.append(f"tremolo=f={tremolo_freq:.1f}:d={params['tremolo_depth']:.2f}")
    
    # 7. Vibrato (only at 60%+ intensity)
    if params['vibrato_depth'] > 0:
        filters.append(f"vibrato=f=8:d={params['vibrato_depth']:.2f}")
    
    return ",".join(filters)


class AudioSession:
    """Manages an audio streaming session with Dalek effect processing"""
    
    def __init__(self, session_id, intensity=50):
        self.session_id = session_id
        self.intensity = intensity
        self.ffmpeg_proc = None
        self.aplay_proc = None
        self.is_active = False
        self.input_sample_rate = 44100  # Default, will be updated on first chunk
        self.lock = threading.Lock()
        
    def start(self):
        """Start the audio processing pipeline"""
        with self.lock:
            if self.is_active:
                return
            
            # Don't start FFmpeg yet - wait for first chunk to know the sample rate
            self.is_active = True
            logger.info(f"Audio session {self.session_id} started with Dalek intensity: {self.intensity}%")
    
    def _get_current_intensity(self):
        """Get current Dalek intensity from extensions (allows dynamic updates)"""
        try:
            import extensions
            return extensions.audio_settings.get("dalek_intensity", 50)
        except:
            return self.intensity
    
    def _start_pipeline(self, input_sample_rate):
        """Start the FFmpeg -> aplay pipeline"""
        ffmpeg_path = shutil.which("ffmpeg")
        aplay_path = shutil.which("aplay")
        
        if not ffmpeg_path:
            logger.error("ffmpeg not found")
            return False
        
        if not aplay_path:
            logger.error("aplay not found")
            return False
        
        # Get current intensity (allows dynamic updates)
        intensity = self._get_current_intensity()
        
        # Build filter chain
        filter_chain = build_dalek_filter_chain(intensity)
        
        # FFmpeg command: raw PCM input -> filter chain -> raw PCM output
        ffmpeg_cmd = [
            ffmpeg_path,
            "-f", "s16le",
            "-ar", str(input_sample_rate),
            "-ac", str(CHANNELS),
            "-i", "-",  # Input from stdin
            "-af", filter_chain,
            "-f", "s16le",  # Output raw PCM
            "-ar", str(SAMPLE_RATE),
            "-ac", str(CHANNELS),
            "-"  # Output to stdout
        ]
        
        # aplay command to output to speakers
        aplay_cmd = [
            aplay_path,
            "-f", "S16_LE",
            "-r", str(SAMPLE_RATE),
            "-c", str(CHANNELS)
        ]
        
        logger.info(f"Starting audio pipeline (input: {input_sample_rate}Hz, intensity: {intensity}%)")
        logger.info(f"FFmpeg filter chain: {filter_chain}")
        
        # Prepare environment for audio access
        env = _get_pulse_env()
        
        try:
            # Start FFmpeg (as original user if running as sudo)
            self.ffmpeg_proc = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                preexec_fn=_demote_process if ORIGINAL_UID else None,
                bufsize=CHUNK_BYTES * 4
            )
            
            # Start aplay (as original user if running as sudo)
            self.aplay_proc = subprocess.Popen(
                aplay_cmd,
                stdin=self.ffmpeg_proc.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env=env,
                preexec_fn=_demote_process if ORIGINAL_UID else None,
                bufsize=CHUNK_BYTES * 4
            )
            
            # Close ffmpeg's stdout in the parent process
            self.ffmpeg_proc.stdout.close()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start audio pipeline: {e}")
            self._stop_pipeline()
            return False
    
    def process_chunk(self, audio_data, input_sample_rate=44100):
        """Process a chunk of audio data"""
        with self.lock:
            if not self.is_active:
                return
            
            # Start pipeline on first chunk with detected sample rate
            if self.ffmpeg_proc is None:
                self.input_sample_rate = input_sample_rate
                if not self._start_pipeline(input_sample_rate):
                    return
            
            if not self.ffmpeg_proc:
                return
            
            try:
                if self.ffmpeg_proc.stdin:
                    self.ffmpeg_proc.stdin.write(audio_data)
                    self.ffmpeg_proc.stdin.flush()
            except (BrokenPipeError, IOError) as e:
                logger.error(f"Audio pipeline broken: {e}")
                self.stop()
    
    def change_intensity(self, new_intensity):
        """Change Dalek intensity (restarts pipeline on next chunk)"""
        with self.lock:
            if self.intensity == new_intensity:
                return
            
            logger.info(f"Changing Dalek intensity from {self.intensity}% to {new_intensity}%")
            self.intensity = new_intensity
            
            # Only restart if pipeline was already running
            if self.ffmpeg_proc is not None:
                # Stop current pipeline
                self._stop_pipeline()
    
    def stop(self):
        """Stop the audio session"""
        with self.lock:
            self._stop_pipeline()
            self.is_active = False
            logger.info(f"Audio session {self.session_id} stopped")
    
    def _stop_pipeline(self):
        """Stop FFmpeg/aplay processes"""
        processes = []
        if self.ffmpeg_proc:
            processes.append(self.ffmpeg_proc)
        if self.aplay_proc:
            processes.append(self.aplay_proc)
        
        for proc in processes:
            try:
                proc.stdin.close()
            except:
                pass
            
            try:
                proc.terminate()
                proc.wait(timeout=1)
            except:
                try:
                    proc.kill()
                except:
                    pass
        
        self.ffmpeg_proc = None
        self.aplay_proc = None


class AudioNamespace(Namespace):
    """SocketIO namespace for audio streaming"""
    
    def on_connect(self):
        """Client connected"""
        session_id = request.sid
        logger.info(f"Audio client connected: {session_id}")
        
        # Get current Dalek intensity
        try:
            import extensions
            intensity = extensions.audio_settings.get("dalek_intensity", 50)
        except:
            intensity = 50
        
        emit("connected", {
            "status": "ok",
            "mock_mode": IS_MOCK_MODE,
            "sample_rate": SAMPLE_RATE,
            "chunk_duration_ms": CHUNK_DURATION_MS,
            "dalek_intensity": intensity,
        })
    
    def on_disconnect(self):
        """Client disconnected"""
        session_id = request.sid
        logger.info(f"Audio client disconnected: {session_id}")
        
        with sessions_lock:
            if session_id in active_sessions:
                active_sessions[session_id].stop()
                del active_sessions[session_id]
    
    def on_start_stream(self, data):
        """Start audio streaming"""
        session_id = request.sid
        
        # Get intensity from data or use default
        intensity = data.get("intensity", 50)
        
        logger.info(f"Starting audio stream for {session_id} with Dalek intensity: {intensity}%")
        
        with sessions_lock:
            # Stop existing session if any
            if session_id in active_sessions:
                active_sessions[session_id].stop()
            
            # Create new session
            session = AudioSession(session_id, intensity)
            session.start()
            active_sessions[session_id] = session
        
        emit("stream_started", {
            "status": "ok",
            "preset": "pitch_up",
            "mock_mode": IS_MOCK_MODE,
        })
    
    def on_stop_stream(self, data):
        """Stop audio streaming"""
        session_id = request.sid
        logger.info(f"Stopping audio stream for {session_id}")
        
        with sessions_lock:
            if session_id in active_sessions:
                active_sessions[session_id].stop()
                del active_sessions[session_id]
        
        emit("stream_stopped", {"status": "ok"})
    
    def on_change_intensity(self, data):
        """Change Dalek intensity"""
        session_id = request.sid
        new_intensity = data.get("intensity", 50)
        
        with sessions_lock:
            if session_id in active_sessions:
                active_sessions[session_id].change_intensity(new_intensity)
        
        emit("intensity_changed", {"status": "ok", "intensity": new_intensity})
    
    def on_audio_chunk(self, data):
        """Receive audio chunk from client"""
        session_id = request.sid
        
        # Data should be base64-encoded PCM audio
        import base64
        audio_data = base64.b64decode(data.get("audio", ""))
        input_sample_rate = data.get("sample_rate", 44100)
        
        with sessions_lock:
            if session_id in active_sessions:
                active_sessions[session_id].process_chunk(audio_data, input_sample_rate)


@audio_bp.route("/audio/intensity", methods=["GET", "POST"])
def intensity_api():
    """API endpoint to get or set Dalek effect intensity"""
    if request.method == "GET":
        try:
            import extensions
            intensity = extensions.audio_settings.get("dalek_intensity", 50)
        except:
            intensity = 50
        return {"intensity": intensity}
    
    elif request.method == "POST":
        data = request.json
        if not data or "intensity" not in data:
            return {"error": "No intensity provided"}, 400
        
        intensity = max(0, min(100, int(data["intensity"])))
        
        # Update settings
        try:
            import extensions
            from settings_storage import save_settings
            extensions.audio_settings["dalek_intensity"] = intensity
            save_settings(audio_settings=extensions.audio_settings)
            logger.info(f"Dalek intensity updated to {intensity}%")
        except Exception as e:
            logger.error(f"Failed to save Dalek intensity: {e}")
        
        return {"status": "ok", "intensity": intensity}


def start_background_threads(socketio_instance):
    """Initialize audio SocketIO namespace"""
    socketio_instance.on_namespace(AudioNamespace("/audio"))
    logger.info(f"Audio namespace registered (mock_mode={IS_MOCK_MODE})")

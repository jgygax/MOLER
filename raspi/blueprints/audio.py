import os
import logging
import threading
import subprocess
import time
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

# Voice effect presets (FFmpeg + SoX filter chains)
VOICE_PRESETS = {
    "pitch_up": {
        "name": "Pitch Up",
        "description": "Pitch shift one octave up",
        "ffmpeg_filters": [
            "aresample=16000",  # Resample to 16kHz
        ],
        "sox_pitch": 1200,  # One octave up (1200 cents)
        "sox_tempo": 1.0,
    },
}

# Track active audio sessions
active_sessions = {}
sessions_lock = threading.Lock()


class AudioSession:
    """Manages an audio streaming session with effect processing"""
    
    def __init__(self, session_id, voice_preset="pitch_up"):
        self.session_id = session_id
        self.voice_preset = voice_preset
        self.ffmpeg_proc = None
        self.mock_file = None
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
            logger.info(f"Audio session {self.session_id} started with preset: {self.voice_preset} (waiting for first chunk to detect sample rate)")
    
    def _start_mock_pipeline(self, preset):
        """Start pipeline that plays to speakers"""
        # Build FFmpeg filter chain - just pass through resampled audio
        ffmpeg_cmd = [
            "ffmpeg",
            "-f", "s16le",
            "-ar", str(self.input_sample_rate),
            "-ac", str(CHANNELS),
            "-i", "-",
            "-af", f"aresample={SAMPLE_RATE}",
            "-f", "s16le",
            "-ar", str(SAMPLE_RATE),
            "-ac", str(CHANNELS),
            "-"
        ]
        
        # SoX for pitch shift
        sox_pitch = preset.get("sox_pitch", 0)
        sox_cmd = [
            "sox",
            "-t", "raw",
            "-r", str(SAMPLE_RATE),
            "-b", "16",
            "-e", "signed",
            "-c", str(CHANNELS),
            "-",
            "-t", "raw",
            "-r", str(SAMPLE_RATE),
            "-b", "16",
            "-e", "signed",
            "-c", str(CHANNELS),
            "-",
            "pitch", str(sox_pitch),
        ]
        
        # Play through default audio output
        aplay_cmd = ["aplay", "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", str(CHANNELS)]
        
        logger.info(f"Starting audio pipeline (input: {self.input_sample_rate}Hz) with pitch shift: {sox_pitch}cents")
        
        # Start FFmpeg
        self.ffmpeg_proc = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=CHUNK_BYTES * 4
        )
        
        # Start SoX
        self.sox_proc = subprocess.Popen(
            sox_cmd,
            stdin=self.ffmpeg_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=CHUNK_BYTES * 4
        )
        
        # Start aplay
        self.aplay_proc = subprocess.Popen(
            aplay_cmd,
            stdin=self.sox_proc.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            bufsize=CHUNK_BYTES * 4
        )
    
    def _start_real_pipeline(self, preset):
        """Start pipeline that plays through audio jack (for Pi)"""
        # Build FFmpeg filter chain with resampling - use only basic filters that are always available
        ffmpeg_filters = [f"aresample={SAMPLE_RATE}"]  # Resample to 16kHz first
        # Add preset filters but skip rnndn if not available
        for f in preset["ffmpeg_filters"]:
            if f != "arnndn":  # Skip RNNoise filter as it may not be available
                ffmpeg_filters.append(f)
        ffmpeg_filter_str = ",".join(ffmpeg_filters)
        
        # FFmpeg command chain:
        # 1. Raw PCM input at browser sample rate
        # 2. Resample to 16kHz + effects
        # 3. SoX for pitch/tempo
        # 4. ALSA output
        
        # Build SoX command for pitch/tempo
        sox_pitch = preset.get("sox_pitch", 0)
        sox_tempo = preset.get("sox_tempo", 1.0)
        
        # Use aplay for ALSA output
        ffmpeg_cmd = [
            "ffmpeg",
            "-f", "s16le",
            "-ar", str(self.input_sample_rate),  # Input sample rate from browser
            "-ac", str(CHANNELS),
            "-i", "-",
            "-af", ffmpeg_filter_str,
            "-f", "s16le",  # Output raw PCM for SoX
            "-ar", str(SAMPLE_RATE),
            "-ac", str(CHANNELS),
            "-"
        ]
        
        sox_cmd = [
            "sox",
            "-t", "raw",
            "-r", str(SAMPLE_RATE),
            "-b", "16",
            "-e", "signed",
            "-c", str(CHANNELS),
            "-",  # Input from stdin
            "-t", "wav",  # Output format
            "-r", str(SAMPLE_RATE),
            "-b", "16",
            "-e", "signed",
            "-c", str(CHANNELS),
            "-",
            "pitch", str(sox_pitch),
            "tempo", str(sox_tempo),
        ]
        
        aplay_cmd = ["aplay", "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", str(CHANNELS)]
        
        logger.info(f"Starting real audio pipeline (input: {self.input_sample_rate}Hz) with preset: {self.voice_preset}")
        
        # Start FFmpeg
        self.ffmpeg_proc = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=CHUNK_BYTES * 4
        )
        
        # Start SoX
        self.sox_proc = subprocess.Popen(
            sox_cmd,
            stdin=self.ffmpeg_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=CHUNK_BYTES * 4
        )
        
        # Start aplay
        self.aplay_proc = subprocess.Popen(
            aplay_cmd,
            stdin=self.sox_proc.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            bufsize=CHUNK_BYTES * 4
        )
    
    def process_chunk(self, audio_data, input_sample_rate=44100):
        """Process a chunk of audio data"""
        with self.lock:
            if not self.is_active:
                return
            
            # Start pipeline on first chunk with detected sample rate
            if self.ffmpeg_proc is None:
                self.input_sample_rate = input_sample_rate
                preset = VOICE_PRESETS.get(self.voice_preset, VOICE_PRESETS["pitch_up"])
                
                if IS_MOCK_MODE:
                    self._start_mock_pipeline(preset)
                else:
                    self._start_real_pipeline(preset)
            
            if not self.ffmpeg_proc:
                return
            
            try:
                if self.ffmpeg_proc and self.ffmpeg_proc.stdin:
                    self.ffmpeg_proc.stdin.write(audio_data)
                    self.ffmpeg_proc.stdin.flush()
            except (BrokenPipeError, IOError) as e:
                logger.error(f"Audio pipeline broken: {e}")
                self.stop()
    
    def change_preset(self, new_preset):
        """Change voice preset (restarts pipeline)"""
        with self.lock:
            if self.voice_preset == new_preset:
                return
            
            logger.info(f"Changing preset from {self.voice_preset} to {new_preset}")
            self.voice_preset = new_preset
            
            # Only restart if pipeline was already running
            if self.ffmpeg_proc is not None:
                # Stop current pipeline
                self._stop_pipeline()
                # Will be restarted on next chunk with new preset
    
    def stop(self):
        """Stop the audio session"""
        with self.lock:
            self._stop_pipeline()
            self.is_active = False
            logger.info(f"Audio session {self.session_id} stopped")
    
    def _stop_pipeline(self):
        """Stop FFmpeg/SoX/aplay processes"""
        processes = []
        if hasattr(self, 'ffmpeg_proc') and self.ffmpeg_proc:
            processes.append(self.ffmpeg_proc)
        if hasattr(self, 'sox_proc') and self.sox_proc:
            processes.append(self.sox_proc)
        if hasattr(self, 'aplay_proc') and self.aplay_proc:
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
        if hasattr(self, 'sox_proc'):
            self.sox_proc = None
        if hasattr(self, 'aplay_proc'):
            self.aplay_proc = None


class AudioNamespace(Namespace):
    """SocketIO namespace for audio streaming"""
    
    def on_connect(self):
        """Client connected"""
        session_id = request.sid
        logger.info(f"Audio client connected: {session_id}")
        emit("connected", {
            "status": "ok",
            "mock_mode": IS_MOCK_MODE,
            "sample_rate": SAMPLE_RATE,
            "chunk_duration_ms": CHUNK_DURATION_MS,
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
        voice_preset = data.get("preset", "pitch_up")
        
        logger.info(f"Starting audio stream for {session_id} with preset: {voice_preset}")
        
        with sessions_lock:
            # Stop existing session if any
            if session_id in active_sessions:
                active_sessions[session_id].stop()
            
            # Create new session
            session = AudioSession(session_id, voice_preset)
            session.start()
            active_sessions[session_id] = session
        
        emit("stream_started", {
            "status": "ok",
            "preset": voice_preset,
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
    
    def on_change_preset(self, data):
        """Change voice preset"""
        session_id = request.sid
        new_preset = data.get("preset", "pitch_up")
        
        with sessions_lock:
            if session_id in active_sessions:
                active_sessions[session_id].change_preset(new_preset)
        
        emit("preset_changed", {"status": "ok", "preset": new_preset})
    
    def on_audio_chunk(self, data):
        """Receive audio chunk from client"""
        session_id = request.sid
        
        # Data should be base64-encoded PCM audio
        import base64
        audio_data = base64.b64decode(data.get("audio", ""))
        input_sample_rate = data.get("sample_rate", 44100)  # Default to 44.1kHz if not specified
        
        with sessions_lock:
            if session_id in active_sessions:
                active_sessions[session_id].process_chunk(audio_data, input_sample_rate)


@audio_bp.route("/audio/presets")
def get_presets():
    """Get available voice presets"""
    return {
        "presets": [
            {"id": k, "name": v["name"], "description": v["description"]}
            for k, v in VOICE_PRESETS.items()
        ]
    }


def start_background_threads(socketio_instance):
    """Initialize audio SocketIO namespace"""
    socketio_instance.on_namespace(AudioNamespace("/audio"))
    logger.info(f"Audio namespace registered (mock_mode={IS_MOCK_MODE})")

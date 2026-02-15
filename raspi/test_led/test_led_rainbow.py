from rpi_ws281x import PixelStrip, Color
import time
import signal
import sys
import colorsys

# Configuration
LED_COUNT = 110       # 21 LEDs
LED_PIN = 12         # GPIO12 (physical pin 32)
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 128  # 0-255
LED_INVERT = False
LED_CHANNEL = 0
DELAY = 0.02         # seconds between updates (50 FPS)
HUE_STEP = 0.005     # how fast the rainbow cycles

strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
strip.begin()

def hsv_to_rgb(h, s, v, mult=0.5):
    """Convert HSV to RGB (0-255 range)"""
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return int(r * 255*mult), int(g * 255*mult), int(b * 255*mult)

def set_pixel(idx, r, g, b):
    strip.setPixelColor(idx, Color(r, g, b))

def all_off():
    for i in range(LED_COUNT):
        strip.setPixelColor(i, Color(0, 0, 0))
    strip.show()

# Graceful exit on SIGINT/SIGTERM
def handle_exit(signum, frame):
    all_off()
    sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

# Main rainbow cycle loop
hue_offset = 0.0

try:
    while True:
        # Set each LED to a different hue
        for i in range(LED_COUNT):
            # Calculate hue for this LED (spread across the strip)
            hue = (hue_offset + (i / LED_COUNT)) % 1.0
            
            # Convert HSV to RGB (saturation=1.0, value=1.0 for full brightness)
            r, g, b = hsv_to_rgb(hue, 1.0, 1.0)
            set_pixel(i, r, g, b)
        
        # Update the strip
        strip.show()
        
        # Increment hue offset to cycle the rainbow
        hue_offset = (hue_offset + HUE_STEP) % 1.0
        
        time.sleep(DELAY)

except Exception as e:
    print("Error:", e)
finally:
    all_off()

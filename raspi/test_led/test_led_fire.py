from rpi_ws281x import PixelStrip, Color
import time
import signal
import sys
import random

# Configuration
LED_COUNT = 110       # 110 LEDs
LED_PIN = 12         # GPIO12 (physical pin 32)
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 128  # 0-255
LED_INVERT = False
LED_CHANNEL = 0
DELAY = 0.05         # seconds between updates (20 FPS for flickering effect)

strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
strip.begin()

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

# Fire effect parameters
heat = [0] * LED_COUNT  # Heat value for each LED

def fire_effect():
    # Cool down every cell a little
    for i in range(LED_COUNT):
        cooldown = random.randint(0, ((55 * 10) // LED_COUNT) + 2)
        if cooldown > heat[i]:
            heat[i] = 0
        else:
            heat[i] = heat[i] - cooldown
    
    # Heat from each cell drifts up and diffuses
    for i in range(LED_COUNT - 1, 1, -1):
        heat[i] = (heat[i - 1] + heat[i - 2] + heat[i - 2]) // 3
    
    # Randomly ignite new sparks near the bottom
    if random.randint(0, 255) < 120:
        y = random.randint(0, 7)
        heat[y] = heat[y] + random.randint(160, 255)
        if heat[y] > 255:
            heat[y] = 255
    
    # Convert heat to LED colors
    for i in range(LED_COUNT):
        # Scale heat to 0-255 range
        t192 = int((heat[i] / 255.0) * 191)
        
        # Calculate color based on heat
        heatramp = t192 & 0x3F  # 0-63
        heatramp <<= 2  # Scale to 0-252
        
        if t192 > 0x80:  # Hottest: yellow to white
            r = 255
            g = 255
            b = heatramp
        elif t192 > 0x40:  # Medium: red to yellow
            r = 255
            g = heatramp
            b = 0
        else:  # Coolest: black to red
            r = heatramp
            g = 0
            b = 0
        
        set_pixel(i, r, g, b)

# Main fire effect loop
try:
    while True:
        fire_effect()
        strip.show()
        time.sleep(DELAY)

except Exception as e:
    print("Error:", e)
finally:
    all_off()

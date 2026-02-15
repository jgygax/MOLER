from rpi_ws281x import PixelStrip, Color
import time
import signal
import sys
import random
import math

# Configuration
LED_COUNT = 110
LED_PIN = 12
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 128
LED_INVERT = False
LED_CHANNEL = 0
DELAY = 0.03  # ~33 FPS

# LED Zones
ZONES = {
    "van-gogh": {"start": 0, "end": 24, "count": 25},
    "schublade": {"start": 25, "end": 36, "count": 12},
    "dia-filter": {"start": 37, "end": 40, "count": 4},
    "dalek-horn": {"start": 41, "end": 44, "count": 4},
    "innenlicht": {"start": 45, "end": 64, "count": 20},
    "belly": {"start": 65, "end": 84, "count": 20},
    "motherboard": {"start": 85, "end": 109, "count": 25}
}

strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
strip.begin()

def set_pixel(idx, r, g, b):
    strip.setPixelColor(idx, Color(r, g, b))

def all_off():
    for i in range(LED_COUNT):
        strip.setPixelColor(i, Color(0, 0, 0))
    strip.show()

# Graceful exit
def handle_exit(signum, frame):
    all_off()
    sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

# Effect state variables
time_offset = 0
fire_heat = [0] * 4  # For dia-filter fire
laser_pulse = 0  # For dalek-horn shooting
laser_active = False
laser_cooldown = 0
belly_pulse = 0  # For belly pulsation
circuit_state = [random.random() for _ in range(25)]  # For motherboard

# Van Gogh - Starry Night Effect (swirling blues and yellows)
def starry_night_effect(zone, t):
    start, end = zone["start"], zone["end"]
    for i in range(start, end + 1):
        offset = (i - start) / zone["count"]
        
        # Swirling motion
        swirl = math.sin(t * 0.5 + offset * 6.28) * 0.5 + 0.5
        wave = math.sin(t * 0.3 + offset * 3.14) * 0.5 + 0.5
        
        # Mix of deep blue and yellow stars
        if swirl > 0.7:  # Yellow stars
            r = int(200 + 55 * wave)
            g = int(180 + 50 * wave)
            b = int(20 + 30 * wave)
        else:  # Deep blue night sky
            r = int(10 + 30 * swirl)
            g = int(20 + 50 * swirl)
            b = int(80 + 100 * wave)
        
        set_pixel(i, r, g, b)

# Schublade - Warmer Oldschool Lamp
def warm_lamp_effect(zone):
    start, end = zone["start"], zone["end"]
    # Much warmer incandescent bulb color
    flicker = random.uniform(0.95, 1.0)
    r = int(255 * flicker * 0.9)
    g = int(100 * flicker * 0.9)
    b = int(10 * flicker * 0.9)
    
    for i in range(start, end + 1):
        set_pixel(i, r, g, b)

# Dia-Filter - Fire Effect (dimmer, no white)
def fire_effect(zone, heat_array):
    start, end = zone["start"], zone["end"]
    count = zone["count"]
    
    # Cool down
    for i in range(count):
        cooldown = random.randint(0, 25)
        if cooldown > heat_array[i]:
            heat_array[i] = 0
        else:
            heat_array[i] = heat_array[i] - cooldown
    
    # Randomly ignite new sparks
    if random.randint(0, 255) < 120:
        heat_array[random.randint(0, count - 1)] = random.randint(150, 220)
    
    # Convert heat to colors (capped at yellow, no white)
    for i in range(count):
        heat = heat_array[i]
        if heat > 150:  # Yellow
            r, g, b = 200, int((heat - 50) * 1.2), 0
        elif heat > 80:  # Orange
            r, g, b = int(heat * 1.8), int((heat - 80) * 1.5), 0
        else:  # Red
            r, g, b = int(heat * 2.0), 0, 0
        
        set_pixel(start + i, r, g, b)

# Dalek Horn - Quick Shooting Laser Effect (less frequent)
def laser_effect(zone, pulse, active, cooldown):
    start, end = zone["start"], zone["end"]
    count = zone["count"]
    
    if not active:
        # Dark/idle state
        for i in range(count):
            set_pixel(start + i, 10, 0, 0)
        
        # Random chance to fire (less frequent)
        if cooldown <= 0 and random.random() < 0.01:  # ~1% chance per frame
            return True, 0.0, 0  # Start firing
        return False, pulse, max(0, cooldown - DELAY)
    else:
        # Fast shooting animation
        position = int((pulse % 1.0) * count)
        
        for i in range(count):
            if i == position:
                # Bright laser point
                r, g, b = 255, 50, 50
            elif abs(i - position) == 1:
                # Trailing glow
                r, g, b = 150, 20, 20
            else:
                # Dark
                r, g, b = 10, 0, 0
            
            set_pixel(start + i, r, g, b)
        
        # Check if shot completed
        if pulse >= 1.0:
            return False, 0.0, random.uniform(2.0, 5.0)  # Cooldown 2-5 seconds
        
        return True, pulse, cooldown

# Innenlicht - Dimmed White
def dimmed_white_effect(zone):
    start, end = zone["start"], zone["end"]
    r, g, b = 100, 100, 90  # Slightly warm white, dimmed
    
    for i in range(start, end + 1):
        set_pixel(i, r, g, b)

# Belly - Soft Pulsating Dark Teal
def pulsating_teal_effect(zone, pulse):
    start, end = zone["start"], zone["end"]
    
    # Sine wave for smooth pulsation
    intensity = (math.sin(pulse * 2) * 0.5 + 0.5) * 0.6 + 0.2  # Range 0.2-0.8
    
    r = int(0 * intensity)
    g = int(100 * intensity)
    b = int(100 * intensity)
    
    for i in range(start, end + 1):
        set_pixel(i, r, g, b)

# Motherboard - Digital Circuit Effect
def circuit_effect(zone, state_array, t):
    start, end = zone["start"], zone["end"]
    
    for i in range(zone["count"]):
        # Random state changes
        if random.random() < 0.02:
            state_array[i] = random.random()
        
        # Fade toward target
        state_array[i] *= 0.95
        
        # Cyan/green data lights
        intensity = state_array[i]
        if intensity > 0.7:
            r, g, b = 0, int(255 * intensity), int(200 * intensity)
        elif intensity > 0.3:
            r, g, b = 0, int(150 * intensity), int(100 * intensity)
        else:
            r, g, b = 0, int(50 * intensity), int(30 * intensity)
        
        set_pixel(start + i, r, g, b)

# Main loop
try:
    while True:
        time_offset += DELAY
        
        # Update each zone
        starry_night_effect(ZONES["van-gogh"], time_offset)
        warm_lamp_effect(ZONES["schublade"])
        fire_effect(ZONES["dia-filter"], fire_heat)
        
        # Super fast laser pulse when active
        laser_active, laser_pulse, laser_cooldown = laser_effect(
            ZONES["dalek-horn"], 
            laser_pulse + (0.3 if laser_active else 0),  # Fast movement
            laser_active, 
            laser_cooldown
        )
        
        dimmed_white_effect(ZONES["innenlicht"])
        
        belly_pulse += DELAY * math.pi
        pulsating_teal_effect(ZONES["belly"], belly_pulse)
        
        circuit_effect(ZONES["motherboard"], circuit_state, time_offset)
        
        strip.show()
        time.sleep(DELAY)

except Exception as e:
    print("Error:", e)
finally:
    all_off()

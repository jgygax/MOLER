from rpi_ws281x import PixelStrip, Color
import time
import signal
import sys
import json

# Configuration
LED_COUNT = 110       # 110 LEDs
LED_PIN = 12         # GPIO12 (physical pin 32)
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 128  # 0-255
LED_INVERT = False
LED_CHANNEL = 0

strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
strip.begin()

def set_pixel(idx, r, g, b):
    strip.setPixelColor(idx, Color(r, g, b))

def all_off():
    for i in range(LED_COUNT):
        strip.setPixelColor(i, Color(0, 0, 0))
    strip.show()

def light_range(start, end):
    """Light up a range of LEDs (inclusive)"""
    all_off()
    for i in range(start, end + 1):
        if i < LED_COUNT:
            set_pixel(i, 255, 255, 255)
    strip.show()

# Graceful exit
def handle_exit(signum, frame):
    all_off()
    sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

# Main labeling loop
segments = {}
current_start = 0
current_end = 0

print("\n=== LED Strip Segment Mapper ===")
print(f"Total LEDs: {LED_COUNT}")
print("\nControls:")
print("  - Press ENTER to extend the lit segment by 1 LED")
print("  - Type a name and press ENTER to save this segment and start the next")
print("  - Type 'back' to go back 1 LED")
print("  - Type 'undo' to remove the last saved segment")
print("  - Type 'done' to finish and save")
print("  - Type 'quit' to exit without saving\n")

try:
    while current_start < LED_COUNT:
        # Light up current range
        light_range(current_start, current_end)
        
        print(f"\rLEDs {current_start}-{current_end} lit ({current_end - current_start + 1} LEDs)", end='', flush=True)
        
        user_input = input("\n> ").strip()
        
        # Empty input = extend by one LED
        if user_input == '':
            if current_end < LED_COUNT - 1:
                current_end += 1
            else:
                print("Reached end of strip!")
            continue
        
        # Commands
        if user_input.lower() == 'quit':
            print("Exiting without saving...")
            break
            
        if user_input.lower() == 'done':
            if len(segments) == 0:
                print("No segments defined yet!")
                continue
            # Save and exit
            with open('led_segments.json', 'w') as f:
                json.dump(segments, f, indent=2)
            print(f"\n✓ Saved {len(segments)} segments to led_segments.json")
            break
        
        if user_input.lower() == 'back':
            if current_end > current_start:
                current_end -= 1
            else:
                print("Already at segment start!")
            continue
            
        if user_input.lower() == 'undo':
            if len(segments) == 0:
                print("No segments to undo!")
                continue
            # Remove last segment
            last_key = list(segments.keys())[-1]
            last_segment = segments.pop(last_key)
            current_start = last_segment['start']
            current_end = current_start
            print(f"Undid segment '{last_key}'")
            continue
        
        # Otherwise, treat as segment name
        segment_name = user_input
        if not segment_name:
            segment_name = f"segment_{len(segments) + 1}"
        
        # Store segment
        segments[segment_name] = {
            'start': current_start,
            'end': current_end,
            'count': current_end - current_start + 1
        }
        
        print(f"✓ Saved '{segment_name}': LEDs {current_start}-{current_end} ({current_end - current_start + 1} LEDs)")
        
        # Move to next segment
        current_start = current_end + 1
        current_end = current_start
        
        if current_start >= LED_COUNT:
            print("\nReached end of strip!")
            with open('led_segments.json', 'w') as f:
                json.dump(segments, f, indent=2)
            print(f"✓ Saved {len(segments)} segments to led_segments.json")
            break

except Exception as e:
    print(f"Error: {e}")
finally:
    all_off()
    
    # Show summary
    if segments:
        print("\n=== Summary ===")
        for name, data in segments.items():
            print(f"  {name}: LEDs {data['start']}-{data['end']} ({data['count']} LEDs)")

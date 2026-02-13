"""
Multi-Zone LED Controller for VPlotter
Controls 110 LEDs in zones plus gondola LED, reacts to plotter state
"""

import math
import random
import signal
import sys
import threading
import time
import logging
import extensions

logger = logging.getLogger(__name__)

# Configuration for 110 LED strip (main zones)
LED_COUNT_MAIN = 110
LED_PIN_MAIN = 12
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 128
LED_INVERT = False
LED_CHANNEL = 0

# Configuration for gondola LED
LED_PIN_GONDOLA = 18
LED_COUNT_GONDOLA = 1

# Update delay (~33 FPS)
DELAY = 0.03

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

# Gondola LED colors
COLOR_IDLE = (0, 0, 64)  # Dim blue
COLOR_PAINT_MAX = (255, 255, 255)  # Pure white at width=1


def interpolate_color(color1, color2, factor):
    """Interpolate between two RGB colors."""
    r = int(color1[0] + (color2[0] - color1[0]) * factor)
    g = int(color1[1] + (color2[1] - color1[1]) * factor)
    b = int(color1[2] + (color2[2] - color1[2]) * factor)
    return (r, g, b)


class MockPixelStrip:
    """Mock LED strip for development/testing without hardware."""
    
    def __init__(self, count, pin, freq_hz, dma, invert, brightness, channel):
        self.count = count
        self.pin = pin
        self.pixels = [(0, 0, 0)] * count
        logger.info(f"MockPixelStrip initialized on pin {pin} with {count} LEDs")
    
    def begin(self):
        pass
    
    def setPixelColor(self, index, color):
        if 0 <= index < self.count:
            self.pixels[index] = color
    
    def show(self):
        pass


class MultiLEDController:
    """
    Multi-zone LED controller that runs in its own thread.
    Controls both the main 110 LED strip and the gondola LED.
    Reacts to VPlotter state for progress indication and effects.
    """
    
    def __init__(self):
        self.running = False
        self.thread = None
        self.strip_main = None
        self.strip_gondola = None
        self.Color = None
        
        # Effect state variables
        self.time_offset = 0
        self.fire_heat = [0] * 4  # For dia-filter fire
        self.laser_charge = 0  # Glow buildup for dalek (0-1)
        self.laser_active = False
        self.laser_cooldown = 0
        self.belly_pulse = 0
        self.circuit_state = [random.random() for _ in range(25)]  # For motherboard
        self.motherboard_fill_level = 0.0  # Current fill level for motherboard progress
        
        # Plotting state (read from vplotter)
        self.is_plotting = False
        self.plot_progress = 0.0  # 0.0 to 1.0
        self.current_line_index = 0
        self.total_lines = 0
        self.current_line_progress = 0.0  # 0.0 to 1.0
        self.plot_finished = False
        self.pen_width = 0.0
        self.prev_pen_width = 0.0  # To detect pen up/down transitions
        
        # Last gondola color for smooth transitions
        self.gondola_color = COLOR_IDLE
        
        self._initialize_strips()
    
    def _initialize_strips(self):
        """Initialize LED strips, falling back to mock if hardware unavailable."""
        try:
            from rpi_ws281x import PixelStrip, Color
            self.Color = Color
            
            # Main 110 LED strip
            self.strip_main = PixelStrip(
                LED_COUNT_MAIN,
                LED_PIN_MAIN,
                LED_FREQ_HZ,
                LED_DMA,
                LED_INVERT,
                LED_BRIGHTNESS,
                LED_CHANNEL,
            )
            self.strip_main.begin()
            
            # Gondola LED on separate pin
            self.strip_gondola = PixelStrip(
                LED_COUNT_GONDOLA,
                LED_PIN_GONDOLA,
                LED_FREQ_HZ,
                LED_DMA,
                LED_INVERT,
                LED_BRIGHTNESS,
                LED_CHANNEL,
            )
            self.strip_gondola.begin()
            
            logger.info("MultiLEDController initialized with hardware")
            
        except ImportError:
            logger.warning("rpi_ws281x not available, using mock LED controllers")
            self.Color = lambda r, g, b: (r, g, b)
            self.strip_main = MockPixelStrip(
                LED_COUNT_MAIN, LED_PIN_MAIN, LED_FREQ_HZ, LED_DMA,
                LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL
            )
            self.strip_gondola = MockPixelStrip(
                LED_COUNT_GONDOLA, LED_PIN_GONDOLA, LED_FREQ_HZ, LED_DMA,
                LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL
            )
        except Exception as e:
            logger.error(f"Failed to initialize LED: {e}")
            raise
    
    def _get_brightness(self):
        """Get current brightness setting from extensions."""
        return getattr(extensions, 'led_settings', {}).get('brightness', 1.0)
    
    def _is_innenlicht_enabled(self):
        """Check if innenlicht is enabled."""
        return getattr(extensions, 'led_settings', {}).get('innenlicht_enabled', True)
    
    def set_pixel(self, strip, idx, r, g, b):
        """Set a pixel color on a strip with brightness dimming applied."""
        brightness = self._get_brightness()
        r = int(r * brightness)
        g = int(g * brightness)
        b = int(b * brightness)
        strip.setPixelColor(idx, self.Color(r, g, b))
    
    def all_off(self):
        """Turn off all LEDs."""
        for i in range(LED_COUNT_MAIN):
            self.strip_main.setPixelColor(i, self.Color(0, 0, 0))
        self.strip_main.show()
        
        if self.strip_gondola:
            self.strip_gondola.setPixelColor(0, self.Color(0, 0, 0))
            self.strip_gondola.show()
    
    def _update_plotter_state(self):
        """Poll the vplotter instance for current state."""
        plotter = getattr(extensions, 'plotter_instance', None)
        if plotter is None:
            self.is_plotting = False
            self.prev_pen_width = self.pen_width
            self.pen_width = 0.0
            return
        
        # Read state from plotter
        self.is_plotting = getattr(plotter, 'is_plotting', False)
        self.plot_progress = getattr(plotter, 'plot_progress', 0.0)
        self.current_line_index = getattr(plotter, 'current_line_index', 0)
        self.total_lines = getattr(plotter, 'total_lines', 0)
        self.current_line_progress = getattr(plotter, 'current_line_progress', 0.0)
        self.plot_finished = getattr(plotter, 'plot_finished', False)
        self.prev_pen_width = self.pen_width
        self.pen_width = getattr(plotter, 'w', 0.0)
    
    # ===== Zone Effect Methods =====
    
    def starry_night_effect(self, zone, t):
        """Van Gogh - Wilder Starry Night Effect (faster, more yellow/blue swirls)"""
        start, end = zone["start"], zone["end"]
        for i in range(start, end + 1):
            offset = (i - start) / zone["count"]
            
            # Faster, wilder swirling motion with multiple frequencies
            swirl = math.sin(t * 0.8 + offset * 6.28) * 0.5 + 0.5
            wave = math.sin(t * 0.5 + offset * 3.14) * 0.5 + 0.5
            wild = math.sin(t * 1.2 + offset * 12.56) * 0.5 + 0.5  # Extra wildness
            
            # Combine for more dynamic movement
            combined = (swirl + wave + wild) / 3
            
            # More yellow/blue contrast, brighter and more saturated
            if combined > 0.6:  # More yellow stars, lower threshold
                # Bright golden yellow
                r = int(255 * wave)
                g = int(220 + 35 * wild)
                b = int(30 + 50 * swirl)
            else:  # Deep vibrant blue
                # More saturated blue with cyan hints
                r = int(5 + 20 * swirl)
                g = int(30 + 80 * wave)
                b = int(120 + 135 * wild)
            
            self.set_pixel(self.strip_main, i, r, g, b)
    
    def progress_meter_effect(self, zone, progress):
        """Van Gogh as progress meter - fills from bottom to top"""
        start, end = zone["start"], zone["end"]
        count = zone["count"]
        
        # Calculate how many LEDs should be lit
        lit_count = int(count * progress)
        
        for i in range(count):
            led_idx = start + i
            
            if i < lit_count:
                # Lit portion - gradient from green (start) to yellow (end)
                ratio = i / count
                r = int(50 + 205 * ratio)
                g = int(200 - 100 * ratio)
                b = int(20)
            elif i == lit_count and progress < 1.0:
                # Leading edge - brighter
                r, g, b = 255, 255, 100
            else:
                # Unlit - dim background
                r, g, b = 5, 5, 20
            
            self.set_pixel(self.strip_main, led_idx, r, g, b)
        
    def warm_lamp_effect(self, zone, t):
        """Schublade - Pulsating warm lamp with left-to-right wave, more warm"""
        start, end = zone["start"], zone["end"]
        count = zone["count"]
        
        # Slower pulsation moving left to right
        wave_pos = (math.sin(t * 1.0) * 0.5 + 0.5)  # Position of brightest point (0-1)
        
        for i in range(count):
            # Calculate distance from wave peak
            pos = i / count
            dist = abs(pos - wave_pos)
            
            # Intensity falls off with distance from wave - stronger pulsation
            intensity = max(0.5, 1.0 - dist * 0.8)
            
            # Small random flicker
            flicker = random.uniform(0.97, 1.0)
            intensity *= flicker
            
            # Warmer, more orange tones
            r = int(255 * intensity)
            g = int(140 * intensity)  # More orange
            b = int(30 * intensity)   # Less blue for warmer feel
            
            self.set_pixel(self.strip_main, start + i, r, g, b)

    def starry_night_effect(self, zone, t):
        """Van Gogh - Wilder Starry Night Effect with distinct yellow/blue streaks"""
        start, end = zone["start"], zone["end"]
        for i in range(start, end + 1):
            offset = (i - start) / zone["count"]
            
            # Multiple frequency waves for streaks
            long_yellow = math.sin(t * 1.5 + offset * 3.14) * 0.5 + 0.5
            long_blue = math.sin(t * 1.3 + offset * 3.14 + 1.57) * 0.5 + 0.5
            short_yellow = math.sin(t * 2.5 + offset * 12.56) * 0.5 + 0.5
            short_blue = math.sin(t * 2.8 + offset * 12.56 + 1.57) * 0.5 + 0.5
            
            # Determine which streak is dominant
            streaks = [
                (long_yellow, "yellow"),
                (long_blue, "blue"),
                (short_yellow, "yellow"),
                (short_blue, "blue")
            ]
            
            max_val, color_type = max(streaks, key=lambda x: x[0])
            
            if color_type == "yellow":
                # Bright golden yellow streaks
                r = int(255 * max_val)
                g = int(200 + 55 * max_val)
                b = int(20 + 30 * max_val)
            else:
                # Deep vibrant blue streaks
                r = int(5 + 15 * max_val)
                g = int(30 + 70 * max_val)
                b = int(120 + 135 * max_val)
            
            self.set_pixel(self.strip_main, i, r, g, b)

    def fire_effect(self, zone, heat_array):
        """Dia-Filter - Smoother, more orange-warm fire effect"""
        start, end = zone["start"], zone["end"]
        count = zone["count"]
        
        # Cool down - slower for smoother effect
        for i in range(count):
            cooldown = random.randint(0, 15)  # Reduced from 25
            if cooldown > heat_array[i]:
                heat_array[i] = 0
            else:
                heat_array[i] = heat_array[i] - cooldown
        
        # Heat diffusion for smoother flames
        for i in range(1, count - 1):
            heat_array[i] = (heat_array[i - 1] + heat_array[i] + heat_array[i + 1]) // 3
        
        # Randomly ignite new sparks
        if random.randint(0, 255) < 120:
            heat_array[random.randint(0, count - 1)] = random.randint(160, 230)
        
        # Convert heat to warm orange/yellow colors
        for i in range(count):
            heat = heat_array[i]
            if heat > 180:  # Bright orange-yellow
                r, g, b = 255, int(140 + (heat - 180) * 1.5), int(20 + (heat - 180) * 0.3)
            elif heat > 100:  # Orange
                r, g, b = int(200 + heat * 0.27), int(80 + heat * 0.6), 0
            elif heat > 40:  # Dark orange-red
                r, g, b = int(heat * 2.2), int(heat * 0.8), 0
            else:  # Deep red ember
                r, g, b = int(heat * 2.5), 0, 0
            
            self.set_pixel(self.strip_main, start + i, r, g, b)

    def laser_effect(self, zone, charge, active, cooldown):
        """Dalek Horn - More frequent shooting with glow buildup before discharge"""
        start, end = zone["start"], zone["end"]
        count = zone["count"]
        
        if not active:
            # Idle state with glow buildup effect
            base_glow = int(5 + charge * 50)
            
            for i in range(count):
                self.set_pixel(self.strip_main, start + i, base_glow, 0, 0)
            
            # More frequent shooting
            if cooldown <= 0 and random.random() < 0.02:  # Increased from 0.005 to 2% chance
                return 0.0, False, 0
            
            # Continue charging
            if cooldown <= 0:
                charge += 0.02
                if charge >= 1.0:
                    charge = 1.0
                    return charge, True, 0
            
            return charge, False, max(0, cooldown - DELAY)
        
        else:
            # Discharge animation
            discharge_progress = charge
            position = int((1.0 - discharge_progress) * count)
            
            for i in range(count):
                if i == position:
                    r, g, b = 255, int(100 * discharge_progress), int(100 * discharge_progress)
                elif abs(i - position) == 1:
                    trail = int(150 * discharge_progress)
                    r, g, b = trail, int(trail * 0.3), int(trail * 0.3)
                else:
                    glow = int(20 * discharge_progress)
                    r, g, b = glow, 0, 0
                
                self.set_pixel(self.strip_main, start + i, r, g, b)
            
            charge -= 0.08
            
            if charge <= 0:
                return 0.0, False, random.uniform(1.0, 3.0)  # Shorter cooldown: 1-3 seconds
            
            return charge, True, 0

    def dimmed_white_effect(self, zone):
        """Innenlicht - Full brightness white (toggleable)"""
        if not self._is_innenlicht_enabled():
            start, end = zone["start"], zone["end"]
            for i in range(start, end + 1):
                self.set_pixel(self.strip_main, i, 0, 0, 0)
            return
        
        start, end = zone["start"], zone["end"]
        r, g, b = 255, 255, 240  # Full brightness, slightly warm white
        
        for i in range(start, end + 1):
            self.set_pixel(self.strip_main, i, r, g, b)

    def pulsating_teal_effect(self, zone, pulse):
        """Belly - Soft Pulsating Dark Teal"""
        start, end = zone["start"], zone["end"]
        
        # Sine wave for smooth pulsation
        intensity = (math.sin(pulse * 2) * 0.5 + 0.5) * 0.6 + 0.2  # Range 0.2-0.8
        
        r = int(0 * intensity)
        g = int(100 * intensity)
        b = int(100 * intensity)
        
        for i in range(start, end + 1):
            self.set_pixel(self.strip_main, i, r, g, b)
    
    def belly_finished_effect(self, zone):
        """Belly - White light when plot is finished"""
        start, end = zone["start"], zone["end"]
        # Bright white to illuminate the image
        r, g, b = 255, 255, 255
        
        for i in range(start, end + 1):
            self.set_pixel(self.strip_main, i, r, g, b)
    
    def circuit_effect(self, zone):
        """Motherboard - Digital Circuit Effect with line progress indicator
        Fills up when pen is down, empties when pen is up (line finished)"""
        start, end = zone["start"], zone["end"]
        count = zone["count"]
        
        # Determine target fill level based on pen state
        PEN_DOWN_THRESHOLD = 0.1
        is_pen_down = self.pen_width > PEN_DOWN_THRESHOLD
        was_pen_down = self.prev_pen_width > PEN_DOWN_THRESHOLD
        
        if is_pen_down:
            # Pen is down - fill up based on current line progress
            target_fill = self.current_line_progress
            # Smoothly approach target
            self.motherboard_fill_level += (target_fill - self.motherboard_fill_level) * 0.3
        else:
            # Pen is up - empty the bar
            if was_pen_down:
                # Just lifted pen - start emptying quickly
                self.motherboard_fill_level = max(0.0, self.motherboard_fill_level - 0.15)
            else:
                # Continue emptying slowly
                self.motherboard_fill_level = max(0.0, self.motherboard_fill_level - 0.08)
        
        # Calculate how many LEDs show progress
        progress_leds = int(count * self.motherboard_fill_level)
        
        for i in range(count):
            if i < progress_leds:
                # Progress indicator - bright cyan/white
                intensity = 0.8 + random.random() * 0.2
                r, g, b = int(100 * intensity), int(255 * intensity), int(255 * intensity)
            elif i == progress_leds and self.motherboard_fill_level > 0 and self.motherboard_fill_level < 1.0:
                # Leading edge of progress - bright white
                r, g, b = 255, 255, 255
            else:
                # Background circuit effect
                # Random state changes
                if random.random() < 0.02:
                    self.circuit_state[i] = random.random()
                
                # Fade toward target
                self.circuit_state[i] *= 0.95
                
                # Dim cyan/green data lights for background
                intensity = self.circuit_state[i] * 0.4  # Dimmer background
                if intensity > 0.3:
                    r, g, b = 0, int(200 * intensity), int(150 * intensity)
                else:
                    r, g, b = 0, int(50 * intensity), int(30 * intensity)
            
            self.set_pixel(self.strip_main, start + i, r, g, b)
    
    def update_gondola_led(self):
        """Update the gondola LED based on pen width."""
        # Calculate target color based on pen width
        target_color = interpolate_color(COLOR_IDLE, COLOR_PAINT_MAX, self.pen_width)
        
        # Smooth transition
        self.gondola_color = interpolate_color(self.gondola_color, target_color, 0.3)
        
        r, g, b = int(self.gondola_color[0]), int(self.gondola_color[1]), int(self.gondola_color[2])
        self.set_pixel(self.strip_gondola, 0, r, g, b)
    
    def _run_loop(self):
        """Main LED update loop."""
        logger.info("MultiLEDController thread started")
        
        try:
            while self.running:
                self.time_offset += DELAY
                
                # Update plotter state
                self._update_plotter_state()
                
                # Update Van Gogh zone - progress meter when plotting, starry night otherwise
                if self.is_plotting:
                    self.progress_meter_effect(ZONES["van-gogh"], self.plot_progress)
                else:
                    self.starry_night_effect(ZONES["van-gogh"], self.time_offset)
                
                # Schublade - warm lamp with left-to-right pulsation
                self.warm_lamp_effect(ZONES["schublade"], self.time_offset)
                
                # Dia-filter - fire effect
                self.fire_effect(ZONES["dia-filter"], self.fire_heat)
                
                # Dalek-horn - laser effect with glow buildup
                self.laser_charge, self.laser_active, self.laser_cooldown = self.laser_effect(
                    ZONES["dalek-horn"],
                    self.laser_charge,
                    self.laser_active,
                    self.laser_cooldown
                )
                
                # Innenlicht - dimmed white (toggleable)
                self.dimmed_white_effect(ZONES["innenlicht"])
                
                # Belly - white when finished, pulsating teal otherwise
                self.belly_pulse += DELAY * math.pi
                if self.plot_finished:
                    self.belly_finished_effect(ZONES["belly"])
                else:
                    self.pulsating_teal_effect(ZONES["belly"], self.belly_pulse)
                
                # Motherboard - digital circuit effect with line progress
                self.circuit_effect(ZONES["motherboard"])
                
                # Update gondola LED
                self.update_gondola_led()
                
                # Show updates
                self.strip_main.show()
                self.strip_gondola.show()
                
                time.sleep(DELAY)
                
        except Exception as e:
            logger.error(f"Error in LED controller loop: {e}")
        finally:
            self.all_off()
            logger.info("MultiLEDController thread stopped")
    
    def start(self):
        """Start the LED controller in a background thread."""
        if self.thread is not None and self.thread.is_alive():
            logger.warning("LED controller thread already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info("MultiLEDController started")
    
    def stop(self):
        """Stop the LED controller thread."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
        self.all_off()
        logger.info("MultiLEDController stopped")
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()


# Backward compatibility - create function for old interface
def create_led_controller():
    """Factory function - now returns None since MultiLEDController is used instead."""
    logger.info("Using MultiLEDController instead of single LED controller")
    return None

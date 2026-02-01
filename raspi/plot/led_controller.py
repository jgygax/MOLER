import logging
import os

logger = logging.getLogger(__name__)

# LED Configuration
LED_COUNT = 1
LED_PIN = 18
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 128
LED_INVERT = False
LED_CHANNEL = 0


def interpolate_color(color1, color2, factor):
    """Interpolate between two RGB colors."""
    r = int(color1[0] + (color2[0] - color1[0]) * factor)
    g = int(color1[1] + (color2[1] - color1[1]) * factor)
    b = int(color1[2] + (color2[2] - color1[2]) * factor)
    return (r, g, b)


class MockLEDController:
    """Mock LED controller for development/testing without hardware."""

    def __init__(self):
        self.current_color = (0, 0, 0)
        self.is_initialized = True
        logger.info("Mock LED controller initialized")

    def set_color(self, r, g, b):
        """Set the LED color (mock implementation)."""
        self.current_color = (r, g, b)
        logger.debug(f"Mock LED color set to RGB({r}, {g}, {b})")

    def get_color(self):
        """Get the current LED color."""
        return self.current_color

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.set_color(0, 0, 0)
        logger.info("Mock LED controller cleaned up")


class LEDController:
    """Real LED controller for Raspberry Pi with rpi_ws281x."""

    def __init__(self):
        self.strip = None
        self.current_color = (0, 0, 0)
        self.is_initialized = False

        try:
            from rpi_ws281x import PixelStrip, Color

            self.Color = Color
            self.strip = PixelStrip(
                LED_COUNT,
                LED_PIN,
                LED_FREQ_HZ,
                LED_DMA,
                LED_INVERT,
                LED_BRIGHTNESS,
                LED_CHANNEL,
            )
            self.strip.begin()
            self.is_initialized = True
            logger.info("Real LED controller initialized")
        except ImportError:
            logger.warning("rpi_ws281x not available, LED will not work")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize LED: {e}")
            raise

    def set_color(self, r, g, b):
        """Set the LED color."""
        if self.strip and self.is_initialized:
            self.strip.setPixelColor(0, self.Color(r, g, b))
            self.strip.show()
            self.current_color = (r, g, b)
            logger.debug(f"LED color set to RGB({r}, {g}, {b})")

    def get_color(self):
        """Get the current LED color."""
        return self.current_color

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Turn off LED on exit."""
        if self.strip and self.is_initialized:
            self.set_color(0, 0, 0)
        logger.info("LED controller cleaned up")


def create_led_controller():
    """Factory function to create appropriate LED controller."""
    try:
        return LEDController()
    except (ImportError, Exception):
        logger.info("Using mock LED controller")
        return MockLEDController()

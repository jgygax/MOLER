import math
import threading
import time
import cv2
import numpy as np
import os
import logging

# Configure logger for this module
logger = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
except ImportError:
    logger.warning("Hardware libraries not found, using mocks")
    from plot.mock import MockGPIO as GPIO


class StepperMotor:
    HALF_STEP_SEQUENCE = [
        [1, 0, 0, 0],
        [1, 1, 0, 0],
        [0, 1, 0, 0],
        [0, 1, 1, 0],
        [0, 0, 1, 0],
        [0, 0, 1, 1],
        [0, 0, 0, 1],
        [1, 0, 0, 1],
    ]

    def __init__(
        self,
        pins,
        speed_up=1,
        speed_down=1,
        up_direction=1,
        initial_string_length=0,
        spool_circumference=12.5,
        steps_per_revolution=4096,
    ):
        self.pins = pins
        self.speed_up = speed_up
        self.speed_down = speed_down
        self.up_direction = up_direction
        self.initial_string_length = initial_string_length
        self.spool_circumference = spool_circumference
        self.steps_per_revolution = steps_per_revolution
        self.revolutions = self.get_revolutions(initial_string_length)

        self.index = 0
        self.last_step_time = time.time()

    def __enter__(self):
        for pin in self.pins:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        for pin in self.pins:
            GPIO.output(pin, GPIO.LOW)

    def step(self, count=1, direction=1):
        if direction == self.up_direction:
            speed = self.speed_up
        else:
            speed = self.speed_down

        update_interval = 1 / (self.steps_per_revolution * speed)

        for _ in range(count):
            current_time = time.time()
            sleep_time = update_interval - (current_time - self.last_step_time)
            if sleep_time > 0 and not os.getenv("NO_SLEEP", "false").lower() == "true":
                time.sleep(sleep_time)
            self.last_step_time = current_time

            self.index = (self.index + direction) % len(self.HALF_STEP_SEQUENCE)
            for pin, value in zip(self.pins, self.HALF_STEP_SEQUENCE[self.index]):
                GPIO.output(pin, value)

            self.revolutions += (
                self.up_direction * direction / self.steps_per_revolution
            )

    def count_steps_to_target(self, target_string_length):
        return round(
            abs(self.get_revolutions(target_string_length) - self.revolutions)
            * self.steps_per_revolution
        )

    def move_to_target(self, target_string_length):
        current_string_length = self.get_string_length()
        if target_string_length < current_string_length:
            direction = -self.up_direction
        else:
            direction = self.up_direction

        self.step(
            count=self.count_steps_to_target(target_string_length), direction=direction
        )

    def get_revolutions(self, string_length):
        return string_length / self.spool_circumference

    def get_string_length(self):
        return self.revolutions * self.spool_circumference


class VPlotter:
    MOTOR_PINS = {
        0: [23, 24, 25, 8],  # Left motor pins
        1: [5, 6, 13, 26],  # Right motor pins
    }
    SPEED_UP = 0.3
    SPEED_DOWN = 0.1
    MOTOR_DISTANCE = 400  # mm
    SERVO_PIN = 10
    SERVO_FREQUENCY = 50
    PEN_UP_DUTY = 12
    PEN_DOWN_DUTY = 2
    STEPS_PER_REVOLUTION = 4096
    SPOOL_CIRCUMFERENCE = 125  # mm
    PIXELS_PER_MM = 1  # mm
    MAX_CIRCLE_DIAMETER = 5  # mm

    DOCK_POSITION = MOTOR_DISTANCE / 2, 125
    START_POSITION = MOTOR_DISTANCE / 2, 200

    def __init__(self):
        self.x = VPlotter.MOTOR_DISTANCE / 2
        # mm
        self.y = 125
        self.w = 0

        self.servo_pwm = None

        s_left, s_right = self.calculate_string_lengths(self.x, self.y)

        self.left_motor = StepperMotor(
            self.MOTOR_PINS[0],
            self.SPEED_UP,
            self.SPEED_DOWN,
            1,
            s_left,
            self.SPOOL_CIRCUMFERENCE,
            self.STEPS_PER_REVOLUTION,
        )
        self.right_motor = StepperMotor(
            self.MOTOR_PINS[1],
            self.SPEED_UP,
            self.SPEED_DOWN,
            -1,
            s_right,
            self.SPOOL_CIRCUMFERENCE,
            self.STEPS_PER_REVOLUTION,
        )

        self.canvas_width = int(VPlotter.MOTOR_DISTANCE * VPlotter.PIXELS_PER_MM)
        self.canvas_height = int(VPlotter.MOTOR_DISTANCE * VPlotter.PIXELS_PER_MM)
        self.clear_canvas()
        logger.info("VPlotter Initialized")

    def __enter__(self):
        GPIO.setmode(GPIO.BCM)

        # Setup Motors
        self.left_motor.__enter__()
        self.right_motor.__enter__()

        # Setup Servo
        GPIO.setup(self.SERVO_PIN, GPIO.OUT)
        self.servo_pwm = GPIO.PWM(self.SERVO_PIN, self.SERVO_FREQUENCY)
        self.servo_pwm.start(0)

        return self

    def __exit__(self, exc_type, exc_value, traceback):
        logger.info("Cleaning up VPlotter...")
        self.pen_up()
        self.servo_pwm.stop()

        self.left_motor.__exit__(exc_type, exc_value, traceback)
        self.right_motor.__exit__(exc_type, exc_value, traceback)

        GPIO.cleanup()

    def clear_canvas(self):
        """Resets the internal canvas to white."""
        logger.debug("Canvas cleared")
        self.canvas = (
            np.ones((self.canvas_height, self.canvas_width, 3), dtype=np.uint8) * 255
        )

    @classmethod
    def calculate_string_lengths(cls, x, y):
        """Calculate string lengths for given x,y coordinates"""
        s_left = (x**2 + y**2) ** 0.5
        s_right = ((cls.MOTOR_DISTANCE - x) ** 2 + y**2) ** 0.5

        if s_left < 0 or s_right < 0:
            logger.error("Calculation Error: strings must be longer than 0 mm")
            raise ValueError("strings must be longer than 0 mm")

        return s_left, s_right

    @classmethod
    def calculate_coords(cls, s_left, s_right):
        """Calculate x,y coordinates from given string lengths"""

        if s_left < 0 or s_right < 0:
            raise ValueError("string lengths must be positive")

        if s_left + s_right < cls.MOTOR_DISTANCE:
            raise ValueError("string lengths too short to reach between motors")

        x = (s_left**2 - s_right**2 + cls.MOTOR_DISTANCE**2) / (2 * cls.MOTOR_DISTANCE)

        y_squared = s_left**2 - x**2

        if y_squared < 0:
            raise ValueError("invalid string lengths")

        y = y_squared**0.5

        return x, y

    def get_current_coords(self):
        return self.calculate_coords(
            self.left_motor.get_string_length(), self.right_motor.get_string_length()
        )

    def set_current_position(self, x, y):
        """Forcing the logic to believe we are at x,y and recalibrating motor revolutions"""
        logger.info(f"Forcing position set to: {x}, {y}")
        s_left, s_right = self.calculate_string_lengths(x, y)
        self.left_motor.revolutions = self.left_motor.get_revolutions(s_left)
        self.right_motor.revolutions = self.right_motor.get_revolutions(s_right)
        self.x = x
        self.y = y

    @staticmethod
    def interpolate(start, end, progression):
        return start + (end - start) * progression

    def pen_up(self):
        self.move_straight_line(w=0)

    def pen_down(self):
        self.move_straight_line(w=1)

    def move_straight_line(self, x=None, y=None, w=None):
        """Move to target position in a straight line with smooth interpolation."""

        start_x, start_y = self.get_current_coords()

        target_x = start_x if x is None else x
        target_y = start_y if y is None else y
        target_w = self.w if w is None else w

        start_w = self.w

        # compute target string lengths
        target_left, target_right = self.calculate_string_lengths(target_x, target_y)
        n_steps_left = self.left_motor.count_steps_to_target(target_left)
        n_steps_right = self.right_motor.count_steps_to_target(target_right)
        max_steps = max(1, abs(n_steps_left), abs(n_steps_right))

        for i in range(max_steps):
            progress = (i + 1) / max_steps

            x = self.interpolate(start_x, target_x, progress)
            y = self.interpolate(start_y, target_y, progress)
            w = self.interpolate(start_w, target_w, progress)

            left, right = self.calculate_string_lengths(x, y)

            # Update steppers, steppers will block / sleep when needed
            self.left_motor.move_to_target(left)
            self.right_motor.move_to_target(right)

            # Update servo
            duty_cycle = self.interpolate(
                VPlotter.PEN_UP_DUTY, VPlotter.PEN_DOWN_DUTY, w
            )
            self.servo_pwm.ChangeDutyCycle(duty_cycle)
            self.w = w

            current_x, current_y = self.get_current_coords()
            pixel_x = int(current_x * VPlotter.PIXELS_PER_MM)
            pixel_y = int(current_y * VPlotter.PIXELS_PER_MM)

            circle_diameter_mm = VPlotter.MAX_CIRCLE_DIAMETER * w
            radius_pixels = int((circle_diameter_mm / 3) * VPlotter.PIXELS_PER_MM)

            if radius_pixels > 0:
                cv2.circle(
                    self.canvas, (pixel_x, pixel_y), radius_pixels, (255, 0, 0), -1
                )

import math
import threading
import time
import RPi.GPIO as GPIO
from RpiMotorLib import RpiMotorLib


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

    def step(self, direction=1):
        """Steps the motor one step in the given direction, will sleep until it's time to step"""
        # Different speeds for moving up or down
        if direction == self.up_direction:
            speed = self.speed_up
        else:
            speed = self.speed_down

        update_interval = speed / self.steps_per_revolution

        # Wait until it's time to step
        current_time = time.time()
        sleep_time = update_interval - (current_time - self.last_step_time)
        if sleep_time > 0:
            time.sleep(sleep_time)
        self.last_step_time = current_time

        # Step
        self.index = (self.index + direction) % len(self.HALF_STEP_SEQUENCE)
        for pin, value in zip(self.pins, self.HALF_STEP_SEQUENCE[self.index]):
            GPIO.output(pin, value)

        # Update internal position
        self.revolutions += direction / self.steps_per_revolution

    def count_steps_to_target(self, target_string_length):
        """Will return number of steps to get as close to the target string length as possible"""

        return round(
            abs(self.get_revolutions(target_string_length) - self.revolutions) * self.steps_per_revolution
        )

    def move_to_target(self, target_string_length):
        """Moves to target string length, and blocks if needed"""
        current_string_length = self.get_sting_length()
        if target_string_length < current_string_length:
            direction = self.up_direction
        else:
            direction = -self.up_direction

        for _ in range(self.count_steps_to_target(target_string_length)):
            self.step(direction)

    def get_revolutions(self, string_length):
        return string_length / self.spool_circumference

    def get_sting_length(self):
        return self.initial_string_length + self.revolutions * self.spool_circumference


class VPlotter:
    # Motor configurations
    MOTOR_PINS = {
        0: [23, 24, 25, 8],  # Left motor pins
        1: [5, 6, 13, 26],  # Right motor pins
    }
    SPEED_UP = 1  # Revolutions per second
    SPEED_DOWN = 1  # Revolutions per second

    MOTOR_DISTANCE = 40  # Distance between motors in cm

    TOP = 10
    LEFT = 10
    BOTTOM = 30
    RIGHT = 30

    # Servo configuration
    SERVO_PIN = 10
    SERVO_FREQUENCY = 50  # Standard servo frequency (50Hz)

    # Z positions (duty cycle percentages for PWM, must be 0-100)
    # For 50Hz servo: 2.5% duty = 0.5ms pulse = 0°, 12.5% duty = 2.5ms pulse = 180°
    PEN_UP_DUTY = 12  # Adjust these values (2.5-12.5) based on your servo
    PEN_DOWN_DUTY = 2  # Adjust these values (2.5-12.5) based on your servo

    def __init__(self):
        self.left_motor = StepperMotor(
            VPlotter.SPEED_UP,
            VPlotter.SPEED_DOWN,
            VPlotter.MOTOR_PINS[0],
            VPlotter.STEPS_PER_REVOLUTION,
        )
        self.right_motor = StepperMotor(
            VPlotter.SPEED_UP,
            VPlotter.SPEED_DOWN,
            VPlotter.MOTOR_PINS[1],
            VPlotter.STEPS_PER_REVOLUTION,
        )

        self.x = VPlotter.MOTOR_DISTANCE / 2
        self.y = 12.5
        self.z = 1  # pen up position

        self.string_lengths = self.calculate_string_lengths(self.x, self.y)

        # Steps per cm calculation
        self.steps_per_cm = VPlotter.STEPS_PER_REVOLUTION / VPlotter.SPOOL_CIRCUMFERENCE

        # Initialize GPIO
        self.setup_gpio()

        # Setup servo PWM for pen up/down
        GPIO.setup(VPlotter.SERVO_PIN, GPIO.OUT)
        self.servo_pwm = GPIO.PWM(VPlotter.SERVO_PIN, VPlotter.SERVO_FREQUENCY)
        self.servo_pwm.start(0)

        # Initialize pen in up position
        self.pen_up()

    def setup_gpio(self):
        """Set up GPIO pins for both motors."""
        GPIO.setmode(GPIO.BCM)
        for pin in VPlotter.MOTOR_PINS[0] + VPlotter.MOTOR_PINS[1]:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW)

    def cleanup(self):
        """Turn off motor pins, raise pen, and clean up GPIO."""
        # Raise pen before cleanup
        self.pen_up()
        time.sleep(0.5)

        # Stop servo PWM
        self.servo_pwm.stop()

        # Turn off motor pins
        GPIO.setmode(GPIO.BCM)
        for pin in VPlotter.MOTOR_PINS[0] + VPlotter.MOTOR_PINS[1]:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW)
        GPIO.cleanup()

    @classmethod
    def calculate_string_lengths(cls, x, y):
        """Calculate string lengths for given x,y coordinates"""
        # Origin is in the middle of the line between the two motors
        # y increases from top to bottom

        s_left = (x**2 + y**2) ** 0.5
        s_right = ((cls.MOTOR_DISTANCE - x) ** 2 + y**2) ** 0.5

        if s_left < 0 or s_right < 0:
            raise ValueError("strings must be longer than 0 cm")

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
            raise ValueError("invalid string lengths - no valid position exists")

        y = y_squared**0.5

        return x, y

    def pen_up(self):
        """Raise the pen."""
        self.servo_pwm.ChangeDutyCycle(VPlotter.PEN_UP_DUTY)
        self.z = 1
        time.sleep(0.3)  # Give servo time to move
        self.servo_pwm.ChangeDutyCycle(0)  # Stop sending signal to prevent jitter
        print("Pen UP")

    def pen_down(self):
        """Lower the pen."""
        self.servo_pwm.ChangeDutyCycle(VPlotter.PEN_DOWN_DUTY)
        self.z = 0
        time.sleep(0.3)  # Give servo time to move
        self.servo_pwm.ChangeDutyCycle(0)  # Stop sending signal to prevent jitter
        print("Pen DOWN")

    def interpolate_z(self, start_z, end_z, num_steps):
        """Smoothly interpolate z position during movement."""
        if num_steps == 0 or start_z == end_z:
            return

        # Convert z values (0-1) to servo duty cycles
        # z=0 (pen down) -> PEN_DOWN_DUTY, z=1 (pen up) -> PEN_UP_DUTY
        start_duty = VPlotter.PEN_DOWN_DUTY + start_z * (
            VPlotter.PEN_UP_DUTY - VPlotter.PEN_DOWN_DUTY
        )
        end_duty = VPlotter.PEN_DOWN_DUTY + end_z * (
            VPlotter.PEN_UP_DUTY - VPlotter.PEN_DOWN_DUTY
        )

        step_size = (end_duty - start_duty) / num_steps

        for i in range(int(num_steps) + 1):
            current_duty = start_duty + (step_size * i)
            print(f"Interpolating Z: Duty Cycle = {current_duty}")
            # Clamp duty cycle to valid range (0-100)
            current_duty = max(0.0, min(100.0, current_duty))
            self.servo_pwm.ChangeDutyCycle(current_duty)
            time.sleep(self.update_interval[0])  # Use motor update interval

        # Ensure we end at exact target position
        end_duty = max(0.0, min(100.0, end_duty))
        self.servo_pwm.ChangeDutyCycle(end_duty)

    @staticmethod
    def interpolate(start, end, progression):
        return start + (end - start) * progression

    def move_straight_line(self, target_x, target_y, target_z):
        """Move to target position in a straight line with smooth z interpolation."""

        start_left = self.left_motor.get_sting_length()
        start_right = self.right_motor.get_sting_length()
        start_z = self.z

        # compute target string lengths
        target_left, target_right = self.calculate_string_lengths(target_x, target_y)
        n_steps_left = self.left_motor.get_steps_to_target(target_left)
        n_steps_right = self.right_motor.get_steps_to_target(target_right)

        max_steps = max(abs(n_steps_left), abs(n_steps_right))
        for i in range(max_steps):
            progress = i / max_steps

            # Update steppers, steppers will block / sleep when needed
            self.left_motor.move_to_target(
                self.interpolate(start_left, target_left, progress)
            )
            self.right_motor.move_to_target(
                self.interpolate(start_right, target_right, progress)
            )

            # Update servo
            z = self.interpolate(start_z, target_z, progress)
            duty_cycle = self.interpolate(
                VPlotter.PEN_DOWN_DUTY, VPlotter.PEN_UP_DUTY, z
            )
            self.servo_pwm.ChangeDutyCycle(duty_cycle)

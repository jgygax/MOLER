import math
import threading
import time
import RPi.GPIO as GPIO
from RpiMotorLib import RpiMotorLib


# TODO: Bändelispitz und Stift sind nicht am selben Punkt -> Korrekturfaktor einbauen


class VPlotter:
    # Motor configurations
    MOTOR_PINS = {
        0: [23, 24, 25, 8],  # Left motor pins
        1: [5, 6, 13, 26],  # Right motor pins
    }
    MOTOR_DISTANCE = 40  # Distance between motors in cm
    STEPS_PER_REVOLUTION = 4096  # 28BYJ-48 has ~512 steps per full revolution
    SPOOL_CIRCUMFERENCE = 12.5  # Circumference of spool in cm
    UPDATE_INTERVAL = 0.0016  # Tick interval in seconds

    # Half-step sequence for smoother motion
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

    # Servo configuration
    SERVO_PIN = 10
    SERVO_FREQUENCY = 50  # Standard servo frequency (50Hz)

    # Z positions (duty cycle percentages for PWM, must be 0-100)
    # For 50Hz servo: 2.5% duty = 0.5ms pulse = 0°, 12.5% duty = 2.5ms pulse = 180°
    PEN_UP_DUTY = 12  # Adjust these values (2.5-12.5) based on your servo
    PEN_DOWN_DUTY = 2  # Adjust these values (2.5-12.5) based on your servo

    def __init__(self):
        self.update_interval = [VPlotter.UPDATE_INTERVAL, VPlotter.UPDATE_INTERVAL]

        self.direction = [-1, 1]
        self.seq_idx = [0, 0]

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

    def update_self_position(self, x, y, z):
        """Update the internal position state."""
        self.x = x
        self.y = y
        self.z = z
        self.string_lengths = self.calculate_string_lengths(x, y)

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
        for pin in VPlotter.MOTOR_PINS[0] + VPlotter.MOTOR_PINS[1]:
            GPIO.output(pin, GPIO.LOW)
        GPIO.cleanup()

    def calculate_string_lengths(self, x, y):
        """Calculate string lengths for given x,y coordinates"""
        # Origin is in the middle of the line between the two motors
        # y increases from top to bottom

        s_left = (x**2 + y**2) ** 0.5
        s_right = ((VPlotter.MOTOR_DISTANCE - x) ** 2 + y**2) ** 0.5

        if s_left < 0 or s_right < 0:
            raise ValueError("strings must be longer than 0 cm")

        return s_left, s_right

    def make_step(self, motor):
        """Execute one step for the specified motor."""
        # Update sequence index
        self.seq_idx[motor] = (self.seq_idx[motor] + self.direction[motor] + 8) % 8

        # Apply the step pattern
        for i in range(4):
            GPIO.output(
                VPlotter.MOTOR_PINS[motor][i],
                VPlotter.HALF_STEP_SEQUENCE[self.seq_idx[motor]][i],
            )

    def pen_up(self):
        """Raise the pen."""
        self.servo_pwm.ChangeDutyCycle(VPlotter.PEN_UP_DUTY)
        time.sleep(0.3)  # Give servo time to move
        self.servo_pwm.ChangeDutyCycle(0)  # Stop sending signal to prevent jitter
        self.z = 1
        print("Pen UP")

    def pen_down(self):
        """Lower the pen."""
        self.servo_pwm.ChangeDutyCycle(VPlotter.PEN_DOWN_DUTY)
        time.sleep(0.3)  # Give servo time to move
        self.servo_pwm.ChangeDutyCycle(0)  # Stop sending signal to prevent jitter
        self.z = 0
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

    def move_straight_line(self, target_x, target_y, target_z):
        """Move to target position in a straight line with smooth z interpolation."""

        # compute target string lengths
        tstring = self.calculate_string_lengths(target_x, target_y)
        print("-" * 50)
        print("current", self.string_lengths)
        print("target", tstring)

        # get number of steps for moving to target
        steps = [
            (tstring[i] - self.string_lengths[i]) * self.steps_per_cm for i in range(2)
        ]
        print("steps", steps)

        # get direction of movement
        self.direction[0] = -1 if steps[0] > 0 else 1
        self.direction[1] = 1 if steps[1] > 0 else -1

        # compute movement speed
        self.update_interval = [VPlotter.UPDATE_INTERVAL, VPlotter.UPDATE_INTERVAL]
        if steps[0] != 0 and steps[1] != 0:
            if abs(steps[0]) > abs(steps[1]):
                self.update_interval[1] = (
                    abs(steps[0] / steps[1]) * self.update_interval[0]
                )
            else:
                self.update_interval[0] = (
                    abs(steps[1] / steps[0]) * self.update_interval[1]
                )

        print("update", self.update_interval)

        # Start motor threads
        motor_threads = [
            threading.Thread(target=self.move_motor, args=(motor, steps[motor]))
            for motor in range(2)
        ]

        # Start z interpolation thread
        z_thread = threading.Thread(
            target=self.interpolate_z,
            args=(self.z, target_z, abs(steps[0])),
        )

        for motor_thread in motor_threads:
            motor_thread.start()
        z_thread.start()

        for motor_thread in motor_threads:
            motor_thread.join()
        z_thread.join()

        self._update_pos(target_x, target_y, target_z)

    def _update_pos(self, x, y, z):
        """Update internal position."""
        self.x = x
        self.y = y
        self.z = z
        self.string_lengths = self.calculate_string_lengths(x, y)

    def move_motor(self, motor, n_steps):
        """Move a single motor by n_steps."""
        for _ in range(abs(int(n_steps))):
            start_time = time.time()
            self.make_step(motor)

            elapsed = time.time() - start_time
            sleep_time = max(0, self.update_interval[motor] - elapsed)
            time.sleep(sleep_time)

    def move_single_motor(self, motor, speed):
        """Move a single motor at specified speed (for calibration)."""

        # get number of steps for moving to target
        steps = [0, 0]
        steps[motor] = abs(speed)
        print("steps", steps)

        # get direction of movement
        self.direction[motor] = -1 if speed > 0 else 1

        # compute movement speed
        self.update_interval = [VPlotter.UPDATE_INTERVAL, VPlotter.UPDATE_INTERVAL]

        print("update", self.update_interval[motor])

        motor_thread = threading.Thread(
            target=self.move_motor, args=(motor, steps[motor])
        )

        motor_thread.start()
        motor_thread.join()

        # TODO: update position accordingly

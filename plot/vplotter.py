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
    UPDATE_INTERVAL = 0.0008  # Tick interval in seconds
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

    def __init__(self):
        # Initialize GPIO

        self.setup_gpio()

        self.update_interval = [VPlotter.UPDATE_INTERVAL, VPlotter.UPDATE_INTERVAL]

        self.direction = [-1, 1]
        self.seq_idx = [0, 0]

        self.x = VPlotter.MOTOR_DISTANCE / 2
        self.y = 12.5

        self.string_lengths = self.calculate_string_lengths(self.x, self.y)

        # Steps per cm calculation
        self.steps_per_cm = VPlotter.STEPS_PER_REVOLUTION / VPlotter.SPOOL_CIRCUMFERENCE
    
    def update_self_position(self, x, y):
        self.x = x
        self.y = y
        self.string_lengths = self.calculate_string_lengths(x, y)

    def setup_gpio(self):
        """Set up GPIO pins for both motors."""
        GPIO.setmode(GPIO.BCM)
        for pin in VPlotter.MOTOR_PINS[0] + VPlotter.MOTOR_PINS[1]:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW)

    def cleanup(self):
        """Turn off motor pins and clean up GPIO."""
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
        # Update sequence index
        self.seq_idx[motor] = (self.seq_idx[motor] + self.direction[motor] + 8) % 8

        # Apply the step pattern
        for i in range(4):
            GPIO.output(
                VPlotter.MOTOR_PINS[motor][i],
                VPlotter.HALF_STEP_SEQUENCE[self.seq_idx[motor]][i],
            )

    def move_straight_line(self, target_x, target_y):

        # compute target string lenghts
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

        motor_threads = [
            threading.Thread(target=self.move_motor, args=(motor, steps[motor]))
            for motor in range(2)
        ]

        for motor_thread in motor_threads:
            motor_thread.start()

        for motor_thread in motor_threads:
            motor_thread.join()

        self._update_pos(target_x, target_y)

    def _update_pos(self, x, y):
        self.x = x
        self.y = y
        self.string_lengths = self.calculate_string_lengths(x, y)

    def move_motor(self, motor, n_steps):
        for _ in range(abs(int(n_steps))):
            start_time = time.time()
            self.make_step(motor)

            elapsed = time.time() - start_time
            sleep_time = max(0, self.update_interval[motor] - elapsed)
            time.sleep(sleep_time)

    def move_single_motor(self, motor, speed):

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

        #TODO: update position accordingly

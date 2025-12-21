from plot.vplotter import VPlotter
import time


def steps_left(speed):
    try:
        plotter = VPlotter()
        plotter.move_single_motor(0, -speed)

    except KeyboardInterrupt:
        print("\nStopping plotter...")
    finally:
        plotter.cleanup()
        print("Plotting finished, GPIO cleaned up")


def steps_right(speed):
    try:
        plotter = VPlotter()
        plotter.move_single_motor(1, speed)

    except KeyboardInterrupt:
        print("\nStopping plotter...")
    finally:
        plotter.cleanup()
        print("Plotting finished, GPIO cleaned up")


def calibrate_servo(duty_cycle):
    """Test a specific duty cycle value for servo calibration.

    Usage:
        plotter.calibrate_servo(5.0)   # Test 0° position
        plotter.calibrate_servo(7.5)   # Test 90° position
        plotter.calibrate_servo(10.0)  # Test 180° position
    """

    try:
        plotter = VPlotter()
        print(f"Setting servo to duty cycle: {duty_cycle}%")
        plotter.servo_pwm.ChangeDutyCycle(duty_cycle)
        time.sleep(5)  # Allow time to observe position
        plotter.servo_pwm.ChangeDutyCycle(0)  # Stop signal

    except KeyboardInterrupt:
        print("\nStopping plotter...")
    finally:
        plotter.cleanup()
        print("Plotting finished, GPIO cleaned up")

from plot.vplotter import VPlotter
import time


def steps_left(speed, plotter):
    if speed < 0:
        direction = plotter.left_motor.up_direction
    else:
        direction = -plotter.left_motor.up_direction

    for _ in range(abs(speed)):
        plotter.left_motor.step(direction=direction)
        plotter.update_canvas()


def steps_right(speed, plotter):
    if speed < 0:
        direction = plotter.right_motor.up_direction
    else:
        direction = -plotter.right_motor.up_direction

    for _ in range(abs(speed)):
        plotter.right_motor.step(direction=direction)
        plotter.update_canvas()


def calibrate_servo(duty_cycle, plotter):
    """Test a specific duty cycle value for servo calibration.

    Usage:
        plotter.calibrate_servo(5.0)   # Test 0° position
        plotter.calibrate_servo(7.5)   # Test 90° position
        plotter.calibrate_servo(10.0)  # Test 180° position
    """

    print(f"Setting servo to duty cycle: {duty_cycle}%")
    plotter.servo_pwm.ChangeDutyCycle(duty_cycle)
    time.sleep(5)  # Allow time to observe position
    plotter.servo_pwm.ChangeDutyCycle(0)  # Stop signal

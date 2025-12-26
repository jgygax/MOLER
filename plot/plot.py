from plot.vplotter import VPlotter
from plot.patterns import plot_cool_pattern, plot_square, plot_circle, plot_house
import yaml


def plot_pattern(plotter):
    try:
        r = 15
        cx = 17
        cy = 23
        plot_cool_pattern(plotter, r, cx, cy)
    except KeyboardInterrupt:
        print("\nStopping plotter...")
    finally:
        plotter.move_straight_line(cx, cy, 1)
        print("Plotting finished, GPIO cleaned up")


def plot_pattern(plotter, pattern, stop_event=None):
    if stop_event and stop_event.is_set():
        return

    # Go to start position
    plotter.pen_up()
    plotter.move_straight_line(plotter.MOTOR_DISTANCE / 2, plotter.MOTOR_DISTANCE / 2)

    for line in pattern["lines"]:
        if stop_event and stop_event.is_set():
            break

        points = line["points"]

        start_x, start_y = points[0]["x"], points[0]["y"]
        plotter.move_straight_line(start_x, start_y, 0)
        plotter.move_straight_line(start_x, start_y, 0)

        for point in line["points"]:
            if stop_event and stop_event.is_set():
                break
            x, y, w = point["x"], point["y"], point["w"]
            plotter.move_straight_line(x, y, w)

        plotter.pen_up()

    # Finish sequence regardless of stop event
    plotter.move_straight_line(
        plotter.MOTOR_DISTANCE / 2, plotter.MOTOR_DISTANCE / 2, 0
    )
    plotter.move_straight_line(plotter.MOTOR_DISTANCE / 2, 125, 0)

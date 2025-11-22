from plot.vplotter import VPlotter
from plot.patterns import plot_cool_pattern, plot_square, plot_circle, plot_house
import yaml


def plot_pattern():
    try:
        r = 15
        cx = 17
        cy = 23
        plotter = VPlotter()

        # plot_square(plotter, r, cx, cy)
        # plotter.move_straight_line(cx, cy)
        # plot_circle(plotter, r, cx, cy)
        # plotter.move_straight_line(cx, cy)
        plot_cool_pattern(plotter, r, cx, cy)

    except KeyboardInterrupt:
        print("\nStopping plotter...")
    finally:
        plotter.move_straight_line(cx, cy)
        plotter.cleanup()
        print("Plotting finished, GPIO cleaned up")


def plot_from_file(data):
    try:
        plotter = VPlotter()
        plotter.update_self_position(12, 16)
        print("--->", plotter.x, plotter.y)

        lines = data["lines"]
        line_points = [[(p["x"], p["y"]) for p in line["points"]] for line in lines]
        for line in line_points:
            for x, y in line:
                plotter.move_straight_line(x/10+12, y/10+16)
                print("--->", plotter.x, plotter.y)

    except KeyboardInterrupt:
        print("\nStopping plotter...")
    finally:
        plotter.cleanup()
        print("Plotting finished, GPIO cleaned up")

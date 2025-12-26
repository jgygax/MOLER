from plot.vplotter import VPlotter
from plot.patterns import plot_cool_pattern, plot_square, plot_circle, plot_house
import yaml


def plot_pattern(plotter):
    try:
        r = 15
        cx = 17
        cy = 23

        # plot_square(plotter, r, cx, cy)
        # plotter.move_straight_line(cx, cy)
        # plot_circle(plotter, r, cx, cy)
        # plotter.move_straight_line(cx, cy)
        plot_cool_pattern(plotter, r, cx, cy)

    except KeyboardInterrupt:
        print("\nStopping plotter...")
    finally:
        plotter.move_straight_line(cx, cy)
        print("Plotting finished, GPIO cleaned up")


def plot_from_file(
    plotter,
    data,
    pos_scale=10,
):
    plotter.move_straight_line(20, 20, 1)
    print("--->", plotter.x, plotter.y)

    lines = data["lines"]
    line_points = [[(p["x"], p["y"], p["w"]) for p in line["points"]] for line in lines]
    for line in line_points:
        x, y, w = line[0]
        plotter.move_straight_line(x / pos_scale, y / pos_scale, 1)
        print("--->", plotter.x, plotter.y, plotter.z)
        plotter.pen_down()
        for x, y, w in line[1:]:
            plotter.move_straight_line(x / pos_scale, y / pos_scale, 1 - w)
            print("--->", plotter.x, plotter.y, plotter.z)
        plotter.pen_up()
    plotter.pen_up()
    plotter.move_straight_line(20, 20, 1)
    plotter.move_straight_line(20, 12.5, 1)

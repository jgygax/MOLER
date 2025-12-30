import math


def plot_circle(plotter, r, cx, cy, num_points=20):
    # Number of points to approximate the circle
    # More points will make the circle smoother

    # Loop to generate and move through points on the circle
    for i in range(num_points + 1):  # +1 to close the circle
        angle = (2 * math.pi / num_points) * i
        x = cx + r * math.cos(angle)
        y = cy + r * math.sin(angle)
        plotter.move_straight_line(x, y)


def plot_square(plotter, r, cx, cy):
    plotter.move_straight_line(cx, cy - r)
    plotter.move_straight_line(cx + r, cy - r)
    plotter.move_straight_line(cx + r, cy + r)
    plotter.move_straight_line(cx - r, cy + r)
    plotter.move_straight_line(cx - r, cy - r)
    plotter.move_straight_line(cx, cy - r)


def plot_cool_pattern(plotter, r, cx, cy):
    for i in range(0, r, 2):
        plotter.move_straight_line(cx + r, cy + i)
        plotter.move_straight_line(cx + r, cy + i + 1)
        plotter.move_straight_line(cx + i, cy)
        plotter.move_straight_line(cx + i + 1, cy)

    for i in range(r):
        plotter.move_straight_line(cx + i, cy + 1 + (r - i))
        plotter.move_straight_line(cx + i, cy + (r - i))
        plotter.move_straight_line(cx + i + 1, cy)


def plot_house(plotter, r, cx, cy):
    plotter.move_straight_line(cx, cy)
    plotter.move_straight_line(cx + r, cy)
    plotter.move_straight_line(cx, cy - r)
    plotter.move_straight_line(cx + r, cy - r)
    plotter.move_straight_line(cx + 0.5 * r, cy - 1.5 * r)
    plotter.move_straight_line(cx, cy - r)
    plotter.move_straight_line(cx, cy)
    plotter.move_straight_line(cx + r, cy - r)
    plotter.move_straight_line(cx + r, cy)
    plotter.move_straight_line(cx, cy)

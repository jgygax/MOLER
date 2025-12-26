import logging

# Configure logger for this module
logger = logging.getLogger(__name__)


def plot_pattern(plotter, pattern, stop_event=None):
    if stop_event and stop_event.is_set():
        return

    # Pen Up before starting specific pattern sequence
    plotter.pen_up()

    for line in pattern["lines"]:
        if stop_event and stop_event.is_set():
            break

        points = line["points"]

        # Move to first point of the line
        start_x, start_y = points[0]["x"], points[0]["y"]
        plotter.pen_up()
        plotter.move_straight_line(start_x, start_y)

        # Plot points
        for point in points:
            if stop_event and stop_event.is_set():
                break
            x, y, w = point["x"], point["y"], point["w"]
            plotter.move_straight_line(x, y, w)
            logger.debug((x, y, w, plotter.get_current_coords()))

        plotter.pen_up()

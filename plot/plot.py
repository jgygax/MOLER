import logging

# Configure logger for this module
logger = logging.getLogger(__name__)


def execute_move_sequence(plotter, target, stop_event=None):
    if stop_event and stop_event.is_set():
        return

    # Always pen up first
    plotter.pen_up()

    # Get coordinate definitions
    start_x, start_y = plotter.START_POSITION
    dock_x, dock_y = plotter.DOCK_POSITION

    if target == "start":
        # Just move to start (after pen up)
        if stop_event and stop_event.is_set():
            return
        plotter.move_straight_line(start_x, start_y, 0)

    elif target == "dock":
        # Move to start first
        if stop_event and stop_event.is_set():
            return
        plotter.move_straight_line(start_x, start_y, 0)

        # Then move to dock
        if stop_event and stop_event.is_set():
            return
        plotter.move_straight_line(dock_x, dock_y, 0)


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

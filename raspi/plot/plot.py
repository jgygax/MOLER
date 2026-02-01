import logging

# Configure logger for this module
logger = logging.getLogger(__name__)


def execute_move_sequence(plotter, target, stop_event=None, speed_mulitplier=None):
    if stop_event and stop_event.is_set():
        return

    # Always pen up first
    plotter.pen_up()

    # Get coordinate definitions
    start_x, start_y = plotter.START_POSITION
    dock_x, dock_y = plotter.DOCK_POSITION

    if target == "start":
        # Set LED to green when going to start
        plotter.set_led_go_start()
        # Just move to start (after pen up)
        if stop_event and stop_event.is_set():
            return
        plotter.move_straight_line(
            start_x, start_y, 0, speed_mulitplier=speed_mulitplier
        )

    elif target == "dock":
        # Set LED to red when going home
        plotter.set_led_go_home()
        # Move to start first
        if stop_event and stop_event.is_set():
            return
        plotter.move_straight_line(
            start_x, start_y, 0, speed_mulitplier=speed_mulitplier
        )

        # Then move to dock
        if stop_event and stop_event.is_set():
            return
        # Go a bit above, and jiggle back to position
        plotter.move_straight_line(
            dock_x, dock_y - 10, 0, speed_mulitplier=speed_mulitplier
        )
        # set strings to known positions
        plotter.set_current_position(*plotter.DOCK_POSITION)

    # Reset LED to idle after movement
    plotter.set_led_idle()


def plot_pattern(plotter, pattern, stop_event=None):
    if stop_event and stop_event.is_set():
        return

    # Pen Up before starting specific pattern sequence
    plotter.pen_up()
    # Set LED to painting mode (idle/blue)
    plotter.set_led_idle()

    total_distance = 0

    home_distance = pattern.get("metadata", {}).get("home_distance", 1000000)

    for line in pattern["lines"]:
        if stop_event and stop_event.is_set():
            break

        total_distance += line["length"]
        points = line["points"]

        # Move to first point of the line
        start_x, start_y = points[0]["x"], points[0]["y"]
        plotter.pen_up()
        plotter.move_straight_line(start_x, start_y)
        plotter.pen_down()

        # Plot points
        for point in points:
            if stop_event and stop_event.is_set():
                break
            x, y, w = point["x"], point["y"], point["w"]
            # Update LED color based on paint width
            plotter.set_led_paint(w)
            plotter.move_straight_line(x, y, w)

        plotter.pen_up()
        # Reset LED to idle after finishing the line
        plotter.set_led_idle()

        if home_distance and total_distance > home_distance:
            execute_move_sequence(plotter, "dock", stop_event, speed_mulitplier=1)
            total_distance = 0

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
        # Just move to start (after pen up)
        if stop_event and stop_event.is_set():
            return
        plotter.move_straight_line(
            start_x, start_y, 0, speed_mulitplier=speed_mulitplier
        )

    elif target == "dock":
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


def plot_pattern(plotter, pattern, stop_event=None):
    if stop_event and stop_event.is_set():
        return

    # Pen Up before starting specific pattern sequence
    plotter.pen_up()

    total_lines = len(pattern["lines"])
    total_distance = 0
    
    home_distance = pattern.get("metadata", {}).get("home_distance", 1000000)
    
    # Set plotting state
    plotter.is_plotting = True
    plotter.plot_finished = False
    plotter.total_lines = total_lines
    plotter.plot_progress = 0.0

    for line_idx, line in enumerate(pattern["lines"]):
        if stop_event and stop_event.is_set():
            break

        total_distance += line["length"]
        points = line["points"]
        
        # Update progress tracking
        plotter.current_line_index = line_idx
        plotter.plot_progress = line_idx / total_lines if total_lines > 0 else 0.0

        # Move to first point of the line
        start_x, start_y = points[0]["x"], points[0]["y"]
        plotter.pen_up()
        plotter.move_straight_line(start_x, start_y)
        plotter.pen_down()

        # Plot points
        num_points = len(points)
        for point_idx, point in enumerate(points):
            if stop_event and stop_event.is_set():
                break
            x, y, w = point["x"], point["y"], point["w"]
            plotter.move_straight_line(x, y, w)
            
            # Update current line progress
            plotter.current_line_progress = (point_idx + 1) / num_points if num_points > 0 else 0.0

        plotter.pen_up()

        if home_distance and total_distance > home_distance:
            execute_move_sequence(plotter, "dock", stop_event, speed_mulitplier=1)
            total_distance = 0
    
    # Mark plotting as finished
    plotter.is_plotting = False
    plotter.plot_finished = True
    plotter.plot_progress = 1.0
    plotter.current_line_progress = 1.0

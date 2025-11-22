from plot.vplotter import VPlotter


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

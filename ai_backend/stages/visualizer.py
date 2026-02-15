import os
import yaml
import logging
from PIL import Image, ImageDraw
from .base import BaseStage
import numpy as np

logger = logging.getLogger("ai_backend.stages.visualizer")


class VisualizerStage(BaseStage):
    def __init__(self):
        super().__init__("visualizer")
        self.valid_input_slugs = [
            "slicer"
        ]  # Requires at least one slicer run to trigger

    def process(self, input_path, params, job_info):
        """
        Visualizes ALL Slicer YAML files generated during the current job run.
        Each slicer output is drawn in a different color to distinguish them.
        """
        # Find all artifacts with the 'slicer' slug from the job history
        slicer_artifacts = [
            a for a in job_info.get("artifacts", []) if a["slug"] in self.valid_input_slugs
        ]

        if not slicer_artifacts:
            logger.warning(
                "No slicer artifacts found in job history. Creating an empty visualization."
            )
            # Create a blank image with a warning message in case this stage is run without any slicer outputs
            img = Image.new("RGB", (1200, 400), "white")
            draw = ImageDraw.Draw(img)
            draw.text(
                (20, 20), "Warning: No Slicer output found to visualize.", fill="red"
            )
            output_filename = self.save_hashed_image(img, extension=".png")
            return {"visualizer": output_filename}

        slicer_paths = [a["path"] for a in slicer_artifacts]
        logger.info(
            f"Visualizing {len(slicer_paths)} slicer YAMLs from the current job."
        )

        # --- Canvas Setup - Use metadata from the FIRST slicer output for bounds ---
        try:
            with open(slicer_paths[0], "r") as f:
                first_data = yaml.safe_load(f)
        except (FileNotFoundError, yaml.YAMLError) as e:
            raise ValueError(
                f"Could not read or parse the first slicer output {slicer_paths[0]}: {e}"
            )

        meta = first_data.get("metadata", {})
        # Get bounds from metadata (format: [min_x, min_y, max_x, max_y])
        bounds = meta.get("drawing_bounds", [100, 150, 300, 350])
        min_x, min_y = bounds[0], bounds[1]
        max_x, max_y = bounds[2], bounds[3]
        area_w = max_x - min_x
        area_h = max_y - min_y

        # Pixels per mm for the preview image
        px_per_mm = 6.0
        img_w = int(area_w * px_per_mm)
        img_h = int(area_h * px_per_mm)

        # Create white canvas
        img = Image.new("RGB", (img_w, img_h), "white")
        draw = ImageDraw.Draw(img)

        # Colors to cycle through for each slicer file
        colors = [(0, 0, 0), (255, 0, 0), (0, 0, 255), (0, 150, 0), (255, 140, 0)]

        # --- Drawing Loop ---
        for i, yaml_path in enumerate(slicer_paths):
            color = colors[i % len(colors)]
            logger.info(
                f"Drawing from '{os.path.basename(yaml_path)}' with color {color}"
            )

            try:
                with open(yaml_path, "r") as f:
                    data = yaml.safe_load(f)
            except (FileNotFoundError, yaml.YAMLError):
                logger.error(f"Skipping visualization for unreadable file: {yaml_path}")
                continue

            lines = data.get("lines", [])

            for line in lines:
                points = line.get("points", [])
                if not points:
                    continue

                previous_pt = None
                for pt in points:
                    # Coordinates are absolute, translate to local image coordinates
                    curr_px = (
                        (pt["x"] - min_x) * px_per_mm,
                        (pt["y"] - min_y) * px_per_mm,
                    )
                    width_mm = pt.get("w", 0.5)
                    width_px = max(1, width_mm * px_per_mm)

                    if previous_pt:
                        draw.line(
                            [previous_pt, curr_px], fill=color, width=int(width_px)
                        )
                        # Draw circles at joints for a smoother look
                        rad = width_px / 2
                        draw.ellipse(
                            [
                                curr_px[0] - rad,
                                curr_px[1] - rad,
                                curr_px[0] + rad,
                                curr_px[1] + rad,
                            ],
                            fill=color,
                        )
                    previous_pt = curr_px

        # Save the final composite image
        output_filename = self.save_hashed_image(img, extension=".png")
        logger.info(f"Generated composite visualization: {output_filename}")
        return {"visualizer": output_filename}

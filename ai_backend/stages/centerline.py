import cv2
import numpy as np
import os
import subprocess
import logging
import tempfile
from .base import BaseStage
from svgpathtools import svg2paths, wsvg
from xml.dom import minidom
import re

logger = logging.getLogger("ai_backend.stages.centerline")

import cv2
import numpy as np
import os
import subprocess
import logging
import tempfile
from .base import BaseStage
from svgpathtools import svg2paths, wsvg
import re

logger = logging.getLogger("ai_backend.stages.centerline")


class CenterlineStage(BaseStage):
    def __init__(self):
        super().__init__("centerline")
        self.valid_input_slugs = ["cleanup", "outline", "subtract"]

    def _parse_style_attribute(self, style_str):
        """Parse CSS style string and extract stroke and fill colors."""
        if not style_str:
            return None, None

        stroke = None
        fill = None

        # Parse style string like "stroke:#080808; fill:none;"
        for item in style_str.split(";"):
            item = item.strip()
            if ":" in item:
                key, value = item.split(":", 1)
                key = key.strip().lower()
                value = value.strip()

                if key == "stroke":
                    stroke = value
                elif key == "fill":
                    fill = value

        return stroke, fill

    def _parse_color(self, color_str):
        """Parse color string and return brightness (0-255)."""
        if not color_str or color_str.lower() == "none":
            return None

        # Remove whitespace
        color_str = color_str.strip().lower()

        # Handle hex colors
        if color_str.startswith("#"):
            hex_color = color_str[1:]
            if len(hex_color) == 3:
                hex_color = "".join([c * 2 for c in hex_color])
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            # Calculate perceived brightness using luminance formula
            return 0.299 * r + 0.587 * g + 0.114 * b

        # Handle rgb() format
        if color_str.startswith("rgb"):
            match = re.search(r"rgb\((\d+),\s*(\d+),\s*(\d+)\)", color_str)
            if match:
                r, g, b = map(int, match.groups())
                return 0.299 * r + 0.587 * g + 0.114 * b

        # Named colors (basic set)
        named_colors = {
            "black": 0,
            "white": 255,
            "red": 76,
            "green": 150,
            "blue": 29,
            "yellow": 226,
            "cyan": 179,
            "magenta": 105,
            "gray": 128,
            "grey": 128,
            "silver": 192,
        }
        return named_colors.get(color_str, 128)  # Default to medium brightness

    def _filter_dark_paths(self, svg_path, brightness_threshold=128):
        """
        Remove bright paths from SVG, keeping only dark ones.

        Args:
            svg_path: Path to input SVG file
            brightness_threshold: Paths with brightness above this are removed (0-255)

        Returns:
            Path to filtered SVG file
        """
        try:
            # Parse the SVG
            paths, attributes, svg_attributes = svg2paths(
                svg_path, return_svg_attributes=True
            )

            # Filter paths based on stroke/fill color
            filtered_paths = []
            filtered_attributes = []

            for path, attr in zip(paths, attributes):
                # First check if colors are in 'style' attribute
                style = attr.get("style", "")
                stroke_from_style, fill_from_style = self._parse_style_attribute(style)

                # Fall back to direct attributes if not in style
                stroke = stroke_from_style or attr.get("stroke", "")
                fill = fill_from_style or attr.get("fill", "")

                # Calculate brightness for stroke and fill
                stroke_brightness = self._parse_color(stroke)
                fill_brightness = self._parse_color(fill)

                # Keep path if either stroke or fill is dark
                keep_path = False

                # If stroke exists and is dark, keep it
                if (
                    stroke_brightness is not None
                    and stroke_brightness < brightness_threshold
                ):
                    keep_path = True
                    logger.debug(
                        f"Keeping path with dark stroke: {stroke} (brightness: {stroke_brightness:.1f})"
                    )

                # If fill exists and is dark, keep it
                if (
                    fill_brightness is not None
                    and fill_brightness < brightness_threshold
                ):
                    keep_path = True
                    logger.debug(
                        f"Keeping path with dark fill: {fill} (brightness: {fill_brightness:.1f})"
                    )

                # If both are None or 'none', keep it (might be using parent styles)
                if stroke_brightness is None and fill_brightness is None:
                    keep_path = True
                    logger.debug(f"Keeping path with no explicit color")

                if keep_path:
                    filtered_paths.append(path)
                    filtered_attributes.append(attr)
                else:
                    logger.debug(
                        f"Removing bright path: stroke={stroke} (brightness: {stroke_brightness}), fill={fill} (brightness: {fill_brightness})"
                    )

            logger.info(
                f"Filtered {len(paths)} paths down to {len(filtered_paths)} dark paths"
            )

            if len(filtered_paths) == 0:
                logger.warning("All paths were filtered out! Returning original SVG.")
                return svg_path

            # Save filtered SVG
            output_path = tempfile.mktemp(suffix=".svg")
            wsvg(
                filtered_paths,
                attributes=filtered_attributes,
                svg_attributes=svg_attributes,
                filename=output_path,
            )

            return output_path

        except Exception as e:
            logger.error(f"Failed to filter SVG paths: {e}")
            # Return original if filtering fails
            return svg_path

    def process(self, input_path, params, job_info):
        """
        Processes an image to extract its centerline and convert it to SVG using autotrace.
        Expects a black-on-white line drawing or binary image.
        """
        if not os.path.exists(input_path):
            raise ValueError(f"Input path does not exist: {input_path}")

        # Autotrace params
        color_count = str(params.get("color_count", 2))
        despeckle_level = str(params.get("despeckle_level", 0))
        despeckle_tightness = str(params.get("despeckle_tightness", 2.0))
        corner_always_threshold = str(params.get("corner_always_threshold", 60))
        corner_surround = str(params.get("corner_surround", 4))
        corner_threshold = str(params.get("corner_threshold", 100))
        error_threshold = str(params.get("error_threshold", 2.0))
        filter_iterations = str(params.get("filter_iterations", 4))
        line_reversion_threshold = str(params.get("line_reversion_threshold", 0.01))
        line_threshold = str(params.get("line_threshold", 1.0))
        preserve_width = params.get("preserve_width", False)
        remove_adjacent_corners = params.get("remove_adjacent_corners", False)
        tangent_surround = str(params.get("tangent_surround", 3))
        width_weight_factor = str(params.get("width_weight_factor", 1.0))

        # Post-processing params
        filter_bright_paths = params.get("filter_bright_paths", True)
        brightness_threshold = params.get("brightness_threshold", 128)

        output_svg_path = tempfile.mktemp(suffix=".svg")
        filtered_svg_path = None

        try:
            command = [
                "autotrace",
                "--centerline",
                "--color-count",
                color_count,
                "--output-file",
                output_svg_path,
                "--output-format",
                "svg",
                "--despeckle-level",
                despeckle_level,
                "--despeckle-tightness",
                despeckle_tightness,
                "--corner-always-threshold",
                corner_always_threshold,
                "--corner-surround",
                corner_surround,
                "--corner-threshold",
                corner_threshold,
                "--error-threshold",
                error_threshold,
                "--filter-iterations",
                filter_iterations,
                "--line-reversion-threshold",
                line_reversion_threshold,
                "--line-threshold",
                line_threshold,
                "--tangent-surround",
                tangent_surround,
                "--width-weight-factor",
                width_weight_factor,
            ]

            if preserve_width:
                command.append("--preserve-width")
            if remove_adjacent_corners:
                command.append("--remove-adjacent-corners")

            command.append(input_path)

            logger.info(f"Running autotrace: {' '.join(command)}")
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Autotrace failed: {result.stderr}")
                raise RuntimeError(f"Autotrace failed: {result.stderr}")

            if not os.path.exists(output_svg_path):
                raise RuntimeError("Autotrace did not produce an output file")

            # Post-process to filter bright paths
            if filter_bright_paths:
                filtered_svg_path = self._filter_dark_paths(
                    output_svg_path, brightness_threshold
                )
                final_path = filtered_svg_path
            else:
                final_path = output_svg_path

            with open(final_path, "rb") as f:
                svg_content = f.read()

            final_output_path = self.save_hashed_file(svg_content, ".svg")
            return {"centerline": final_output_path}

        finally:
            if os.path.exists(output_svg_path):
                os.remove(output_svg_path)
            if filtered_svg_path and os.path.exists(filtered_svg_path):
                os.remove(filtered_svg_path)

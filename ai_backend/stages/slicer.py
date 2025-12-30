import os
import yaml
import numpy as np
import logging
from scipy.spatial import KDTree
from svgpathtools import svg2paths
from .base import BaseStage
import xml.etree.ElementTree as ET

logger = logging.getLogger("ai_backend.stages.slicer")


class YAMLUtils:
    """
    Helper to ensure data is clean native Python types before dumping to YAML.
    """

    @staticmethod
    def sanitize(obj):
        if isinstance(obj, dict):
            return {k: YAMLUtils.sanitize(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [YAMLUtils.sanitize(v) for v in obj]
        elif isinstance(obj, (np.integer, int)):
            return int(obj)
        elif isinstance(obj, (np.floating, float)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return YAMLUtils.sanitize(obj.tolist())
        elif isinstance(obj, (str, bool, type(None))):
            return obj
        else:
            return str(obj)


class SlicerStage(BaseStage):
    def __init__(self):
        super().__init__("slicer")
        self.valid_input_slugs = ["centerline", "extract_outline", "logo", "text"]

    def _rescale_points_to_bounds(
        self, points, original_bbox, target_center, max_dims, mode="auto"
    ):
        """
        Fits points into max_dims while maintaining aspect ratio,
        then centers them on target_center.
        The 'mode' parameter controls scaling:
        - 'auto': Scales content to fit inside max_dims.
        - 'repeat': Same as 'auto', used to indicate the bbox is from a prior run.
        - 'none': Assumes SVG units are mm and does not scale (scale=1.0).
        """
        if points.shape[0] == 0:
            return points
        min_x, min_y, max_x, max_y = original_bbox
        svg_width = max_x - min_x
        svg_height = max_y - min_y

        scale = 1.0
        if svg_width <= 0 or svg_height <= 0:
            pass  # Use scale=1.0 if there's no area
        else:
            target_w, target_h = max_dims
            if mode in ("auto", "repeat"):
                scale_x = target_w / svg_width
                scale_y = target_h / svg_height
                scale = min(scale_x, scale_y)
            elif mode == "none":
                scale = 1.0  # Treat SVG units as mm
            else:
                logger.warning(
                    f"Unknown resizing mode '{mode}', using 'none' (scale=1.0)."
                )
                scale = 1.0

        # 1. Normalize to 0,0 based on min and apply scale
        points_np = np.copy(
            np.array(points)
        )  # Use copy to avoid modifying original array
        points_np[:, 0] = (points_np[:, 0] - min_x) * scale
        points_np[:, 1] = (points_np[:, 1] - min_y) * scale

        # 2. Calculate new dimensions of the scaled object
        new_w = svg_width * scale
        new_h = svg_height * scale

        # 3. Calculate offsets to place center of object at target_center
        offset_x = target_center[0] - (new_w / 2)
        offset_y = target_center[1] - (new_h / 2)
        points_np[:, 0] += offset_x
        points_np[:, 1] += offset_y

        return points_np

    def _get_svg_dimensions(self, svg_path):
        """Extract viewBox or width/height from SVG file."""
        tree = ET.parse(svg_path)
        root = tree.getroot()
        try:
            return float(root.get("width")), float(root.get("height"))
        except Exception as e:
            return 1000, 120

    def _dist(self, p1, p2):
        return np.sqrt(np.sum((p1 - p2) ** 2))

    def _connect_nearby_paths(self, polylines, threshold_mm=0.5):
        if not polylines:
            return []
        logger.info(
            f"Attempting to merge {len(polylines)} independent lines (Threshold: {threshold_mm}mm)"
        )
        pool = [{"points": p, "valid": True} for p in polylines]
        merged_lines = []
        for i in range(len(pool)):
            if not pool[i]["valid"]:
                continue
            current_chain = pool[i]["points"]
            pool[i]["valid"] = False
            extended = True
            while extended:
                extended = False
                chain_end = current_chain[-1]
                best_idx = -1
                best_dist = float("inf")
                best_action = None
                for j in range(len(pool)):
                    if not pool[j]["valid"]:
                        continue
                    cand = pool[j]["points"]
                    start_pt = cand[0]
                    end_pt = cand[-1]
                    d_es = self._dist(chain_end, start_pt)
                    if d_es < best_dist:
                        best_dist = d_es
                        best_idx = j
                        best_action = "append"
                    d_ee = self._dist(chain_end, end_pt)
                    if d_ee < best_dist:
                        best_dist = d_ee
                        best_idx = j
                        best_action = "append_reversed"
                if best_dist <= threshold_mm and best_idx != -1:
                    candidate = pool[best_idx]["points"]
                    if best_action == "append_reversed":
                        candidate = candidate[::-1]
                    if best_dist < 0.05:
                        current_chain = np.vstack((current_chain, candidate[1:]))
                    else:
                        current_chain = np.vstack((current_chain, candidate))
                    pool[best_idx]["valid"] = False
                    extended = True
            merged_lines.append(current_chain)
        return merged_lines

    def _optimize_path_order_greedy(self, paths):
        if not paths:
            return []
        if len(paths) == 1:
            return paths
        logger.info(f"Sorting {len(paths)} paths using KDTree-assisted Greedy TSP...")
        endpoints = []
        for p in paths:
            endpoints.append(p[0])
            endpoints.append(p[-1])
        kdtree = KDTree(endpoints)
        visited = set()
        ordered_paths = []
        # Start closer to top-left of drawing area (approx 100, 150)
        current_pos = np.array([100.0, 150.0])
        while len(ordered_paths) < len(paths):
            k = min(len(endpoints), len(ordered_paths) + 50)
            dists, idxs = kdtree.query(current_pos, k=k)
            if not isinstance(idxs, (list, np.ndarray)):
                idxs = [idxs]
            found = False
            for idx in idxs:
                path_idx = idx // 2
                is_reverse = idx % 2 == 1
                if path_idx not in visited:
                    p = paths[path_idx]
                    if is_reverse:
                        p = p[::-1]
                    ordered_paths.append(p)
                    current_pos = p[-1]
                    visited.add(path_idx)
                    found = True
                    break
            if not found:
                for i in range(len(paths)):
                    if i not in visited:
                        ordered_paths.append(paths[i])
                        current_pos = paths[i][-1]
                        visited.add(i)
                        break
        return ordered_paths

    def process(self, input_path, params, job_info):
        if not os.path.exists(input_path):
            raise ValueError(f"Input path missing: {input_path}")
        # --- Coordinates & Params ---
        resizing_mode = params.get("resizing_mode", "auto")  # 'auto', 'repeat', 'none'
        # Machine Config
        motor_width = float(params.get("motor_width_mm", 400.0))
        home_distance = float(params.get("home_distance", 1000000))
        # Drawing Area defs
        area_left = float(params.get("area_left", 100.0))
        area_right = float(params.get("area_right", 300.0))
        area_top = float(params.get("area_top_mm", 150.0))
        area_bottom = float(params.get("area_bottom_mm", 350.0))
        # Scale content within the drawing area
        content_scale = float(params.get("scale", 1))
        # Calculation of drawing Box (Absolute Coords)
        abs_x_min = area_left
        abs_x_max = area_right
        abs_y_min = area_top
        abs_y_max = area_bottom
        draw_area_w = abs_x_max - abs_x_min
        draw_area_h = abs_y_max - abs_y_min
        center_x = abs_x_min + (draw_area_w / 2)
        center_y = abs_y_min + (draw_area_h / 2)
        graphic_max_w = draw_area_w * content_scale
        graphic_max_h = draw_area_h * content_scale
        # Pen Settings
        resolution_mm = float(params.get("resolution_mm", 0.5))
        min_width = float(params.get("min_width", 0.1))
        max_width = float(params.get("max_width", 1))
        taper_len = float(params.get("taper_length_mm", 20.0))
        connect_dist = float(params.get("connect_threshold_mm", 2.0))
        connect = params.get("connect", True)
        optimize = params.get("optimize", True)
        logger.info(
            f"Slicing with resizing_mode='{resizing_mode}' in area: [{abs_x_min}, {abs_y_min}] to [{abs_x_max}, {abs_y_max}] abs coords."
        )
        # 1. Load SVG and discretize into raw polylines
        paths, _ = svg2paths(input_path)
        if not paths:
            raise ValueError("SVG has no paths.")

        svg_width, svg_height = self._get_svg_dimensions(input_path)
        svg_dim_max = max(svg_width, svg_height)
        logger.info(f"SVG dimensions from file: {svg_width}x{svg_height}")

        raw_polylines = []
        target_dim_max = min(graphic_max_w, graphic_max_h)
        scale_est = target_dim_max / (svg_dim_max if svg_dim_max > 0 else 1)
        for path in paths:
            for segment in path:
                length = segment.length()
                if length <= 0:
                    continue
                spacing_svg = (
                    resolution_mm / scale_est
                    if resizing_mode != "none" and scale_est > 0
                    else resolution_mm
                )

                num_points = max(2, int(length / spacing_svg))
                pts = [
                    [p.real, p.imag]
                    for p in (segment.point(t) for t in np.linspace(0, 1, num_points))
                ]
                raw_polylines.append(np.array(pts))

        # 2. Determine source bounding box for scaling
        source_bbox = None
        if resizing_mode == "repeat":
            transform_info = None
            if "slicer" in job_info["results"]:
                previous_slicer_output = job_info["results"]["slicer"]
                if (
                    isinstance(previous_slicer_output, dict)
                    and "transform" in previous_slicer_output
                ):
                    transform_info = previous_slicer_output["transform"]

            if transform_info and "svg_bbox" in transform_info:
                source_bbox = tuple(transform_info["svg_bbox"])
                logger.info(
                    f"Using 'repeat' resizing mode with bbox from previous run: {source_bbox}"
                )
            else:
                logger.warning(
                    "Resizing mode is 'repeat' but no previous slicer transform found. Falling back to 'auto'."
                )
                resizing_mode = "auto"  # Fallback

        if resizing_mode in ("auto", "none"):
            all_points = np.vstack(raw_polylines) if raw_polylines else np.array([])
            if all_points.size == 0:
                source_bbox = (0, 0, 1, 1)
            else:
                w, h = self._get_svg_dimensions(input_path)
                source_bbox = (0, 0, w, h)

        # 3. Rescale and Center all polylines
        rescaled_lines = [
            self._rescale_points_to_bounds(
                line,
                source_bbox,
                (center_x, center_y),
                (graphic_max_w, graphic_max_h),
                resizing_mode,
            )
            for line in raw_polylines
        ]

        # 4. Connect and Sort
        final_lines = rescaled_lines
        if connect:
            final_lines = self._connect_nearby_paths(
                final_lines, threshold_mm=connect_dist
            )
        if optimize:
            final_lines = self._optimize_path_order_greedy(final_lines)

        # 5. Generate Data Structure and YAML
        yaml_lines, total_draw_dist, total_points = [], 0.0, 0
        for poly in final_lines:
            if poly.shape[0] < 2:
                continue
            points_data = []
            dists = np.sqrt(np.sum(np.diff(poly, axis=0) ** 2, axis=1))
            cum_dist = np.insert(np.cumsum(dists), 0, 0)
            total = cum_dist[-1]
            total_draw_dist += float(total)
            for k, (x, y) in enumerate(poly):
                d = min(cum_dist[k], total - cum_dist[k])
                factor = min(d / taper_len, 1.0) if taper_len > 0 else 1.0
                factor_smooth = factor * factor * (3 - 2 * factor)
                w = min_width + (max_width - min_width) * factor_smooth
                points_data.append(
                    {
                        "x": round(float(x), 2),
                        "y": round(float(y), 2),
                        "w": round(float(w), 2),
                    }
                )
            yaml_lines.append({"points": points_data, "length": round(float(total), 2)})
            total_points += len(points_data)

        output_data = {
            "metadata": {
                "units": "mm",
                "motor_width": motor_width,
                "drawing_bounds": [abs_x_min, abs_y_min, abs_x_max, abs_y_max],
                "line_count": len(yaml_lines),
                "total_distance_mm": round(total_draw_dist, 2),
                "point_count": total_points,
                "home_distance": home_distance,
            },
            "lines": yaml_lines,
        }

        sanitized_data = YAMLUtils.sanitize(output_data)
        logger.info(
            f"Slicing Result: {len(yaml_lines)} paths, {total_draw_dist:.0f}mm distance."
        )
        yaml_str = yaml.dump(sanitized_data, sort_keys=False, default_flow_style=None)
        output_filename = self.save_hashed_file(yaml_str.encode("utf-8"), ".yaml")

        # Prepare the transform data to be returned for potential 'repeat' use.
        transform_for_output = {"svg_bbox": list(source_bbox)}

        return {"slicer": output_filename, "transform": transform_for_output}

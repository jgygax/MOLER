import os
import cv2
import yaml
import logging
import numpy as np
import tempfile
from svgpathtools import svg2paths, wsvg
from PIL import Image
from .base import BaseStage
from utils import resize_and_pad

logger = logging.getLogger("ai_backend.stages.add_logo")

class AddLogoStage(BaseStage):
    def __init__(self):
        super().__init__("add_logo")
        self.valid_input_slugs = ["rmbg-mask", "slicer", "any"]
        self.logo_path = os.path.join(os.getcwd(), "assets", "logo.svg")

    def _get_collision_mask(self, job_info, target_size, content_size):
        """
        Creates a binary numpy grid (0=empty, 255=content) representing the current state 
        of the canvas to determine where to place the logo.
        """
        results = job_info.get("results", {})
        
        # 1. Try using RMBG mask (Best for images)
        if "rmbg" in results and "rmbg-mask" in results["rmbg"]:
            mask_path = results["rmbg"]["rmbg-mask"]
            if os.path.exists(mask_path):
                try:
                    img = Image.open(mask_path).convert("L")
                    
                    # Apply the same resize/pad logic as the rest of the pipeline
                    processed_img = resize_and_pad(
                        img, 
                        target_size=target_size, 
                        content_size=content_size, 
                        bg_color=0 # Black background for mask logic
                    )
                    
                    # Convert to numpy (White=Subject, Black=Background)
                    return np.array(processed_img)
                except Exception as e:
                    logger.warning(f"Failed to load rmbg mask: {e}")

        # 2. Try using Slicer YAML output (Best for vector/drawing flows)
        slicer_result = results.get("slicer")
        if slicer_result:
            yaml_path = slicer_result if isinstance(slicer_result, str) else slicer_result.get("slicer")
            if yaml_path and os.path.exists(yaml_path):
                try:
                    with open(yaml_path, 'r') as f:
                        data = yaml.safe_load(f)
                    
                    # Create empty grid
                    grid = np.zeros((target_size, target_size), dtype=np.uint8)
                    
                    # Extract bounds to map mm coordinates back to pixels
                    meta = data.get("metadata", {})
                    bounds = meta.get("drawing_bounds", [0, 0, 100, 100])
                    min_x, min_y = bounds[0], bounds[1]
                    max_x, max_y = bounds[2], bounds[3]
                    
                    width_mm = max_x - min_x
                    height_mm = max_y - min_y
                    
                    # Prevent div by zero
                    if width_mm <= 0: width_mm = 1
                    if height_mm <= 0: height_mm = 1
                    
                    # Calculate scale
                    scale_x = target_size / width_mm
                    scale_y = target_size / height_mm
                    scale = min(scale_x, scale_y) # Keep aspect ratio
                    
                    # Draw lines onto grid
                    for line in data.get("lines", []):
                        points = line.get("points", [])
                        if len(points) < 2: continue
                        
                        pts_list = []
                        for p in points:
                            # Normalize coord to 0..target_size
                            px = int((p["x"] - min_x) * scale)
                            py = int((p["y"] - min_y) * scale)
                            pts_list.append([px, py])
                        
                        cv2.polylines(grid, [np.array(pts_list)], False, 255, thickness=5)
                    
                    return grid
                except Exception as e:
                    logger.warning(f"Failed to parse slicer output for collision detection: {e}")

        # Default: Empty grid
        return np.zeros((target_size, target_size), dtype=np.uint8)

    def _determine_position(self, mask, location, target_size, logo_w_px, logo_h_px, margin_px):
        """
        Returns the (x, y) coordinates for the top-left of the logo.
        """
        # Ensure coordinates are within bounds
        safe_w = max(0, target_size - logo_w_px - margin_px)
        safe_h = max(0, target_size - logo_h_px - margin_px)
        
        corners = {
            "top-left": (margin_px, margin_px),
            "top-right": (safe_w, margin_px),
            "bottom-left": (margin_px, safe_h),
            "bottom-right": (safe_w, safe_h)
        }

        if location != "auto":
            return corners.get(location, corners["bottom-right"])

        # Auto Mode: Find corner with least content intersection and furthest from content
        best_corner = "bottom-right" # Default fallback
        min_collision = float('inf')
        max_dist_to_content = -1

        # Distance transform: value is distance to nearest zero (empty) pixel.
        # We want to measure space. 
        # Invert mask: 0=Content, 255=Empty
        inv_mask = cv2.bitwise_not(mask)
        # distanceTransform calculates distance to nearest zero pixel (the content)
        dist_map = cv2.distanceTransform(inv_mask, cv2.DIST_L2, 5)

        for name, (x, y) in corners.items():
            x, y = int(x), int(y)
            # Define logo ROI (Region of Interest)
            x2 = min(x + int(logo_w_px), target_size)
            y2 = min(y + int(logo_h_px), target_size)
            
            # Extract region where logo would go
            if x2 > x and y2 > y:
                roi_mask = mask[y:y2, x:x2]
                
                # Sum of pixels (255) in the ROI - strictly checks for overlap with content
                collision_score = np.sum(roi_mask)
                
                # Average distance to content in this area (higher is better = more whitespace)
                roi_dist = dist_map[y:y2, x:x2]
                avg_dist = np.mean(roi_dist) if roi_dist.size > 0 else 0
            else:
                collision_score = float('inf')
                avg_dist = 0

            logger.debug(f"Corner {name}: Collision={collision_score}, AvgDist={avg_dist:.1f}")

            # Priority 1: Zero collision. Priority 2: Further from content.
            # Using a small tolerance for collision
            if collision_score < min_collision:
                min_collision = collision_score
                max_dist_to_content = avg_dist
                best_corner = name
            elif collision_score == min_collision:
                if avg_dist > max_dist_to_content:
                    max_dist_to_content = avg_dist
                    best_corner = name

        logger.info(f"Auto-selected placement: {best_corner}")
        return corners[best_corner]

    def process(self, input_path, params, job_info):
        location = params.get("location", "auto") # top-left, top-right, bottom-left, bottom-right, auto
        target_size = int(params.get("target_size", 1024))
        content_size = int(params.get("content_size", 1024))
        logo_size_mm = float(params.get("logo_size_mm", 40.0))
        drawing_width_mm = float(params.get("drawing_width_mm", 300.0)) # Approx width of drawing area for scaling
        margin_mm = float(params.get("margin_mm", 5.0))

        if not os.path.exists(self.logo_path):
            raise FileNotFoundError(f"Logo asset missing at {self.logo_path}")

        # 1. Load Logo SVG paths
        # svg2paths loads paths and attributes from the SVG
        paths, attributes = svg2paths(self.logo_path)
        if not paths:
            raise ValueError("Logo SVG contains no paths")

        # 2. Calculate Scaling
        # Map real world MM to pixels based on the target coordinate system.
        px_per_mm = target_size / drawing_width_mm
        
        logo_target_w_px = logo_size_mm * px_per_mm
        margin_px = margin_mm * px_per_mm

        # Get current logic bounding box (scan points)
        min_x, max_x, min_y, max_y = 0, 0, 0, 0
        all_points = []
        for path in paths:
            if len(path) == 0: continue
            # Sample path to find bounds
            try:
                for seg in path:
                    all_points.extend([seg.point(t) for t in np.linspace(0, 1, 5)])
            except Exception:
                pass
        
        if all_points:
            x_coords = [p.real for p in all_points]
            y_coords = [p.imag for p in all_points]
            min_x, max_x = min(x_coords), max(x_coords)
            min_y, max_y = min(y_coords), max(y_coords)
        
        current_w = max_x - min_x
        current_h = max_y - min_y
        
        if current_w <= 0: current_w = 1 
        
        scale_factor = logo_target_w_px / current_w
        logo_h_px = current_h * scale_factor

        # 3. Determine Placement
        mask = self._get_collision_mask(job_info, target_size, content_size)
        pos_x, pos_y = self._determine_position(
            mask, location, target_size, logo_target_w_px, logo_h_px, margin_px
        )

        # 4. Transform Paths and Filter Attributes
        final_paths = []
        final_attrs = []
        
        # Offsets
        origin_offset = complex(-min_x, -min_y)
        final_translation = complex(pos_x, pos_y)

        for path, attr in zip(paths, attributes):
            # Transform Path
            # 1. Translate to 0,0
            p = path.translated(origin_offset)
            # 2. Scale
            p = p.scaled(scale_factor)
            # 3. Translate to final position
            p = p.translated(final_translation)
            
            final_paths.append(p)
            
            # Filter Attributes
            # Remove keys with colons (Namespaces like inkscape: or sodipodi:) to prevent XML errors
            safe_attr = {}
            for k, v in attr.items():
                if ":" not in k:
                    safe_attr[k] = v
            final_attrs.append(safe_attr)

        # 5. Output SVG
        svg_attributes = {
            "width": f"{target_size}",
            "height": f"{target_size}",
            "viewBox": f"0 0 {target_size} {target_size}",
            "xmlns": "http://www.w3.org/2000/svg"
        }

        # Use temp file to let wsvg write the XML
        tmp_svg = tempfile.mktemp(suffix=".svg")
        try:
            wsvg(
                final_paths, 
                attributes=final_attrs, 
                svg_attributes=svg_attributes, 
                filename=tmp_svg
            )
            
            with open(tmp_svg, "rb") as f:
                content = f.read()
            
            output_path = self.save_hashed_file(content, ".svg")
            return {"logo": output_path}
            
        finally:
            if os.path.exists(tmp_svg):
                os.remove(tmp_svg)
import cv2
import numpy as np
import logging
from .base import BaseStage

logger = logging.getLogger("ai_backend.stages.subtract")


class SubtractStage(BaseStage):
    def __init__(self):
        super().__init__("subtract")
        self.valid_input_slugs = ["any"]

    def process(self, input_path, params, job_info):
        """
        1. Scales and Translates the positive (drawing) to perfectly overlap the negative.
        2. Dilates the aligned negative (outline).
        3. Subtracts to remove the outer boundary.
        """
        # --- 1. Load Inputs ---
        slug_pos = params.get("positive_slug")  # The detailed drawing
        slug_neg = params.get("negative_slug", "extract_outline")
        results = job_info.get("results", {})
        # Resolve Positive Path
        path_pos = input_path
        if slug_pos and slug_pos in results:
            path_pos = results[slug_pos]
            if isinstance(path_pos, dict):
                path_pos = list(path_pos.values())[0]
        # Resolve Negative Path
        path_neg = None
        if slug_neg in results:
            path_neg = results[slug_neg]
            if isinstance(path_neg, dict):
                path_neg = list(path_neg.values())[0]
        if not path_neg:
            raise ValueError(
                f"Subtraction failed: Could not find result for slug '{slug_neg}'"
            )
        # Load as Grayscale
        img_pos = cv2.imread(path_pos, cv2.IMREAD_GRAYSCALE)
        img_neg = cv2.imread(path_neg, cv2.IMREAD_GRAYSCALE)
        if img_pos is None:
            raise ValueError(f"Could not read positive: {path_pos}")
        if img_neg is None:
            raise ValueError(f"Could not read negative: {path_neg}")
        # --- 2. Invert (Work with White Lines on Black BG) ---
        target_h, target_w = img_neg.shape[:2]  # Use negative dimensions as target
        pos_inv = cv2.bitwise_not(img_pos)
        neg_inv = cv2.bitwise_not(img_neg)
        # --- 3. Crop Positive to Content ---
        points = cv2.findNonZero(pos_inv)
        pos_crop_x, pos_crop_y = 0, 0
        if points is not None:
            x, y, w, h = cv2.boundingRect(points)
            pad = 2
            x = max(0, x - pad)
            y = max(0, y - pad)
            w = min(img_pos.shape[1] - x, w + pad * 2)
            h = min(img_pos.shape[0] - y, h + pad * 2)
            pos_cropped = pos_inv[y : y + h, x : x + w]
            pos_crop_x, pos_crop_y = x, y
        else:
            pos_cropped = pos_inv
        # --- 4. Multi-Scale Template Matching (BEFORE dilation) ---
        logger.info("Auto-aligning drawing to outline...")
        pad_amounts = int(max(target_h, target_w) * 0.5)
        neg_padded = cv2.copyMakeBorder(
            neg_inv,
            pad_amounts,
            pad_amounts,
            pad_amounts,
            pad_amounts,
            cv2.BORDER_CONSTANT,
            value=0,
        )
        base_h = target_h
        aspect_ratio = (
            pos_cropped.shape[1] / pos_cropped.shape[0]
            if pos_cropped.shape[0] > 0
            else 1.0
        )
        best_val = -1
        best_img = None
        best_loc = (0, 0)
        best_scale = 1.0
        scales = np.linspace(0.8, 1.2, 20)
        for scale in scales:
            new_h = int(base_h * scale)
            new_w = int(new_h * aspect_ratio)
            if new_h <= 0 or new_w <= 0:
                continue
            resized_template = cv2.resize(
                pos_cropped, (new_w, new_h), interpolation=cv2.INTER_LINEAR
            )
            if (
                resized_template.shape[0] > neg_padded.shape[0]
                or resized_template.shape[1] > neg_padded.shape[1]
            ):
                continue
            res = cv2.matchTemplate(neg_padded, resized_template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
            if max_val > best_val:
                best_val = max_val
                best_img = resized_template
                best_loc = max_loc
                best_scale = scale
        logger.info(
            f"Best alignment found: Confidence={best_val:.3f}, Scale={best_scale:.3f}"
        )
        # --- 5. Reconstruct Aligned Positive Image ---
        aligned_pos = np.zeros((target_h, target_w), dtype=np.uint8)
        if best_img is not None:
            start_x = best_loc[0] - pad_amounts
            start_y = best_loc[1] - pad_amounts
            c_x1 = max(0, start_x)
            c_y1 = max(0, start_y)
            c_x2 = min(target_w, start_x + best_img.shape[1])
            c_y2 = min(target_h, start_y + best_img.shape[0])
            t_x1 = c_x1 - start_x
            t_y1 = c_y1 - start_y
            t_x2 = c_x2 - start_x
            t_y2 = c_y2 - start_y
            if c_x2 > c_x1 and c_y2 > c_y1:
                aligned_pos[c_y1:c_y2, c_x1:c_x2] = best_img[t_y1:t_y2, t_x1:t_x2]
        # --- 6. Dilate Negative AFTER alignment ---
        dilation = params.get("dilation_pixels", 13)
        if dilation > 0:
            kernel = np.ones((3, 3), np.uint8)
            neg_inv = cv2.dilate(neg_inv, kernel, iterations=dilation)
        # --- 7. Subtract ---
        result_inv = cv2.subtract(aligned_pos, neg_inv)
        # --- 8. Save Debug Image ---
        final_img = cv2.cvtColor(cv2.bitwise_not(result_inv), cv2.COLOR_GRAY2BGR)
        subtracted_mask = cv2.bitwise_and(neg_inv, aligned_pos)
        final_img[subtracted_mask > 0] = [255, 200, 200]
        output_path = self.save_hashed_file(
            cv2.imencode(".png", final_img)[1].tobytes(), ".png"
        )
        return {"subtract": output_path}
    
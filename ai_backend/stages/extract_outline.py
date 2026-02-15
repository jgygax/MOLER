import cv2
import numpy as np
import logging
from PIL import Image
from .base import BaseStage
from utils import resize_and_pad

logger = logging.getLogger("ai_backend.stages.extract_outline")


class ExtractOutlineStage(BaseStage):
    def __init__(self):
        super().__init__("extract_outline")
        self.valid_input_slugs = ["rmbg-mask"]

    def process(self, input_path, params, job_info):
        target_size = params.get("target_size", 1024)
        content_size = params.get("content_size", 1000)
        thickness = params.get("thickness", 2)

        # Load mask as grayscale
        mask = cv2.imread(input_path, cv2.IMREAD_GRAYSCALE)
        if mask is None:
            raise ValueError(f"Could not read mask from {input_path}")

        # Find contours
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_TC89_L1
        )

        # Create white canvas for outline
        outline = np.ones_like(mask) * 255

        # Draw contours smoothly
        # -1 means draw all contours, 0 is black, thickness is line width
        cv2.drawContours(
            outline, contours, -1, (0), thickness=thickness, lineType=cv2.LINE_AA
        )

        # Remove outlines touching the very edge of the cropped mask
        # this avoids straight lines where the subject was cut off at the image edge
        h, w = outline.shape
        margin = thickness * 2
        cv2.rectangle(outline, (0, 0), (w - 1, h - 1), (255), thickness=margin)

        # Convert back to PIL for utility functions
        outline_pil = Image.fromarray(outline).convert("RGB")

        # Now resize and pad the outline to match the final composited image
        final_outline = resize_and_pad(
            outline_pil,
            target_size=target_size,
            content_size=content_size,
            bg_color=(255, 255, 255),
        )

        output_path = self.save_hashed_image(final_outline)
        return {"outline": output_path}

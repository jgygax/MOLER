import numpy as np
import logging
from PIL import Image

logger = logging.getLogger("ai_backend.utils")


def crop_to_content(img, mask, padding=5):
    """
    Crops an image based on the non-zero pixels in the mask.
    """
    mask_np = np.array(mask)
    coords = np.argwhere(mask_np > 0)
    if len(coords) == 0:
        logger.warning("No content found in mask!")
        return img, (0, 0, img.width, img.height)

    y_min, x_min = coords.min(axis=0)
    y_max, x_max = coords.max(axis=0)

    y_min = max(0, y_min - padding)
    x_min = max(0, x_min - padding)
    y_max = min(mask_np.shape[0] - 1, y_max + padding)
    x_max = min(mask_np.shape[1] - 1, x_max + padding)

    bbox = (int(x_min), int(y_min), int(x_max + 1), int(y_max + 1))
    return img.crop(bbox), bbox


def resize_and_pad(img, target_size=1024, content_size=1000, bg_color=(255, 255, 255)):
    """
    Resizes the image so its longest side is content_size, then pads to target_size x target_size.
    """
    w, h = img.size
    scale = content_size / max(w, h)
    new_w, new_h = int(w * scale), int(h * scale)

    img_resized = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new(img.mode, (target_size, target_size), bg_color)
    offset = ((target_size - new_w) // 2, (target_size - new_h) // 2)
    canvas.paste(img_resized, offset)
    return canvas

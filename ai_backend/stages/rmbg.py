import os
import torch
import numpy as np
import logging
from PIL import Image
from torchvision import transforms
from transformers import AutoModelForImageSegmentation
from .base import BaseStage
from utils import crop_to_content, resize_and_pad

logger = logging.getLogger("ai_backend.stages.rmbg")


class RmbgStage(BaseStage):
    def __init__(self):
        super().__init__("rmbg")
        self.valid_input_slugs = ["original"]
        self.model = None
        self.device = "cuda"
        self.image_size = (1024, 1024)
        self.transform_image = transforms.Compose(
            [
                transforms.Resize(self.image_size),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )
        self._ensure_model_loaded()

    def _ensure_model_loaded(self):
        if self.model is not None:
            return

        logger.info(f"Loading model briaai/RMBG-2.0 on {self.device}...")
        token = os.getenv("HF_TOKEN")

        self.model = AutoModelForImageSegmentation.from_pretrained(
            "briaai/RMBG-2.0",
            trust_remote_code=True,
            token=token,
            cache_dir="/app/.huggingface-cache",
        )

        torch.set_float32_matmul_precision("high")

        if self.device == "cuda":
            self.model.to(device=self.device, dtype=torch.float16)
        else:
            self.model.to(self.device)

        self.model.eval()

    def process(self, input_path, params, job_info):
        self._ensure_model_loaded()

        target_size = params.get("target_size", 1024)
        content_size = params.get("content_size", 1024)

        image = Image.open(input_path).convert("RGB")

        dtype = torch.float16 if self.device == "cuda" else torch.float32
        input_images = (
            self.transform_image(image).unsqueeze(0).to(device=self.device, dtype=dtype)
        )

        with torch.inference_mode():
            preds = self.model(input_images)[-1].sigmoid().cpu()
        pred = preds[0].squeeze().numpy()

        # Convert to mask matching original image size
        mask = (pred > 0.5).astype(np.uint8) * 255
        mask_img = Image.fromarray(mask).resize(image.size, Image.NEAREST)

        # Composite subject onto white background
        mask_bool = np.array(mask_img) > 128
        subject_np = np.array(image)
        white_bg = np.ones_like(subject_np) * 255
        composited = np.where(mask_bool[..., None], subject_np, white_bg)
        composited_img = Image.fromarray(composited.astype(np.uint8))

        # Crop to content
        mask_cropped, _ = crop_to_content(mask_img, mask_img)
        composited_cropped, _ = crop_to_content(composited_img, mask_img)

        # Resize and pad ONLY the composited image
        # Mask stays cropped but unscaled for better outline extraction later
        final_composited = resize_and_pad(
            composited_cropped, target_size=target_size, content_size=content_size
        )

        mask_path = self.save_hashed_image(mask_cropped, extension="_mask.png")
        composited_path = self.save_hashed_image(final_composited)

        return {"rmbg": composited_path, "rmbg-mask": mask_path}

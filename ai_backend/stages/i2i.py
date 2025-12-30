import os
import json
import random
import logging
import tempfile
from PIL import Image
from .base import BaseStage
from comfy_client import ComfyUIClient
from utils import resize_and_pad

logger = logging.getLogger("ai_backend.stages.i2i")


class I2IStage(BaseStage):
    def __init__(self):
        super().__init__("i2i")
        # Accepts original uploads, rmbg outputs, or essentially anything
        self.valid_input_slugs = ["original", "rmbg"]

        # Configuration
        self.workflow_path = os.path.join(os.getcwd(), "workflows", "i2i.json")
        self.comfy_url = os.getenv("COMFY_URL", "http://host.docker.internal:8188")
        self.client = ComfyUIClient(self.comfy_url)

    def process(self, input_path, params, job_info):
        """
        Runs the image-to-image workflow via ComfyUI.
        """
        # 1. Parse Parameters
        target_size = int(
            params.get("target_size", 1024)
        )  # The size of the canvas/latent
        content_size = int(
            params.get("content_size", 1024)
        )  # The size of the subject within that canvas
        user_prompt = params.get("prompt", "")
        negative_prompt = params.get("negative_prompt", "")
        if params.get("seed") == "random":
            seed = random.randint(1, 10000000000)
        else:
            seed = int(params.get("seed", 42))
        denoise = float(params.get("denoise", 1.0))
        steps = int(params.get("steps", 4))

        logger.info(
            f"Preparing I2I: Target={target_size}, Content={content_size}, Seed={seed}"
        )

        # 2. Pre-process Image (Resize and Pad)
        # We need to take the input (which might be raw or rmbg output) and
        # center it on a white background of target_size.
        try:
            input_image = Image.open(input_path).convert("RGBA")

            # Use utility from rmbg stage logic to center/pad
            processed_image = resize_and_pad(
                input_image, target_size=target_size, content_size=content_size
            )

            # Convert to RGB (Comfy LoadImage prefers standard formats)
            # Create white background for alpha channel if exists
            background = Image.new("RGB", processed_image.size, (255, 255, 255))
            background.paste(processed_image, mask=processed_image.split()[3])
            final_input = background

        except Exception as e:
            logger.error(f"Error processing input image: {e}")
            raise ValueError(f"Failed to process input image: {e}")

        # 3. Upload to ComfyUI
        # We save to a temporary file first to upload
        temp_input_filename = f"i2i_input_{job_info['job_id']}.png"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = os.path.join(temp_dir, temp_input_filename)
            final_input.save(temp_path)

            # Upload
            self.client.upload_image(temp_path, temp_input_filename)

        # 4. Load and Modify Workflow
        if not os.path.exists(self.workflow_path):
            raise FileNotFoundError(f"Workflow file not found: {self.workflow_path}")

        with open(self.workflow_path, "r") as f:
            workflow = json.load(f)

        # Node IDs identified from your workflows/i2i.json:
        # 3: KSampler (seed, steps, denoise)
        # 78: LoadImage (image file)
        # 101: Positive Prompt (TextEncodeQwenImageEditPlus)
        # 102: Negative Prompt
        # 107: EmptySD3LatentImage (width, height)
        # 60: SaveImage (Output)

        # -- Set Latent Size (Node 107) --
        if "107" in workflow:
            workflow["107"]["inputs"]["width"] = content_size
            workflow["107"]["inputs"]["height"] = content_size

        # -- Set Input Image (Node 78) --
        if "78" in workflow:
            workflow["78"]["inputs"]["image"] = temp_input_filename

        # -- Set Sampler Params (Node 3) --
        if "3" in workflow:
            workflow["3"]["inputs"]["seed"] = seed
            workflow["3"]["inputs"]["denoise"] = denoise
            workflow["3"]["inputs"]["steps"] = steps

        # -- Set Prompts (Node 101 & 102) --
        # Default style prompt from your JSON
        default_style = "Transform into Q版风格 — chibi style, extremely simplified features, with flat colors, thick black lines and white background."

        if "101" in workflow:
            # If user provided a prompt, we can choose to replace it or append it.
            # Here, if user provides a prompt, we assume they want to control it,
            # otherwise we fall back to the default style.
            # Alternatively, you could do: f"{user_prompt}, {default_style}"
            final_prompt = user_prompt if user_prompt else default_style
            workflow["101"]["inputs"]["prompt"] = final_prompt

        if "102" in workflow and negative_prompt:
            workflow["102"]["inputs"]["prompt"] = negative_prompt

        # 5. Execute Workflow
        logger.info("Queuing workflow to ComfyUI...")

        # We implement a custom run execution here instead of client.run_workflow
        # so we don't have to save the modified JSON to disk first or rely on strict node mappings
        try:
            queued = self.client.queue_prompt(workflow)
            prompt_id = queued["prompt_id"]

            history = self.client.wait_for_prompt_completion(prompt_id)

            # 6. Retrieve Result
            node_outputs = history["outputs"]

            # Find output for Node 60 (SaveImage)
            if "60" not in node_outputs:
                raise RuntimeError("Workflow did not output an image on Node 60")

            image_outputs = node_outputs["60"]["images"]
            if not image_outputs:
                raise RuntimeError("No images generated.")

            output_info = image_outputs[0]
            image_data = self.client.get_image_data(
                output_info["filename"], output_info["subfolder"], output_info["type"]
            )

            # 7. Save Result locally
            output_path = self.save_hashed_file(image_data, ".png")
            return {"i2i": output_path}

        except Exception as e:
            logger.error(f"ComfyUI execution failed: {e}")
            raise RuntimeError(f"ComfyUI execution failed: {e}")

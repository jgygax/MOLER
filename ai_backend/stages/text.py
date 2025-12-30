import os
import logging
import tempfile
from .base import BaseStage
from handwriting import HandwritingGenerator

logger = logging.getLogger("ai_backend.stages.text")


class TextStage(BaseStage):
    def __init__(self):
        super().__init__("text")
        # Text generation creates new content, so it can theoretically
        # accept any previous artifact as a placeholder trigger.
        self.valid_input_slugs = ["any"]
        self.model = None

    def _ensure_model_loaded(self):
        if self.model is not None:
            return

        logger.info(f"Loading HandwritingGenerator")
        try:
            self.model = HandwritingGenerator()
        except Exception as e:
            logger.error(f"Failed to load HandwritingGenerator: {e}")
            raise e

    def process(self, input_path, params, job_info):
        """
        Generates handwritten text as SVG.
        Ignores input_path content, but uses parameters for generation.
        """
        self._ensure_model_loaded()

        # Extract parameters with defaults based on your stub
        text_content = params.get("text", "")
        if not text_content:
            raise ValueError("Parameter 'text' is required for TextStage")

        width = float(params.get("width", 50))
        align_mode = params.get("align", "center")  # left, center, right
        style = int(params.get("style", 1))

        # Temp file for generation
        temp_output = tempfile.mktemp(suffix=".svg")

        try:
            logger.info(
                f"Generating text (style={style}, align={align_mode}, width={width})"
            )

            self.model.generate(
                text=text_content,
                filename=temp_output,
                width=width,
                align_mode=align_mode,
                style=style,
            )

            if not os.path.exists(temp_output):
                raise RuntimeError(
                    "Handwriting generation failed to produce an output file"
                )

            # Read the generated SVG content
            with open(temp_output, "rb") as f:
                svg_content = f.read()

            # Save using the standard hashing mechanism
            final_output_path = self.save_hashed_file(svg_content, ".svg")

            return {"text": final_output_path}

        except Exception as e:
            logger.error(f"Error during text generation: {e}")
            raise e

        finally:
            # Cleanup temp file
            if os.path.exists(temp_output):
                os.remove(temp_output)

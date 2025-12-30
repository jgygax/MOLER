import os
import hashlib


class BaseStage:
    def __init__(self, name):
        self.name = name
        self.output_dir = os.path.join(os.getcwd(), "results", self.name)
        os.makedirs(self.output_dir, exist_ok=True)
        self.valid_input_slugs = ["any"]

    def process(self, input_path, params, job_info):
        """
        To be implemented by subclasses.
        Should return a dictionary of {slug: path} for the results.
        Example: {'rmbg-mask': '/path/to/mask.png'}
        """
        raise NotImplementedError

    def save_hashed_file(self, content_bytes, extension):
        file_hash = hashlib.md5(content_bytes).hexdigest()
        filename = f"{file_hash}{extension}"
        output_path = os.path.join(self.output_dir, filename)

        if not os.path.exists(output_path):
            with open(output_path, "wb") as f:
                f.write(content_bytes)

        return output_path

    def save_hashed_image(self, pil_image, extension=".png"):
        import io

        buf = io.BytesIO()
        # Get format from extension (e.g. .png or _mask.png)
        ext_part = extension.split(".")[-1].upper()
        if ext_part == "JPG":
            ext_part = "JPEG"

        pil_image.save(buf, format=ext_part)
        return self.save_hashed_file(buf.getvalue(), extension)

import requests
import json
import uuid
import time
import os
import logging

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class ComfyUIClient:
    def __init__(self, server_address):
        self.server_address = server_address

    def upload_image(self, local_path: str, filename: str) -> dict:
        """Uploads an image to the ComfyUI server."""
        logging.info(f"Uploading image '{local_path}' as '{filename}' to ComfyUI...")
        with open(local_path, "rb") as file:
            files = {"image": (filename, file)}
            data = {"overwrite": "true"}
            response = requests.post(
                f"{self.server_address}/upload/image", files=files, data=data
            )
            response.raise_for_status()
            logging.info("Image uploaded successfully.")
            return response.json()

    def queue_prompt(self, prompt_workflow: dict) -> dict:
        """Queues a prompt workflow for execution."""
        client_id = str(uuid.uuid4())
        prompt_data = {"prompt": prompt_workflow, "client_id": client_id}
        response = requests.post(f"{self.server_address}/prompt", json=prompt_data)
        print(response.text)
        response.raise_for_status()
        result = response.json()
        logging.info(f"Prompt queued with ID: {result['prompt_id']}")
        return result

    def get_history(self, prompt_id: str) -> dict:
        """Retrieves the execution history for a given prompt ID."""
        response = requests.get(f"{self.server_address}/history/{prompt_id}")
        response.raise_for_status()
        return response.json()

    def get_image_data(self, filename: str, subfolder: str, image_type: str) -> bytes:
        """Downloads an image from the ComfyUI output directory."""
        params = {"filename": filename, "subfolder": subfolder, "type": image_type}
        response = requests.get(f"{self.server_address}/view", params=params)
        response.raise_for_status()
        logging.info(f"Downloaded image: {filename}")
        return response.content

    def wait_for_prompt_completion(self, prompt_id: str):
        """Polls the history until the prompt execution is complete."""
        while True:
            try:
                history = self.get_history(prompt_id)
                if prompt_id in history and history[prompt_id].get("outputs"):
                    logging.info(f"Prompt {prompt_id} completed.")
                    return history[prompt_id]
            except Exception as e:
                logging.warning(
                    f"Error checking history for {prompt_id}, will retry. Error: {e}"
                )
            time.sleep(1)

    def run_workflow(
        self, workflow_path: str, replacements: dict, output_node_id: str
    ) -> bytes:
        """
        Loads a workflow, applies replacements, runs it, and returns the final image data.
        """
        # Load workflow
        with open(workflow_path, "r") as f:
            workflow = json.load(f)

        # Apply replacements (e.g., input image, prompt)
        for node_id, fields in replacements.items():
            for field, value in fields.items():
                workflow[node_id]["inputs"][field] = value

        # Queue prompt and wait
        queued_prompt = self.queue_prompt(workflow)
        prompt_id = queued_prompt["prompt_id"]
        history = self.wait_for_prompt_completion(prompt_id)

        # Get output image
        output_data = history["outputs"][output_node_id]["images"][0]
        image_data = self.get_image_data(
            filename=output_data["filename"],
            subfolder=output_data["subfolder"],
            image_type=output_data["type"],
        )
        return image_data

import os
import hashlib
import logging
from cache_manager import cache_manager

logger = logging.getLogger("ai_backend.orchestrator")


class Orchestrator:
    def __init__(self):
        self.stages = {}

    def register_stage(self, name, stage_instance):
        self.stages[name] = stage_instance

    def run(self, job_info, locks):
        # Initialize artifacts with the original input
        if "artifacts" not in job_info:
            job_info["artifacts"] = []

        # Add original input as 'original' slug if not present
        if not any(a["slug"] == "original" for a in job_info["artifacts"]):
            image_hash = os.path.basename(job_info["input_path"]).split(".")[0]
            job_info["artifacts"].append(
                {
                    "slug": "original",
                    "path": job_info["input_path"],
                    "hash": image_hash,
                    "timestamp": 0,  # Earliest
                }
            )

        workflow = job_info["workflow"]

        for step in workflow:
            stage_name = step["stage"]
            params = step.get("params", {})

            if stage_name not in self.stages:
                raise ValueError(f"Unknown stage: {stage_name}")

            stage = self.stages[stage_name]
            valid_slugs = stage.valid_input_slugs

            # Find the most recent valid artifact
            input_artifact = self._find_best_input(job_info["artifacts"], valid_slugs)
            if not input_artifact:
                raise ValueError(
                    f"No valid input artifact found for stage {stage_name} with slugs {valid_slugs}"
                )

            input_path = input_artifact["path"]
            logger.info(
                f"Running stage {stage_name} for job {job_info['job_id']} using input {input_path} (slug: {input_artifact['slug']})"
            )

            # Caching check
            cache_key = self._generate_cache_key(input_path, stage_name, params)
            cached_result = cache_manager.get(cache_key)

            if (
                cached_result
                and isinstance(cached_result, dict)
                and all(
                    not isinstance(p, str) or os.path.exists(p)
                    for p in cached_result.values()
                )
            ):
                logger.info(f"Using cached result for {stage_name} (key: {cache_key})")
                outputs = cached_result
            else:
                # Stage locking if required
                lock = locks.get(stage_name)
                if lock:
                    logger.debug(f"Acquiring lock for {stage_name}")
                    with lock:
                        outputs = stage.process(input_path, params, job_info)
                else:
                    outputs = stage.process(input_path, params, job_info)

                # Standardize outputs to dict if it's a single path string
                if isinstance(outputs, str):
                    outputs = {f"{stage_name}-output": outputs}

                cache_manager.set(cache_key, outputs)

            # Update job_info
            job_info["results"][stage_name] = outputs
            for slug, path in outputs.items():
                if isinstance(path, dict):
                    continue
                file_hash = os.path.basename(path).split(".")[0]
                job_info["artifacts"].append(
                    {
                        "slug": slug,
                        "path": path,
                        "hash": file_hash,
                        "timestamp": len(job_info["artifacts"]),  # Simple ordering
                    }
                )

            job_info["current_stage"] = stage_name

    def _find_best_input(self, artifacts, valid_slugs):
        if "any" in valid_slugs:
            # For 'any', we prefer the most recent artifact overall,
            # but usually 'rmbg' wants the 'original' if not specified otherwise.
            # Let's say 'any' means 'most recent'.
            return sorted(artifacts, key=lambda x: x["timestamp"], reverse=True)[0]

        logger.info([a["slug"] for a in artifacts])
        # Filter artifacts matching valid_slugs
        valid_artifacts = [a for a in artifacts if a["slug"] in valid_slugs]
        if not valid_artifacts:
            return None

        # Return most recent
        return sorted(valid_artifacts, key=lambda x: x["timestamp"], reverse=True)[0]

    def _generate_cache_key(self, input_path, stage_name, params):
        with open(input_path, "rb") as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
        param_str = str(sorted(params.items()))
        logger.debug(f"Generating cache key for {input_path} {stage_name} {param_str}")
        return hashlib.md5(f"{file_hash}_{stage_name}_{param_str}".encode()).hexdigest()


orchestrator = Orchestrator()

# Register stages
from stages.add_logo import AddLogoStage
from stages.rmbg import RmbgStage
from stages.i2i import I2IStage
from stages.centerline import CenterlineStage
from stages.slicer import SlicerStage
from stages.extract_outline import ExtractOutlineStage
from stages.cleanup import CleanupStage
from stages.visualizer import VisualizerStage
from stages.subtract import SubtractStage
from stages.text import TextStage

orchestrator.register_stage("add_logo", AddLogoStage())
orchestrator.register_stage("rmbg", RmbgStage())
orchestrator.register_stage("extract_outline", ExtractOutlineStage())
orchestrator.register_stage("cleanup", CleanupStage())
orchestrator.register_stage("i2i", I2IStage())
orchestrator.register_stage("centerline", CenterlineStage())
orchestrator.register_stage("slicer", SlicerStage())
orchestrator.register_stage("visualizer", VisualizerStage())
orchestrator.register_stage("subtract", SubtractStage())
orchestrator.register_stage("text", TextStage())

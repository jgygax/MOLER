import json
import os
import logging
from threading import Lock

logger = logging.getLogger("ai_backend.job_store")


class JobStore:
    def __init__(self, filepath="jobs.json"):
        self.filepath = filepath
        self.lock = Lock()
        self.jobs = {}
        self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    self.jobs = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load jobs from {self.filepath}: {e}")
                self.jobs = {}
        else:
            self.jobs = {}

    def _save(self):
        try:
            with open(self.filepath, "w") as f:
                json.dump(self.jobs, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save jobs to {self.filepath}: {e}")

    def add_job(self, job_info):
        with self.lock:
            self.jobs[job_info["job_id"]] = job_info
            self._save()

    def update_job(self, job_id, updates):
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].update(updates)
                self._save()
            else:
                logger.warning(f"Attempted to update non-existent job: {job_id}")

    def get_job(self, job_id):
        with self.lock:
            return self.jobs.get(job_id)

    def get_all_jobs(self):
        with self.lock:
            return list(self.jobs.values())


job_store = JobStore()

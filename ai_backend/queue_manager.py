import threading
import queue
import time
import logging
from orchestrator import orchestrator
from job_store import job_store

logger = logging.getLogger("ai_backend.queue")


class QueueManager:
    def __init__(self):
        self.priority_queue = queue.PriorityQueue()
        self.locks = {"rmbg": threading.Lock(), "i2i": threading.Lock()}
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()
        logger.info("Queue worker started")

        # Re-queue pending jobs on startup
        self._requeue_pending_jobs()

    def _requeue_pending_jobs(self):
        jobs = job_store.get_all_jobs()
        for job in jobs:
            if job.get("status") == "queued":
                self.priority_queue.put((job.get("priority", 10), job["job_id"]))
                logger.info(f"Re-queued pending job {job['job_id']}")

    def add_job(self, job_info):
        job_id = job_info["job_id"]
        job_info["status"] = "queued"
        job_store.add_job(job_info)
        # PriorityQueue sorts low to high, so we negate priority if we want higher number to be higher priority
        # Or just use the number if 0 is highest. Let's assume lower number = higher priority for now.
        self.priority_queue.put((job_info.get("priority", 10), job_id))
        logger.info(
            f"Job {job_id} added to queue with priority {job_info.get('priority', 10)}"
        )

    def get_job(self, job_id):
        return job_store.get_job(job_id)

    def get_all_jobs(self):
        return job_store.get_all_jobs()

    def _worker(self):
        while True:
            try:
                priority, job_id = self.priority_queue.get(timeout=1)
                job_info = job_store.get_job(job_id)
                if job_info:
                    logger.info(f"Processing job {job_id}")
                    job_store.update_job(job_id, {"status": "processing"})
                    try:
                        orchestrator.run(job_info, self.locks)
                        job_store.update_job(
                            job_id,
                            {
                                "status": "completed",
                                "results": job_info.get("results", {}),
                                "artifacts": job_info.get("artifacts", []),
                            },
                        )
                        logger.info(f"Job {job_id} completed successfully")
                    except Exception as e:
                        logger.exception(f"Error processing job {job_id}: {e}")
                        job_store.update_job(
                            job_id, {"status": "failed", "error": str(e)}
                        )
                self.priority_queue.task_done()
            except queue.Empty:
                continue


queue_manager = QueueManager()

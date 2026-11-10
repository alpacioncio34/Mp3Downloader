"""Cola de descargas en segundo plano con progreso consultable."""
import atexit
import os
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import media


class Job:
    def __init__(self, url, mode, quality):
        self.id = uuid.uuid4().hex
        self.url, self.mode, self.quality = url, mode, quality
        self.status = "queued"  # queued | downloading | processing | done | error
        self.progress = 0.0
        self.title = None
        self.path = None
        self.filename = None
        self.error = None
        self.tmp = tempfile.mkdtemp(prefix="descarga-")
        self.touched = time.time()
        self.future = None

    @property
    def finished(self):
        return self.status in ("done", "error")

    def update(self, status=None, progress=None, title=None):
        if status:
            self.status = status
        if progress is not None:
            self.progress = progress
        if title:
            self.title = title

    def public(self):
        return {
            "id": self.id,
            "status": self.status,
            "progress": round(self.progress, 3),
            "title": self.title,
            "filename": self.filename,
            "error": self.error,
        }


class QueueFull(Exception):
    pass


class JobManager:
    def __init__(self, workers=3, max_active=8, ttl=15 * 60):
        self._jobs = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers)
        self._max_active = max_active
        self._ttl = ttl
        atexit.register(self._cleanup_all)

    def create(self, url, mode, quality):
        self._reap()
        with self._lock:
            if sum(not j.finished for j in self._jobs.values()) >= self._max_active:
                raise QueueFull
            job = Job(url, mode, quality)
            self._jobs[job.id] = job
        job.future = self._pool.submit(self._run, job)
        return job

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
        if job:
            job.touched = time.time()
        return job

    def _run(self, job):
        try:
            path, title = media.download(job.url, job.mode, job.quality, job.tmp, job.update)
            job.path = path
            job.title = title or job.title
            job.filename = media.safe_filename(job.title, os.path.splitext(path)[1].lstrip("."))
            job.progress = 1.0
            job.status = "done"
        except media.MediaError as e:
            job.error, job.status = str(e), "error"
        except Exception as e:  # noqa: BLE001 - se informa al usuario
            job.error, job.status = f"Error inesperado: {e}", "error"
        finally:
            job.touched = time.time()
            if job.status == "error":
                shutil.rmtree(job.tmp, ignore_errors=True)

    def _reap(self):
        """Borra los trabajos terminados que nadie ha tocado en `ttl` segundos."""
        limit = time.time() - self._ttl
        with self._lock:
            old = [j for j in self._jobs.values() if j.finished and j.touched < limit]
            for j in old:
                del self._jobs[j.id]
        for j in old:
            shutil.rmtree(j.tmp, ignore_errors=True)

    def _cleanup_all(self):
        self._pool.shutdown(wait=False, cancel_futures=True)
        for j in list(self._jobs.values()):
            shutil.rmtree(j.tmp, ignore_errors=True)

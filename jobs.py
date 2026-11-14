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
    def __init__(self, url, mode, quality, clip=None):
        self.id = uuid.uuid4().hex
        self.url, self.mode, self.quality, self.clip = url, mode, quality, clip
        # queued | downloading | clipping | processing | done | error | cancelled
        self.status = "queued"
        self.progress = 0.0
        self.speed = None
        self.eta = None
        self.title = None
        self.path = None
        self.filename = None
        self.size = None
        self.error = None
        self.cancelled = False
        self.tmp = tempfile.mkdtemp(prefix="descarga-")
        self.touched = time.time()
        self.future = None

    @property
    def finished(self):
        return self.status in ("done", "error", "cancelled")

    def update(self, status=None, progress=None, title=None, speed=None, eta=None):
        """Lo llama media.download; lanzar aquí Cancelled aborta la descarga."""
        if self.cancelled:
            raise media.Cancelled
        if status:
            self.status = status
        if progress is not None:
            self.progress = progress
        if title:
            self.title = title
        self.speed, self.eta = speed, eta

    def public(self):
        # Una cancelación pedida se muestra ya, aunque el hilo tarde en enterarse.
        cancelled = self.cancelled and self.status != "done"
        return {
            "id": self.id,
            "status": "cancelled" if cancelled else self.status,
            "progress": round(self.progress, 3),
            "speed": self.speed,
            "eta": self.eta,
            "title": self.title,
            "filename": self.filename,
            "size": self.size,
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
        # Limpieza periódica: los vídeos largos no deben quedarse ocupando disco.
        threading.Thread(target=self._reap_forever, daemon=True).start()

    def create(self, url, mode, quality, clip=None):
        with self._lock:
            if sum(not j.finished for j in self._jobs.values()) >= self._max_active:
                raise QueueFull
            job = Job(url, mode, quality, clip)
            self._jobs[job.id] = job
        job.future = self._pool.submit(self._run, job)
        return job

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
        if job:
            job.touched = time.time()
        return job

    def cancel(self, job_id):
        """Marca el trabajo como cancelado; el hilo se detiene en su siguiente aviso."""
        job = self.get(job_id)
        if job and not job.finished:
            job.cancelled = True
            if job.future.cancel():  # seguía en cola: no llegará a ejecutarse
                job.status = "cancelled"
                shutil.rmtree(job.tmp, ignore_errors=True)
        return job

    def _run(self, job):
        try:
            if job.cancelled:
                raise media.Cancelled
            path, title = media.download(
                job.url, job.mode, job.quality, job.tmp, job.update, job.clip)
            if job.cancelled:
                raise media.Cancelled
            job.path = path
            job.size = os.path.getsize(path)
            job.title = title or job.title
            job.filename = media.safe_filename(job.title, os.path.splitext(path)[1].lstrip("."))
            job.progress = 1.0
            job.status = "done"
        except media.Cancelled:
            job.status = "cancelled"
        except media.MediaError as e:
            job.error, job.status = str(e), "error"
        except Exception as e:  # noqa: BLE001 - se informa al usuario
            job.error, job.status = f"Error inesperado: {e}", "error"
        finally:
            job.touched = time.time()
            if job.status != "done":
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

    def _reap_forever(self):
        while True:
            time.sleep(60)
            self._reap()

    def _cleanup_all(self):
        self._pool.shutdown(wait=False, cancel_futures=True)
        for j in list(self._jobs.values()):
            shutil.rmtree(j.tmp, ignore_errors=True)

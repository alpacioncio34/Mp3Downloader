import os

from flask import Flask, jsonify, render_template, request, send_file

import media
from jobs import JobManager, QueueFull

app = Flask(__name__)
jobs = JobManager()


@app.errorhandler(media.MediaError)
def media_error(e):
    return jsonify(error=str(e)), 400


@app.get("/")
def index():
    return render_template("index.html", modes=media.MODES)


@app.get("/api/info")
def info():
    url = request.args.get("url", "").strip()
    media.validate(url, "video", None)
    return jsonify(media.fetch_info(url))


def _create_job(data):
    url = (data.get("url") or "").strip()
    mode, quality = media.validate(url, data.get("mode") or "audio", data.get("quality"))
    return jobs.create(url, mode, quality)


@app.post("/api/jobs")
def create_job():
    try:
        job = _create_job(request.get_json(silent=True) or {})
    except QueueFull:
        return jsonify(error="Hay demasiadas descargas en marcha. Prueba en un momento."), 429
    return jsonify(job.public()), 202


@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify(error="Descarga caducada o inexistente"), 404
    return jsonify(job.public())


def _send(job):
    return send_file(job.path, as_attachment=True, download_name=job.filename)


@app.get("/api/jobs/<job_id>/file")
def job_file(job_id):
    job = jobs.get(job_id)
    if not job or job.status != "done" or not os.path.exists(job.path):
        return jsonify(error="El archivo ya no está disponible"), 404
    return _send(job)


@app.get("/download")
def download():
    """Descarga directa y bloqueante: es lo que usa el formulario sin JavaScript."""
    try:
        job = _create_job(request.args)
    except QueueFull:
        return jsonify(error="Hay demasiadas descargas en marcha."), 429
    job.future.result()
    if job.status != "done":
        return jsonify(error=job.error), 400
    return _send(job)


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )

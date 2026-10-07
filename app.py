import os
import re
import shutil
import tempfile
from io import BytesIO

import yt_dlp
from flask import Flask, jsonify, render_template, request, send_file

app = Flask(__name__)


def limpiar_error(e):
    """Quita códigos de color y el prefijo 'ERROR:' de los mensajes de yt-dlp."""
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e))
    return re.sub(r"^ERROR:\s*", "", msg).strip() or "Error desconocido"


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/info")
def info():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify(error="Falta el enlace"), 400
    try:
        opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            j = ydl.extract_info(url, download=False)
        return jsonify(
            title=j.get("title"),
            thumbnail=j.get("thumbnail"),
            duration=j.get("duration"),
            author=j.get("uploader"),
        )
    except yt_dlp.utils.DownloadError as e:
        return jsonify(error=limpiar_error(e)), 400
    except Exception as e:
        return jsonify(error=f"Error inesperado: {e}"), 500


@app.get("/download")
def download():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify(error="Falta el enlace"), 400

    tmp = tempfile.mkdtemp()
    try:
        opts = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "outtmpl": os.path.join(tmp, "%(id)s.%(ext)s"),
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)

        ruta = os.path.join(tmp, f"{info['id']}.mp3")
        if not os.path.exists(ruta):
            raise FileNotFoundError("No se generó el MP3 (¿está ffmpeg instalado?)")

        with open(ruta, "rb") as f:
            datos = BytesIO(f.read())

        return send_file(
            datos,
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name=f"{info.get('title') or 'audio'}.mp3",
        )
    except yt_dlp.utils.DownloadError as e:
        return jsonify(error=limpiar_error(e)), 400
    except Exception as e:
        return jsonify(error=f"Error inesperado: {e}"), 500
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

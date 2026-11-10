"""Catálogo de modalidades y toda la lógica de yt-dlp / ffmpeg."""
import os
import re
import subprocess
from urllib.parse import urlparse

import yt_dlp

PLATFORMS = {
    "YouTube": ("youtube.com", "youtu.be"),
    "TikTok": ("tiktok.com",),
    "Instagram": ("instagram.com",),
}

_VIDEO_QUALITIES = [
    {"id": "best", "label": "Máxima"},
    {"id": "1080", "label": "1080p"},
    {"id": "720", "label": "720p"},
    {"id": "480", "label": "480p"},
    {"id": "360", "label": "360p"},
]

# Única fuente de verdad: el frontend recibe este mismo diccionario.
MODES = {
    "video": {
        "label": "Vídeo",
        "desc": "Imagen y sonido",
        "noun": "el vídeo",
        "tag": "MP4",
        "default": "best",
        "qualities": _VIDEO_QUALITIES,
    },
    "audio": {
        "label": "Audio",
        "desc": "Solo el sonido",
        "noun": "el audio",
        "tag": "",
        "default": "mp3-192",
        "qualities": [
            {"id": "mp3-320", "label": "MP3 320 kbps"},
            {"id": "mp3-192", "label": "MP3 192 kbps"},
            {"id": "mp3-128", "label": "MP3 128 kbps"},
            {"id": "m4a", "label": "M4A"},
            {"id": "wav", "label": "WAV"},
        ],
    },
    "mute": {
        "label": "Mudo",
        "desc": "Solo la imagen",
        "noun": "la imagen",
        "tag": "MP4 sin sonido",
        "default": "best",
        "qualities": _VIDEO_QUALITIES,
    },
}


class MediaError(Exception):
    """Error que se puede mostrar tal cual al usuario."""


def platform_of(url):
    """Nombre de la plataforma si el enlace es http(s) y de un dominio admitido."""
    try:
        p = urlparse(url)
        host = (p.hostname or "").lower()
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not host:
        return None
    for name, domains in PLATFORMS.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return name
    return None


def validate(url, mode, quality):
    """Devuelve (mode, quality) normalizados o lanza MediaError."""
    if not url:
        raise MediaError("Falta el enlace")
    if not platform_of(url):
        raise MediaError("Ese enlace no es de YouTube, TikTok ni Instagram.")
    if mode not in MODES:
        raise MediaError("Modalidad no válida")
    ids = [q["id"] for q in MODES[mode]["qualities"]]
    return mode, quality if quality in ids else MODES[mode]["default"]


def _clean(e):
    """Quita códigos de color y el prefijo 'ERROR:' de los mensajes de yt-dlp."""
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e))
    return re.sub(r"^ERROR:\s*", "", msg).strip() or "Error desconocido"


def safe_filename(title, ext):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", title or "")
    name = re.sub(r"\s+", " ", name).strip(" .")[:120] or "descarga"
    return f"{name}.{ext}"


_BASE = {"quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True}


def fetch_info(url):
    try:
        with yt_dlp.YoutubeDL({**_BASE, "skip_download": True}) as ydl:
            j = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise MediaError(_clean(e)) from e

    # "Resolución" = lado corto, para que un vertical 1080x1920 cuente como 1080p.
    sizes = [
        min(f["width"], f["height"])
        for f in j.get("formats") or []
        if f.get("vcodec") not in (None, "none") and f.get("width") and f.get("height")
    ]
    return {
        "title": j.get("title"),
        "thumbnail": j.get("thumbnail"),
        "duration": j.get("duration"),
        "author": j.get("uploader") or j.get("channel"),
        "platform": platform_of(url),
        "max_res": max(sizes) if sizes else None,
    }


def _options(mode, quality, tmp):
    opts = {**_BASE, "outtmpl": os.path.join(tmp, "%(id)s.%(ext)s")}

    if mode == "audio":
        codec, _, kbps = quality.partition("-")
        pp = {"key": "FFmpegExtractAudio", "preferredcodec": codec}
        if kbps:
            pp["preferredquality"] = kbps
        opts.update(format="bestaudio/best", postprocessors=[pp])
        return opts

    # Vídeo: la mayor resolución que no supere la pedida y, a igualdad,
    # H.264 + AAC, que se reproduce en cualquier sitio.
    res = "res" if quality == "best" else f"res:{quality}"
    opts["format_sort"] = [res, "vcodec:h264", "acodec:aac"]
    if mode == "video":
        opts.update(
            format="bv*+ba/b",
            merge_output_format="mp4",
            postprocessors=[{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
        )
    else:  # mute: la pista de audio se quita después con ffmpeg
        opts["format"] = "bv*/b"
    return opts


def _strip_audio(src):
    dst = os.path.splitext(src)[0] + ".mudo.mp4"
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", src,
         "-an", "-c:v", "copy", "-movflags", "+faststart", dst],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not os.path.exists(dst):
        raise MediaError("ffmpeg no pudo quitar el audio: " + (r.stderr.strip()[-300:] or "error"))
    return dst


def download(url, mode, quality, tmp, on_progress=lambda **kw: None):
    """Descarga en `tmp` y devuelve (ruta, título).

    on_progress recibe status ('downloading' | 'processing'), progress (0-1) y title.
    """
    opts = _options(mode, quality, tmp)
    state = {"done": 0, "parts": 1}

    def hook(d):
        if d["status"] == "finished":
            state["done"] += 1
            frac = 0
        elif d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            frac = min(d.get("downloaded_bytes", 0) / total, 1) if total else 0
        else:
            return
        on_progress(status="downloading",
                    progress=min((state["done"] + frac) / state["parts"], 1))

    def pp_hook(d):
        if d["status"] == "started":
            on_progress(status="processing", progress=1)

    opts["progress_hooks"] = [hook]
    opts["postprocessor_hooks"] = [pp_hook]

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            state["parts"] = len(info.get("requested_formats") or [1])
            on_progress(status="downloading", progress=0, title=info.get("title"))
            info = ydl.process_ie_result(info, download=True)
    except yt_dlp.utils.DownloadError as e:
        raise MediaError(_clean(e)) from e

    files = [d.get("filepath") for d in info.get("requested_downloads") or []]
    path = next((f for f in files if f and os.path.exists(f)), None)
    if not path:
        raise MediaError("No se generó el archivo (¿está ffmpeg instalado?)")

    if mode == "mute":
        on_progress(status="processing", progress=1)
        path = _strip_audio(path)

    return path, info.get("title")

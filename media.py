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
    "X": ("x.com", "twitter.com"),
    "Facebook": ("facebook.com", "fb.watch"),
    "Vimeo": ("vimeo.com",),
    "Twitch": ("twitch.tv",),
    "SoundCloud": ("soundcloud.com",),
}
UNSUPPORTED = "Enlace no admitido. Vale de: " + ", ".join(PLATFORMS) + "."

# Límite de duración en segundos (0 = sin límite) y cookies opcionales para yt-dlp.
MAX_DURATION = int(os.environ.get("MAX_DURATION", "0") or 0)
COOKIES = os.environ.get("YTDLP_COOKIES") or None

_VIDEO_QUALITIES = [
    {"id": "best", "label": "Máxima"},
    {"id": "2160", "label": "4K"},
    {"id": "1440", "label": "1440p"},
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
            {"id": "opus", "label": "Opus"},
            {"id": "flac", "label": "FLAC"},
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
    "thumb": {
        "label": "Portada",
        "desc": "La miniatura",
        "noun": "la portada",
        "tag": "",
        "default": "jpg",
        "qualities": [{"id": "jpg", "label": "JPG"}],
    },
}


class MediaError(Exception):
    """Error que se puede mostrar tal cual al usuario."""


class Cancelled(Exception):
    """El usuario canceló la descarga; se lanza desde on_progress."""


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
        raise MediaError(UNSUPPORTED)
    if mode not in MODES:
        raise MediaError("Modalidad no válida")
    ids = [q["id"] for q in MODES[mode]["qualities"]]
    return mode, quality if quality in ids else MODES[mode]["default"]


def parse_time(value):
    """'90', '1:30' o '1:02:03.5' -> segundos (None si viene vacío)."""
    if value is None or str(value).strip() == "":
        return None
    parts = str(value).strip().replace(",", ".").split(":")
    try:
        if len(parts) > 3:
            raise ValueError
        t = 0.0
        for p in parts:
            t = t * 60 + float(p)
    except ValueError:
        raise MediaError(f"Tiempo no válido: «{value}». Usa mm:ss o h:mm:ss.") from None
    if not 0 <= t < 10**7:  # también descarta NaN e infinito
        raise MediaError(f"Tiempo no válido: «{value}».")
    return t


def parse_clip(start, end):
    """Devuelve (inicio, fin) en segundos, o None si no se pide recorte."""
    start, end = parse_time(start), parse_time(end)
    if not start and end is None:
        return None
    start = start or 0.0
    if end is not None and end <= start:
        raise MediaError("El final del recorte tiene que ir después del inicio.")
    return start, end if end is not None else float("inf")


def _clean(e):
    """Quita códigos de color y el prefijo 'ERROR:' de los mensajes de yt-dlp."""
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e))
    return re.sub(r"^ERROR:\s*", "", msg).strip() or "Error desconocido"


def safe_filename(title, ext):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", title or "")
    name = re.sub(r"\s+", " ", name).strip(" .")[:120] or "descarga"
    return f"{name}.{ext}"


_BASE = {"quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True}
if COOKIES:
    _BASE["cookiefile"] = COOKIES


def _is_video(f):
    return f.get("vcodec") not in (None, "none") and f.get("width") and f.get("height")


def _sizes(formats, duration):
    """Tamaño aproximado en bytes de cada calidad: {modalidad: {calidad: bytes}}."""
    def size(f):
        return f.get("filesize") or f.get("filesize_approx") or (
            f["tbr"] * 125 * duration if f.get("tbr") and duration else None)

    videos = [(min(f["width"], f["height"]), f) for f in formats if _is_video(f)]
    audios = [f for f in formats
              if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
    best_audio = max(audios, key=lambda f: f.get("abr") or f.get("tbr") or 0, default=None)
    a = size(best_audio) if best_audio else None

    out = {"video": {}, "mute": {}, "audio": {}}
    for q in _VIDEO_QUALITIES:
        cap = float("inf") if q["id"] == "best" else int(q["id"])
        fits = [(r, f) for r, f in videos if r <= cap]
        if not fits:
            continue
        top = max(r for r, _ in fits)
        # Mismo criterio que format_sort: a igual resolución, H.264 primero.
        f = max((f for r, f in fits if r == top),
                key=lambda f: (str(f.get("vcodec")).startswith("avc1"), f.get("tbr") or 0))
        v = size(f)
        if v:
            separate = f.get("acodec") in (None, "none")
            out["video"][q["id"]] = int(v + (a or 0 if separate else 0))
            out["mute"][q["id"]] = int(v)
    if duration:
        for kbps in (320, 192, 128):
            out["audio"][f"mp3-{kbps}"] = int(kbps * 125 * duration)
        out["audio"]["wav"] = int(1411 * 125 * duration)
    if a:
        out["audio"]["m4a"] = out["audio"]["opus"] = int(a)
    return out


def fetch_info(url):
    try:
        with yt_dlp.YoutubeDL({**_BASE, "skip_download": True}) as ydl:
            j = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise MediaError(_clean(e)) from e

    # "Resolución" = lado corto, para que un vertical 1080x1920 cuente como 1080p.
    formats = j.get("formats") or []
    sizes = [min(f["width"], f["height"]) for f in formats if _is_video(f)]
    return {
        "title": j.get("title"),
        "thumbnail": j.get("thumbnail"),
        "duration": j.get("duration"),
        "author": j.get("uploader") or j.get("channel"),
        "platform": platform_of(url),
        "max_res": max(sizes) if sizes else None,
        "live": bool(j.get("is_live")),
        "sizes": _sizes(formats, j.get("duration")),
    }


_METADATA = {"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True}
_COVER_CODECS = ("mp3", "m4a", "opus", "flac")


def _options(mode, quality, tmp, clip=None):
    opts = {**_BASE, "outtmpl": os.path.join(tmp, "%(id)s.%(ext)s")}

    if mode == "thumb":
        opts.update(skip_download=True, writethumbnail=True)
        return opts

    if clip:
        opts["download_ranges"] = yt_dlp.utils.download_range_func(None, [clip])
        opts["force_keyframes_at_cuts"] = True  # corte exacto, no al fotograma clave

    if mode == "audio":
        codec, _, kbps = quality.partition("-")
        pp = {"key": "FFmpegExtractAudio", "preferredcodec": codec}
        if kbps:
            pp["preferredquality"] = kbps
        pps = [pp]
        if codec != "wav":
            pps.append(_METADATA)  # título, autor, fecha
        if codec in _COVER_CODECS:
            # La miniatura como carátula, en JPG para que no pese más que el audio.
            opts["writethumbnail"] = True
            pps.insert(0, {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
            pps.append({"key": "EmbedThumbnail"})
        opts.update(format="bestaudio/best", postprocessors=pps)
        return opts

    # Vídeo: la mayor resolución que no supere la pedida y, a igualdad,
    # H.264 + AAC, que se reproduce en cualquier sitio.
    res = "res" if quality == "best" else f"res:{quality}"
    opts["format_sort"] = [res, "vcodec:h264", "acodec:aac"]
    if mode == "video":
        opts.update(
            format="bv*+ba/b",
            merge_output_format="mp4",
            postprocessors=[{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}, _METADATA],
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


def _to_jpg(tmp):
    """Localiza la miniatura descargada en `tmp` y la deja en JPG."""
    images = [os.path.join(tmp, n) for n in sorted(os.listdir(tmp))
              if n.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
    if not images:
        raise MediaError("Este vídeo no tiene miniatura.")
    src = images[0]
    if src.lower().endswith((".jpg", ".jpeg")):
        return src
    dst = os.path.splitext(src)[0] + ".jpg"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-q:v", "2", dst],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise MediaError("ffmpeg no pudo convertir la miniatura.")
    return dst


def _check_length(info, mode, clip):
    if info.get("is_live"):
        raise MediaError("Los directos en emisión no se pueden descargar.")
    if mode == "thumb":
        return
    dur = info.get("duration")
    if clip and dur and clip[0] >= dur:
        raise MediaError("El recorte empieza después del final del vídeo.")
    length = min(clip[1], dur or clip[1]) - clip[0] if clip else dur
    if MAX_DURATION and length and length > MAX_DURATION:
        raise MediaError(
            f"Demasiado largo: el máximo son {MAX_DURATION // 60} min. Prueba a recortarlo.")


def download(url, mode, quality, tmp, on_progress=lambda **kw: None, clip=None):
    """Descarga en `tmp` y devuelve (ruta, título).

    on_progress recibe status ('downloading' | 'clipping' | 'processing'),
    progress (0-1), title, speed (bytes/s) y eta (s). Si lanza Cancelled, se aborta.
    `clip` es (inicio, fin) en segundos para bajar solo ese tramo.
    """
    if mode == "thumb":
        clip = None
    opts = _options(mode, quality, tmp, clip)
    state = {"done": 0, "parts": 1}
    # Los recortes los baja ffmpeg, que no informa del total: progreso indeterminado.
    active = "clipping" if clip else "downloading"

    def hook(d):
        if d["status"] == "finished":
            state["done"] += 1
            frac = 0
        elif d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            frac = min(d.get("downloaded_bytes", 0) / total, 1) if total else 0
        else:
            return
        on_progress(status=active,
                    progress=min((state["done"] + frac) / state["parts"], 1),
                    speed=d.get("speed"), eta=d.get("eta"))

    def pp_hook(d):
        if d["status"] == "started":
            on_progress(status="processing", progress=1)

    opts["progress_hooks"] = [hook]
    opts["postprocessor_hooks"] = [pp_hook]

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            _check_length(info, mode, clip)
            state["parts"] = len(info.get("requested_formats") or [1])
            on_progress(status=active, progress=0, title=info.get("title"))
            info = ydl.process_ie_result(info, download=True)
    except yt_dlp.utils.DownloadError as e:
        raise MediaError(_clean(e)) from e

    if mode == "thumb":
        return _to_jpg(tmp), info.get("title")

    files = [d.get("filepath") for d in info.get("requested_downloads") or []]
    path = next((f for f in files if f and os.path.exists(f)), None)
    if not path:
        raise MediaError("No se generó el archivo (¿está ffmpeg instalado?)")

    if mode == "mute":
        on_progress(status="processing", progress=1)
        path = _strip_audio(path)

    return path, info.get("title")

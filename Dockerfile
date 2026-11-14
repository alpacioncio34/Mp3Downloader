FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# yt-dlp cambia a menudo: --upgrade para llevar siempre la última al reconstruir.
RUN pip install --no-cache-dir --upgrade -r requirements.txt
COPY . .

RUN useradd --create-home saca
USER saca

ENV PORT=8000
EXPOSE 8000

# Un solo proceso: la cola de descargas vive en memoria. La concurrencia va por hilos.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 16 --timeout 0 app:app"]

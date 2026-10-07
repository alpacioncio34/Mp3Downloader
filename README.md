# Mp3 Downloader

A small Flask web app that extracts the audio (MP3) from short videos: YouTube Shorts, Instagram Reels, TikTok and any other site supported by [yt-dlp](https://github.com/yt-dlp/yt-dlp).

Paste a link, press **Download MP3**, and the file is saved by your browser.

## Requirements

- Python 3.9+
- [ffmpeg](https://ffmpeg.org/) installed and available in your PATH

## Setup

```bash
cd shorts-mp3
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Install ffmpeg if you don't have it:

```bash
sudo apt install ffmpeg         # Debian/Ubuntu
brew install ffmpeg             # macOS
winget install ffmpeg           # Windows
```

## Run

```bash
python3 app.py
```

Open http://localhost:5000. To use it from your phone on the same Wi-Fi, open `http://YOUR-PC-IP:5000`, this may give some issues due to networks and firewalls, not its intended use.

## Project structure

```
shorts-mp3/
├── app.py              Flask server and routes
└── templates/
    └── index.html      Single-page interface
```

## Routes

| Route | Description |
|-------|-------------|
| `GET /` | Web interface |
| `GET /info?url=...` | Returns JSON with `title`, `thumbnail`, `duration`, `author` |
| `GET /download?url=...` | Returns the audio as an MP3 file |

Errors are returned as `{"error": "message"}` and shown in red below the input.

## Disclaimer

Downloading content from these platforms may violate their terms of service. Use it only with your own content or with permission from the owner.

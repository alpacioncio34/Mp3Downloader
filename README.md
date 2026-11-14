# saca.

Descarga vídeo, audio o la portada de un enlace de YouTube, TikTok, Instagram, X,
Facebook, Vimeo, Twitch o SoundCloud. Backend en Flask + yt-dlp + ffmpeg; la interfaz
es una PWA que se instala en el móvil.

## Qué hace

- **Vídeo** (MP4, hasta 4K), **Audio** (MP3 320/192/128, M4A, Opus, FLAC, WAV),
  **Mudo** (vídeo sin sonido) y **Portada** (miniatura en JPG).
- **Vídeos largos**: sin límite por defecto, con tamaño aproximado antes de descargar,
  velocidad y tiempo restante, botón de cancelar, y la descarga se retoma si se recarga
  la página o el móvil cierra la pestaña.
- **Recorte**: baja solo un tramo (`Desde` / `Hasta`, en `mm:ss` o `h:mm:ss`).
- El audio lleva título, autor y la miniatura como carátula.

## Ejecutar en local

Hace falta Python 3.10+ y `ffmpeg` en el PATH.

```bash
pip install -r requirements.txt
python app.py            # http://localhost:5000
```

## Desplegar

```bash
docker build -t saca .
docker run -d --name saca -p 8000:8000 --restart unless-stopped saca
```

La imagen sirve para cualquier hosting de contenedores (un VPS, Fly.io, Railway,
Render…). A tener en cuenta:

- **Un solo proceso.** La cola de descargas vive en memoria, así que gunicorn va con
  `--workers 1` e hilos (ya viene así en el `Dockerfile`). No escalar a varias instancias.
- **HTTPS obligatorio** para instalarla como app y para el botón «Pegar». Pon delante
  un proxy con certificado (Caddy, Cloudflare Tunnel, o el que traiga el hosting).
- **Disco temporal.** Los archivos se guardan en `/tmp` y se borran a los 15 minutos de
  terminar. Un vídeo largo en 4K puede ocupar varios GB.
- **YouTube bloquea muchas IP de centros de datos** («Sign in to confirm you're not a
  bot»). En un servidor de casa o una IP residencial no pasa; en la nube puede hacer
  falta `YTDLP_COOKIES`.
- Reconstruye la imagen de vez en cuando: yt-dlp necesita estar al día para seguir
  funcionando.

| Variable        | Por defecto | Para qué                                                    |
|-----------------|-------------|-------------------------------------------------------------|
| `PORT`          | 8000 (Docker) / 5000 | Puerto de escucha                                  |
| `MAX_DURATION`  | `0`         | Duración máxima en segundos (`0` = sin límite). Con recorte cuenta el tramo. |
| `YTDLP_COOKIES` | —           | Ruta a un `cookies.txt` (formato Netscape) para yt-dlp      |

La app no tiene usuarios ni contraseña: si la publicas en internet, cualquiera con la
dirección puede usar tu servidor para descargar. Protégela en el proxy (autenticación
básica, Cloudflare Access, Tailscale…) si no quieres eso.

## En el móvil

Una vez desplegada con HTTPS:

- **Android (Chrome):** menú ⋮ → *Instalar aplicación*. Queda con su icono, a pantalla
  completa, y aparece en el menú **Compartir**: desde YouTube/TikTok/Instagram,
  *Compartir → saca.* abre la app con el enlace ya puesto.
- **iPhone (Safari):** *Compartir → Añadir a pantalla de inicio*. iOS no permite a las
  PWA recibir enlaces compartidos; ahí se usa el botón «Pegar».

### APK para Android (opcional)

La PWA se puede empaquetar tal cual como app Android (Trusted Web Activity) con
[Bubblewrap](https://github.com/GoogleChromeLabs/bubblewrap); necesita Node y el JDK/SDK
de Android, que la herramienta descarga sola:

```bash
npx @bubblewrap/cli init --manifest https://TU-DOMINIO/static/manifest.webmanifest
npx @bubblewrap/cli build        # genera app-release-signed.apk
```

Para que se abra sin barra de navegador hay que publicar en
`https://TU-DOMINIO/.well-known/assetlinks.json` la huella que imprime `bubblewrap`.
El APK es para instalarlo a mano: Google Play y la App Store no admiten apps que
descargan de YouTube.

La app sigue necesitando el servidor: yt-dlp y ffmpeg corren en el backend, no en el
teléfono.

## API

| Método | Ruta                    | Descripción                                            |
|--------|-------------------------|--------------------------------------------------------|
| GET    | `/api/info?url=`        | Título, duración, resolución máxima y tamaños estimados |
| POST   | `/api/jobs`             | `{url, mode, quality, start?, end?}` → crea la descarga |
| GET    | `/api/jobs/<id>`        | Estado, progreso, velocidad y tiempo restante          |
| DELETE | `/api/jobs/<id>`        | Cancela                                                |
| GET    | `/api/jobs/<id>/file`   | El archivo terminado                                   |
| GET    | `/download?url=&mode=`  | Descarga directa y bloqueante (formulario sin JS)      |

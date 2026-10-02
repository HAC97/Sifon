# VideoDownloader: diseño

Fecha: 2026-10-01. Estado: pendiente de revisión del usuario.

## Objetivo

Web app local, parecida a cobalt: se pega la URL de un video, se elige Video o solo Audio, y el navegador descarga el archivo. Funciona con cualquier sitio que soporte yt-dlp. Uso personal en una máquina Windows, servida en `127.0.0.1`.

**Resultado medible:** de un set fijo de URLs públicas, al menos el 80% se descarga correctamente (verificado con `ffprobe`). Cada job deja una línea en `jobs.log` con estado, duración y código de error.

## Decisiones ya tomadas

- Forma: web app local (no escritorio, no pública, no CLI).
- Motor: yt-dlp usado como librería Python, más ffmpeg para fusionar y extraer audio. Ya están instalados (yt-dlp, ffmpeg, Python 3.12, Node 24).
- Backend: Python + FastAPI. Frontend: HTML/JS/CSS vanilla, sin build.
- No usa LLM, así que no aplica el servicio LLM.

## Estructura

```
contracts/api.openapi.json     contrato único de la API
services/downloader/           FastAPI + yt-dlp (lib) + ffmpeg
  app/ main.py, urlcheck.py, formats.py, jobs.py, errors.py
  tests/ (gate)   evals/ (periódicos)   README.md
web/ index.html, app.js, style.css
scripts/ run.ps1, update-ytdlp.ps1
```

El servidor sirve `web/` y `/api` desde el mismo puerto (`127.0.0.1:8000`), sin CORS.

## API (contrato en `contracts/api.openapi.json`)

- `POST /api/info {url}` devuelve `{title, thumbnail, duration, uploader, heights[]}`.
- `POST /api/jobs {url, mode: "video"|"audio", height?, audio_format?}` devuelve `{job_id}`.
  - Video: `height` es 360, 480, 720, 1080, 1440, 2160 o `best`. Salida mp4.
  - Audio: `audio_format` es `mp3` (192k), `m4a` u `opus`.
- `GET /api/jobs/{id}` devuelve `{status, percent, speed, eta, filename?, error_code?, error_message?}`.
  - `status`: `queued`, `downloading`, `processing`, `done`, `error`.
- `GET /api/jobs/{id}/file` entrega el archivo con `Content-Disposition`.
- `GET /api/health` devuelve la versión de yt-dlp y si ffmpeg está disponible.

## Flujo de datos

1. La UI llama a `/info` con la URL y muestra título y miniatura.
2. El usuario elige modo y calidad o formato; la UI crea el job.
3. El job corre en un hilo (`ThreadPoolExecutor`, máximo 3 simultáneos). El hook de progreso de yt-dlp actualiza el estado en memoria.
4. La UI consulta el estado cada 1 s; en `done` dispara `/file`.
5. Cada job usa un directorio temporal propio, borrado 30 min después de terminar.

Selectores: video usa `bv*[height<=H]+ba/b[height<=H]` con `merge_output_format=mp4`. Audio usa `bestaudio` más el postprocesador `FFmpegExtractAudio`.

## Seguridad y errores

- Solo `http` y `https`. Se resuelve el host y se rechazan loopback, redes privadas y link-local (SSRF). El servidor escucha solo en `127.0.0.1`.
- `noplaylist=True`: se descarga solo el video de la URL.
- Nombres de archivo sanitizados. Solo se sirven archivos del directorio del job; el id es un UUID.
- Códigos de error: `INVALID_URL`, `UNSUPPORTED_SITE`, `LOGIN_REQUIRED`, `GEO_BLOCKED`, `FFMPEG_MISSING`, `NETWORK`, `UNKNOWN`. La UI muestra un texto claro por código.
- yt-dlp se rompe cuando un sitio cambia. `/health` muestra la versión y `update-ytdlp.ps1` ejecuta `pip install -U yt-dlp`.

## Tests y evals (en el mismo commit que el código)

- **Gate** (pytest, deterministas, sin red, menos de 2 s): validación de URL y SSRF; constructor de selectores; mapeo de errores; máquina de estados de jobs con downloader falso; contrato de la API contra el OpenAPI con TestClient; limpieza por TTL.
- **Eval periódico** (con red): unas 5 URLs públicas o de dominio público (YouTube corto, Vimeo, SoundCloud, archive.org y una más), en modo video y audio. `ffprobe` valida streams y duración. Umbral: 80%.
- **Frontend:** smoke test con Playwright contra un servidor falso: pegar URL, elegir modo, ver progreso y recibir el archivo.

## Fuera de alcance (v1)

Playlists, cookies o login, subtítulos, cuentas de usuario, Docker, despliegue público.

## Restart

Es un proyecto nuevo: se arranca con `scripts/run.ps1`. No hay servicios previos que reiniciar.

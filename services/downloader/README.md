# Servicio downloader

Backend FastAPI + yt-dlp. Sirve también la interfaz de `web/`. Escucha solo en `127.0.0.1`.

## Endpoints

Contrato completo en `contracts/api.openapi.json`. Resumen:

- `GET /api/health`: `ok`, versión de yt-dlp y si hay ffmpeg.
- `POST /api/info`: título, miniatura, duración, autor y alturas disponibles de una URL.
- `POST /api/jobs`: crea una descarga (`mode` `video` con `height`, o `audio` con formato). Devuelve `job_id`.
- `GET /api/jobs/{id}`: estado, porcentaje, nombre de archivo, código y mensaje de error.
- `GET /api/jobs/{id}/file`: baja el archivo terminado.

Regenerar el contrato (desde la raíz del repo):

```powershell
.\services\downloader\.venv\Scripts\python.exe scripts\gen_contract.py
```

## Tests

Tres carriles, desde la raíz del repo:

| Carril | Comando | Notas |
|---|---|---|
| gate | `.\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\tests -q` | Local, sin red. |
| e2e | `.\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\tests\e2e -m e2e -q` | Navegador real, necesita `.\services\downloader\.venv\Scripts\python.exe -m playwright install chromium` (una vez; playwright viene de `requirements-dev.txt`). |
| eval | `.\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\evals -m eval -s -q` | Usa la red y baja archivos reales. Umbral 80%. |

Resultados del eval el 2026-10-01: una corrida dio 9 de 11 casos (82%, umbral 80%), con YouTube, SoundCloud, archive.org y Dailymotion pasando. Tres corridas posteriores el mismo día dieron 73%, 64% y 64%: archive.org no respondía desde esta máquina (timeouts) y un caso de audio de YouTube falló una vez por un error de red. Los dos casos de Vimeo fallan a propósito (el video de prueba ya no existe y los demás piden login). Por eso el umbral de 80% no está confirmado como estable: hay que volver a correr el eval cuando los sitios respondan. URLs y cómo se verificaron: `services/downloader/evals/URL_VERIFICATION.md`.

## jobs.log

`services/downloader/jobs.log` (ignorado por git). Una línea JSON por job con `ts`, `job_id`, `mode`, `status`, `duration_s`, `error_code` y `host`. Nunca guarda la URL completa.

## Limitaciones conocidas

- La validación de URL resuelve el host una vez y yt-dlp lo resuelve de nuevo después, así que un host con DNS rebinding o una redirección a una red privada no están cubiertos. El servidor solo escucha en `127.0.0.1`, por lo que el riesgo es bajo para uso personal.
- Sin login ni cookies: los videos privados fallan con `LOGIN_REQUIRED`.
- yt-dlp se rompe cuando un sitio cambia: actualizarlo con `scripts\update-ytdlp.ps1`.
- Un HTTP 404 del sitio puede mostrarse con el mensaje de conexión (`NETWORK`).
- Si falla la primera consulta de progreso en la interfaz, deja de mostrarse el avance, pero la descarga sigue en el servidor.

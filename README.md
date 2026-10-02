# VideoDownloader

Descargador de videos y audio local, parecido a cobalt. Pegás una URL, elegís video (con calidad) o solo audio (mp3, m4a u opus) y bajás el archivo. Corre en tu máquina: backend FastAPI + yt-dlp, interfaz web simple.

Descargá solo contenido sobre el que tengas derecho a hacerlo y respetá los términos de cada sitio.

## Requisitos

- Windows con PowerShell
- Python 3 (probado con 3.12)
- `ffmpeg` en el `PATH` (`ffprobe` suele venir con él; es opcional, ver abajo)

Si falta `ffmpeg`, `/api/health` muestra `"ffmpeg": false` y las descargas fallan con el código `FFMPEG_MISSING`. Una forma de instalarlo en Windows es `winget install Gyan.FFmpeg` (sugerencia, no probada por el autor); después reiniciá la app.

`ffprobe` es opcional: sin él siguen funcionando la extracción de audio (mp3, m4a, opus) y la fusión de video y audio (probado con ffmpeg sin `ffprobe` sobre archivos locales). Según el código de yt-dlp, algunos videos HLS sí lo necesitan (no probado con una descarga real) y en ese caso fallan con `FFMPEG_MISSING`; el eval (`-m eval`) también lo exige para validar los archivos.

## Instalación

```powershell
python -m venv services\downloader\.venv
services\downloader\.venv\Scripts\python.exe -m pip install -r services\downloader\requirements.txt
```

Para correr los tests, instalá además `services\downloader\requirements-dev.txt` con el mismo `pip install -r`.

Si ya tenías un entorno viejo, volvé a correr el `pip install -r` de arriba: `requirements.txt` instala `yt-dlp[default,curl-cffi]` y `curl-cffi` hace falta para sitios como Dailymotion.

## Arranque

```powershell
.\scripts\run.ps1
```

Abrí `http://127.0.0.1:8000`. Si el puerto 8000 ya está en uso en tu máquina, usá otro: `.\scripts\run.ps1 -Port 8765` (y abrí `http://127.0.0.1:8765`). El autor solo corrió la app con `-Port 8765`; el puerto 8000 (el predeterminado) puede estar ocupado en tu máquina. El servidor escucha solo en `127.0.0.1` y rechaza pedidos con un `Host` u `Origin` que no sea local (ver la sección de seguridad en `services/downloader/README.md`).

## Actualizar yt-dlp

yt-dlp se rompe cuando un sitio cambia. Para actualizarlo:

```powershell
.\scripts\update-ytdlp.ps1
```

Después reiniciá la app.

## Estructura

```
contracts/api.openapi.json   contrato HTTP (generado)
scripts/                     run.ps1, update-ytdlp.ps1, gen_contract.py
services/downloader/         backend, tests y evals (ver su README)
web/                         interfaz (index.html, app.js, style.css)
```

Más detalle (endpoints, tests, límites conocidos): `services/downloader/README.md`.

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

### Cómo puntúa el eval

Cada uno de los 11 casos termina en uno de cuatro tipos, y se imprimen todos:

- `PASS`: el archivo es válido (ffprobe, códec y duración).
- `FAIL`: falla del producto (archivo incorrecto, un error que no es de red, cualquier otra excepción).
- `NETWORK`: error de red o timeout. Se reintenta una vez; si vuelve a fallar, se registra así.
- `KNOWN_DEAD`: los dos casos de Vimeo (el video ya no existe y los demás piden login). Se corren y se imprimen, pero no cuentan. Si uno pasa, el eval imprime `PROMOTE` y falla para que lo muevas de vuelta a los casos activos.

Tasa = `PASS / (PASS + FAIL)` sobre los casos activos (`NETWORK` y `KNOWN_DEAD` no cuentan). Si los `NETWORK` son más del 25% de los casos activos, el veredicto es `INCONCLUSIVE` y el eval falla con un mensaje claro (nunca pasa en silencio ni se saltea). Si no, pasa cuando la tasa es de al menos 80%. El puntaje de cada caso queda en `evals/results/last_run.json` (ignorado por git), con su `kind`.

Historial, el 2026-10-01, con la puntuación anterior (todo fallo contaba contra el producto, Vimeo incluido): una corrida dio 9 de 11 casos (82%, umbral 80%), con YouTube, SoundCloud, archive.org y Dailymotion pasando. Tres corridas posteriores el mismo día dieron 73%, 64% y 64%: archive.org no respondía desde esta máquina (timeouts) y un caso de audio de YouTube falló una vez por un error de red.

Una corrida con la puntuación nueva, el 2026-10-01: `PASS=7, FAIL=0, NETWORK=2, KNOWN_DEAD=2`. Los dos `NETWORK` fueron los casos de archive.org, que siguen sin responder desde esta máquina tras el reintento. Tasa 7 de 7 (100%), `NETWORK` 22% de los casos activos (límite 25%), veredicto `PASS`. Como archive.org no se pudo medir, el umbral de 80% está confirmado solo sobre 7 de los 9 casos activos; queda sin confirmar para archive.org hasta una corrida con ese sitio alcanzable (con más del 25% en `NETWORK` la corrida sería `INCONCLUSIVE`, no un resultado). Esta fue una sola corrida. URLs y cómo se verificaron: `services/downloader/evals/URL_VERIFICATION.md`.

## jobs.log

`services/downloader/jobs.log` (ignorado por git). Una línea JSON por job con `ts`, `job_id`, `mode`, `status`, `duration_s`, `error_code` y `host`. Nunca guarda la URL completa.

## Seguridad

La API no tiene autenticación. Escucha solo en `127.0.0.1`, y además un middleware revisa cada pedido:

- El `Host` tiene que ser `127.0.0.1`, `localhost` o `[::1]` (sin importar el puerto ni las mayúsculas); si no, responde `403` con `{"detail": "host not allowed"}`. Esto bloquea las páginas con DNS rebinding, que de otro modo se volverían del mismo origen que la API.
- En los métodos que no son GET, HEAD ni OPTIONS, si viene un `Origin`, su host tiene que ser uno de esos; si no, `403` con `{"detail": "origin not allowed"}`. Esto bloquea los POST desde otra página. Un pedido sin `Origin` (curl, navegación directa) pasa.
- `create_app(..., allowed_hosts=...)` cambia la lista permitida.

Lo que no cubre: la validación de URL resuelve el host una vez y yt-dlp lo resuelve de nuevo después, y yt-dlp sigue las redirecciones sin volver a validarlas. Una URL pública que redirija a una red privada (por ejemplo `192.168.x.x` o `127.0.0.1`) sigue pudiendo ser descargada: esa es una limitación conocida y no está resuelta. El riesgo es acotado para uso personal en una máquina propia, pero no es nulo.

## Limitaciones conocidas

- Redirecciones a redes privadas: ver la sección de seguridad. No están cubiertas.
- Sin login ni cookies: los videos privados fallan con `LOGIN_REQUIRED`.
- yt-dlp se rompe cuando un sitio cambia: actualizarlo con `scripts\update-ytdlp.ps1`.
- Si falla cualquier consulta de progreso en la interfaz (no solo la primera), deja de mostrarse el avance, pero la descarga sigue en el servidor. Si el servidor se reinicia, la página muestra un mensaje genérico.

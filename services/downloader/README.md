# Servicio downloader

Backend FastAPI + yt-dlp. Sirve también la interfaz de `web/`. Escucha solo en `127.0.0.1`. Instalación y uso: README de la raíz.

## Endpoints

Contrato completo en `contracts/api.openapi.json` (generado; un test falla si se desactualiza). Resumen:

- `GET /api/health`: `ok`, versión de sifón y de yt-dlp, si hay ffmpeg, ffprobe y motor de JavaScript (`deno`, `node` o `null`), y los límites activos.
- `POST /api/info`: título, miniatura, duración, autor y alturas disponibles de una URL.
- `POST /api/jobs`: crea una descarga (`mode` `video` con `height`, o `audio` con formato). Devuelve `job_id` (202). Errores previos al trabajo: `400` (URL, red bloqueada), `429` `QUEUE_FULL`, `507` `DISK_FULL`.
- `GET /api/jobs/{id}`: estado (`queued`, `downloading`, `processing`, `done`, `error`, `cancelled`), porcentaje, nombre de archivo, código y mensaje de error.
- `DELETE /api/jobs/{id}`: cancela un trabajo en cola o en curso. Si ya terminó, lo descarta junto con su archivo. `404` si no existe.
- `GET /api/jobs/{id}/file`: baja el archivo terminado.

Códigos de error (`error_code`): `INVALID_URL`, `UNSUPPORTED_SITE`, `LOGIN_REQUIRED`, `GEO_BLOCKED`, `FFMPEG_MISSING`, `NETWORK`, `BLOCKED_ADDRESS`, `TOO_LARGE`, `TOO_LONG`, `QUEUE_FULL`, `DISK_FULL`, `CANCELLED`, `UNKNOWN`.

Regenerar el contrato (desde la raíz del repo):

```powershell
.\services\downloader\.venv\Scripts\python.exe scripts\gen_contract.py
```

## Límites

Variables `SIFON_*` leídas al crear la app (`app/config.py`); valores y efecto en el README de la raíz. Un valor inválido hace fallar el arranque con el nombre de la variable. Dónde se aplica cada uno:

- Cola y concurrencia: `JobManager.create` (el conteo y el alta se hacen bajo un mismo lock, así que pedidos simultáneos no superan el tope) y el pool de hilos.
- Tamaño y espacio libre: el hook de progreso de yt-dlp (`JobManager._check_limits`) aborta la descarga en curso; el espacio libre se vuelve a medir como mucho cada 2 s y también al crear el trabajo.
- Duración y transmisiones en vivo: `match_filter` de yt-dlp en `ytdlp_runner.run_download`, antes de bajar nada.
- Cancelación: `JobManager.cancel` marca el trabajo; el hook de progreso lanza `CANCELLED` en el siguiente evento. Un trabajo en cola nunca arranca. Si se cancela mientras ffmpeg convierte, el resultado se descarta al terminar.

## Archivos temporales

`%TEMP%\sifon-<pid>` (ver `create_app`). Un trabajo fallido o cancelado borra su carpeta al terminar; uno completado, `SIFON_TTL_MINUTES` después (barrido cada 60 s); `shutdown()` borra todo. La ejecución toca `.alive` cada 60 s y, al arrancar, `create_app` borra las carpetas `sifon-*` ajenas con ese latido de más de 10 minutos (o sin latido y con la carpeta igual de vieja): son de una ejecución que murió sin limpiar.

## Tests

Tres carriles, desde la raíz del repo (necesitan `.\install.cmd -Dev`):

| Carril | Comando | Notas |
|---|---|---|
| gate | `.\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\tests -q` | Local, sin internet. Incluye el proxy de salida, los límites con un servidor local y yt-dlp real, y el contrato. |
| e2e | `.\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\tests\e2e -m e2e -q` | Navegador real, necesita `.\services\downloader\.venv\Scripts\python.exe -m playwright install chromium` (una vez). |
| eval | `.\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\evals -m eval -s -q` | Usa la red y baja archivos reales de sitios reales. Umbral 80%. Necesita ffprobe. |

En GitHub Actions: `.github/workflows/ci.yml` corre el gate, el contrato, e2e y una instalación desde cero en Windows; `.github/workflows/evals.yml` corre el eval a mano o una vez por semana y **no bloquea** merges, porque depende de sitios externos.

### Cómo puntúa el eval

Cada uno de los 11 casos termina en uno de cuatro tipos, y se imprimen todos:

- `PASS`: el archivo es válido (ffprobe, códec y duración).
- `FAIL`: falla del producto (archivo incorrecto, un error que no es de red, cualquier otra excepción).
- `NETWORK`: error de red o timeout. Se reintenta una vez; si vuelve a fallar, se registra así.
- `KNOWN_DEAD`: los dos casos de Vimeo (el video ya no existe y los demás piden login). Se corren y se imprimen, pero no cuentan. Si uno pasa, el eval imprime `PROMOTE` y falla para que lo muevas de vuelta a los casos activos.

Tasa = `PASS / (PASS + FAIL)` sobre los casos activos (`NETWORK` y `KNOWN_DEAD` no cuentan). Si los `NETWORK` son más del 25% de los casos activos, el veredicto es `INCONCLUSIVE` y el eval falla con un mensaje claro (nunca pasa en silencio ni se saltea). Si no, pasa cuando la tasa es de al menos 80%. El puntaje de cada caso queda en `evals/results/last_run.json` (ignorado por git), con su `kind`. URLs y cómo se verificaron: `evals/URL_VERIFICATION.md`. Los resultados por versión están en `CHANGELOG.md`.

## jobs.log

`services/downloader/jobs.log` (ignorado por git). Una línea JSON por job con `ts`, `job_id`, `mode`, `status`, `duration_s`, `error_code` y `host`. Nunca guarda la URL completa.

## Seguridad

La API no tiene autenticación. **No está preparada para exponerse directamente a internet ni a una red compartida**: quien llegue al puerto puede iniciar descargas en la máquina. Escucha solo en `127.0.0.1` (el lanzador lo fija; no cambies `--host`). Defensas, de afuera hacia adentro:

1. **Host y Origin** (middleware en `app/main.py`). El `Host` tiene que ser `127.0.0.1`, `localhost` o `[::1]` (sin importar puerto ni mayúsculas); si no, `403` `{"detail": "host not allowed"}`. Esto bloquea las páginas con DNS rebinding. En los métodos que no son GET, HEAD ni OPTIONS (incluido `DELETE`), si viene un `Origin`, su host tiene que ser uno de esos; si no, `403` `{"detail": "origin not allowed"}`. Un pedido sin `Origin` (curl, navegación directa) pasa. `create_app(..., allowed_hosts=...)` cambia la lista.
2. **Validación de la URL** (`app/urlcheck.py`). Esquema `http` o `https`, sin espacios, hasta 2048 caracteres, y el host no puede resolver a una dirección no pública (loopback, privada, link-local, reservada, multicast). Da un error rápido y claro, pero **no es la defensa**: resuelve una vez y después yt-dlp resuelve de nuevo.
3. **Proxy de salida** (`app/egress_proxy.py`), la defensa real. Todo pedido de yt-dlp (información y descarga, con cualquiera de sus clientes HTTP: urllib, requests y curl-cffi) sale por un proxy HTTP/CONNECT que escucha solo en `127.0.0.1`, en un puerto efímero. Para cada conexión resuelve el nombre **una vez**, rechaza (`403`, motivo `sifon-blocked-address`, código `BLOCKED_ADDRESS`) si **alguna** dirección resuelta no es pública, y conecta a la dirección que comprobó, sin resolver otra vez. Como cada salto de una redirección es una conexión nueva por el proxy, una URL pública que redirige a `192.168.x.x` o `127.0.0.1` también se bloquea, y un nombre que cambia de respuesta entre la comprobación y la conexión (DNS rebinding) no sirve. Si el proxy no arranca, la app no arranca.

Cubierto por tests (`tests/test_egress_proxy.py`, `tests/test_limits_integration.py`): redirección público → privado, respuesta DNS mixta, una sola resolución por conexión, IP literal privada, CONNECT, y la aplicación ensamblada con yt-dlp real.

Lo que no cubre:

- Un proxy de empresa para salir a internet no se respeta (el tráfico de yt-dlp va solo por el proxy interno).
- Los clientes HTTP de yt-dlp son de terceros: un cliente nuevo que ignore la opción `proxy` evadiría el control. Los tres actuales se probaron; un cambio grande de yt-dlp justifica volver a correr los tests.
- No hay autenticación, límites por usuario ni cuotas: los límites son del equipo, no de quien llama.

## Limitaciones conocidas

- Sin login ni cookies: los videos privados fallan con `LOGIN_REQUIRED`.
- yt-dlp se rompe cuando un sitio cambia: actualizarlo con `update.cmd`.
- Si falla cualquier consulta de progreso en la interfaz (no solo la primera), deja de mostrarse el avance, pero la descarga sigue en el servidor. Si el servidor se reinicia, la página muestra un mensaje genérico.
- El límite de tamaño es por archivo bajado; un video con audio separado puede acercarse al doble.
- Solo Windows está probado.

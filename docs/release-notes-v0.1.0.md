# sifón v0.1.0

Primera versión pensada para que otra persona la instale en su Windows. Se distribuye como código fuente (ZIP o Git); un instalador o ejecutable queda para una versión posterior.

## Qué es

Descargador local de video y audio. Pegás un enlace, elegís video (con calidad) o solo audio (MP3, M4A, Opus) y el navegador guarda el archivo. Servidor FastAPI + yt-dlp en tu computadora, interfaz web propia. Licencia MIT.

## Requisitos

| | |
|---|---|
| Windows 64 bits | probado en Windows 11 Home (10.0.26300); Windows 10 no probado |
| Python | 3.10 o más nuevo; probado con 3.12.10 |
| FFmpeg | obligatorio; probado con 8.1.1 y 9.0.2 (compilaciones `full` de gyan.dev) |
| FFprobe | opcional; probado con y sin él |
| Deno | recomendado para YouTube; probado con 2.9.7 (sin Deno se usa Node.js si está) |

Linux y macOS no están probados y no se ofrecen como compatibles. Pasos de instalación, uso y problemas frecuentes: [README](../README.md).

## Qué trae

- `install.cmd`, `run.cmd`, `update.cmd`: instalación guiada, arranque (detecta puertos ocupados y dependencias, abre el navegador cuando el servidor responde) y actualización de `yt-dlp[default,curl-cffi]` verificada.
- Límites configurables por variables `SIFON_*`: descargas simultáneas, cola, tamaño, duración, espacio libre, vida de los archivos y memoria. Cancelación de descargas (botón y `DELETE /api/jobs/{id}`).
- Archivos temporales que se borran solos (ver el README).
- Solo escucha en `127.0.0.1`; todo el tráfico de yt-dlp pasa por un proxy interno que bloquea redes privadas, incluidas redirecciones y cambios de DNS. **No está preparada para exponerse a internet.**

## Qué se probó (2026-10-02)

Todo en una sola máquina: Windows 11 Home 10.0.26300, Python 3.12.10, yt-dlp 2026.08.19, yt-dlp-ejs 0.8.0, curl-cffi 0.16.3, FastAPI 0.142.2.

| Prueba | Resultado |
|---|---|
| Tests locales (gate, sin red) | 332 pasaron |
| Tests de navegador (Playwright + Chromium) | 17 pasaron |
| Eval con sitios reales, pasando por el proxy de salida, 3 corridas | 9 de 9 casos activos `PASS` las 3 veces (YouTube video y audio MP3, M4A y Opus; SoundCloud; archive.org; Dailymotion), 0 `FAIL`, 0 `NETWORK`; los 2 casos de Vimeo `KNOWN_DEAD` (el video ya no existe o pide login). Cada corrida tardó entre 80 y 97 s |
| Desde un ZIP nuevo, siguiendo el README: `install.cmd` (23 s), `run.cmd`, con el navegador real: video 360p de YouTube (AV1 + AAC, 634,6 s, verificado con ffprobe), MP3 de YouTube y Opus de SoundCloud, y `update.cmd` | todo bien |
| Puerto 8000 ocupado: `run.cmd` pasa al 8001; `-Port` ocupado: se detiene con un mensaje | bien |
| Sin FFmpeg: `install.cmd` se detiene; con el servidor andando la descarga da `FFMPEG_MISSING` | bien |
| Sin entorno virtual / variable `SIFON_*` inválida: `run.cmd` explica qué hacer | bien |
| `update.cmd` sin acceso al índice de paquetes | falla con un mensaje (antes habría dicho "ya está al día") |
| Cierre con la señal de interrupción: el servidor termina y borra su carpeta temporal | bien |
| Deno 2.9.7 + FFmpeg 9.0.2; solo Node.js; ningún motor de JavaScript | un video de YouTube descargado en los tres casos |
| FFmpeg sin FFprobe: video, MP3, M4A y Opus de YouTube | descargados |
| Revisión de seguridad independiente (atacante en frío) | 8 hallazgos, todos corregidos o documentados; ver abajo |

Una de las ~25 descargas reales de la matriz de herramientas (M4A sin FFprobe) falló una vez con `NETWORK`; repetida 8 veces, funcionó las 8. Se cuenta aquí y no se oculta.

### Revisión de seguridad

Un revisor independiente intentó romper las defensas con servidores locales. Hallazgos corregidos antes de esta versión: lectura de memoria sin tope con una página que no termina (ahora hay tope de bytes en el proxy y de memoria en el proceso); ffmpeg y `NO_PROXY` podían saltarse el proxy; formas IPv6 con IPv4 embebida (NAT64, compatibles) no se bloqueaban; el barrido de carpetas temporales podía borrar una carpeta ajena llamada `sifon-…`; carpetas sin borrar con un archivo en uso; `Origin` de otro puerto local aceptado; `Host` mal formado aceptado; un puerto inválido en el proxy daba un traceback. Cada uno tiene un test de regresión.

## Problemas conocidos y límites de lo probado

- **No se probó en un Windows recién instalado.** Python, FFmpeg y Node.js ya estaban en la máquina de prueba y no hubo máquina virtual (Windows 11 Home no trae Windows Sandbox). Se probó con un ZIP nuevo, un entorno virtual nuevo y un `PATH` controlado, no con un sistema vacío.
- Windows 10, otras versiones de Python (3.10, 3.11, 3.13) y otras versiones de FFmpeg y Deno no se probaron.
- La apertura automática del navegador: el lanzador la ejecuta sin error, pero la prueba automática no pudo observar la pestaña. SmartScreen y la política de ejecución de PowerShell tampoco se observaron en una máquina limpia (los `.cmd` evitan esa política).
- `Ctrl+C` en la ventana de `run.cmd` no se probó de forma interactiva; sí la señal equivalente enviada al servidor.
- Los flujos de GitHub Actions se validaron con `actionlint` y ejecutando sus pasos a mano; **todavía no corrieron en GitHub**.
- Solo se probaron YouTube, SoundCloud, archive.org y Dailymotion. Vimeo no funciona sin iniciar sesión. Sin login ni cookies, los videos privados o de miembros fallan.
- Cuando es ffmpeg quien baja los segmentos (HLS con SAMPLE-AES, algunas transmisiones en vivo), los segmentos `https` fallan: es el precio de impedir que ffmpeg se conecte sin pasar por el proxy.
- El límite de tamaño es por archivo: un video con audio separado puede ocupar cerca del doble. El espacio libre no se vigila durante la fusión final.
- `POST /api/info` no se encola (cada consulta tiene un tope de 32 MB).
- Un proxy de empresa para salir a internet no se respeta; mientras corre, sifón ignora `NO_PROXY` y `ALL_PROXY`.
- Sin autenticación: no exponer a internet ni a la red local.
- yt-dlp se rompe cuando un sitio cambia: `update.cmd`.

## Reportar un problema

Con la plantilla de Issues del repositorio (pide versiones y pasos). **No adjuntes cookies, contraseñas, tokens ni enlaces privados.** Vulnerabilidades: ver [SECURITY.md](../SECURITY.md).

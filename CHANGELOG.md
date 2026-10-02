# Cambios

Formato: [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). Versionado: `0.x` mientras la instalación se pruebe en pocas máquinas.

## [0.1.0] - 2026-10-02 (pendiente de etiquetar)

Primera versión pensada para que otra persona la instale en su Windows. Detalle de requisitos, pruebas y problemas conocidos: [`docs/release-notes-v0.1.0.md`](docs/release-notes-v0.1.0.md).

### Agregado

- `install.cmd`: comprueba Python, FFmpeg, FFprobe y Deno, crea el entorno virtual, instala las dependencias y verifica el resultado. Se detiene con un mensaje claro y no toca configuraciones globales.
- `run.cmd`: detecta dependencias ausentes y puertos ocupados, muestra la dirección y abre el navegador cuando el servidor responde.
- `update.cmd`: actualiza `yt-dlp[default,curl-cffi]` (incluido `yt-dlp-ejs`) y solo informa éxito tras `pip check` y la comprobación de que `yt-dlp-ejs` coincide con lo que pide yt-dlp.
- Límites configurables (`SIFON_MAX_CONCURRENT`, `SIFON_MAX_QUEUE`, `SIFON_MAX_FILESIZE_MB`, `SIFON_MAX_DURATION_MIN`, `SIFON_MIN_FREE_DISK_MB`, `SIFON_TTL_MINUTES`, `SIFON_MAX_MEMORY_MB`) y códigos de error `TOO_LARGE`, `TOO_LONG`, `QUEUE_FULL`, `DISK_FULL`.
- Cancelación: `DELETE /api/jobs/{id}` y botón **Cancelar descarga** en la interfaz.
- `GET /api/health` informa también la versión de sifón, FFprobe, el motor de JavaScript y los límites activos.
- Uso de Node.js como motor de JavaScript cuando no hay Deno.
- Licencia MIT, `THIRD_PARTY.md`, `SECURITY.md`, plantilla de reporte de errores, `.gitattributes` y `.gitignore` completo.
- GitHub Actions: `ci.yml` (tests, contrato, navegador, instalación desde cero) y `evals.yml` (sitios reales, manual o semanal, no bloquea merges).

### Seguridad (revisión independiente)

- Tope de bytes por conexión en el proxy de salida (32 MB para `/api/info`, `SIFON_MAX_FILESIZE_MB` para descargas) y tope de memoria del proceso (`SIFON_MAX_MEMORY_MB`): una página que no termina ya no agota la RAM.
- ffmpeg ya no puede saltarse el proxy: se ignoran `NO_PROXY` y `ALL_PROXY` mientras corre el servidor y ffmpeg recibe una lista de protocolos permitidos sin `httpproxy://`.
- `is_blocked_ip` bloquea también IPv4 embebida en `::/96`, `64:ff9b::/96` y SIIT, `fec0::/10`, `192.88.99.0/24` y `5f00::/16`.
- `Origin` debe coincidir con el `Host` (mismo puerto); un `Host` mal formado se rechaza.
- El barrido de carpetas temporales solo toca `sifon-<número>` que contienen el archivo de latido; las carpetas que Windows no deja borrar se reintentan.

### Cambiado

- Seguridad: todo el tráfico de yt-dlp pasa por un proxy interno en `127.0.0.1` que resuelve cada nombre una vez y rechaza destinos no públicos. Cierra el límite conocido de versiones anteriores: las redirecciones y los cambios de DNS ya no pueden llegar a redes privadas (`BLOCKED_ADDRESS`).
- Una descarga fallida o cancelada borra sus archivos parciales de inmediato (antes esperaba el TTL).
- La carpeta temporal pasa a `%TEMP%\sifon-<pid>` y una ejecución nueva borra las que dejó una ejecución muerta (por latido).
- Descargas simultáneas por defecto: 2 (antes 3).
- El eval de sitios reales usa el mismo camino que la aplicación (con el proxy de salida).

### Problemas conocidos

Ver `docs/release-notes-v0.1.0.md`.

# Cambios

Formato: [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). Versionado: `0.x` mientras la instalación se pruebe en pocas máquinas.

## [Sin publicar]

### Agregado

- `packaging/winget/make_manifest.py`: genera, a partir del propio release (URL y `SHA256SUMS.txt`), los cuatro archivos del manifiesto de winget (`HAC97.sifon`), con tests; el resultado pasa `winget validate` sin advertencias. Guía en `packaging/winget/README.md`.
- README: secciones **Privacidad** y **Política de firma de código** (requisito de SignPath Foundation); `docs/code-signing.md`.

### Cambiado

- El repositorio pasó a llamarse `HAC97/Sifon`: URLs actualizadas.

## [0.2.0] - sin fecha (pendiente de etiquetar)

Primera versión con **ejecutable para Windows**: se baja el instalador desde Releases y no hace falta instalar nada más.

### Agregado

- **Instalador (`sifon-<versión>-setup.exe`) y ZIP portable**: `sifon.exe` con Python, las dependencias, FFmpeg y FFprobe (compilación LGPL de BtbN, sin `--enable-gpl`) y Deno incluidos, verificados con SHA-256 al construir. El instalador es por usuario (sin administrador), crea un acceso en el menú Inicio y se desinstala limpio (programa, registro, acceso y datos propios; nunca las descargas).
- Ventana de control chica (tkinter): dirección, abrir la página, buscar actualización de yt-dlp, reiniciar para aplicarla y cerrar sifón (avisa si hay descargas en curso). Una segunda ejecución solo abre la página de la que ya está abierta.
- **Actualización de yt-dlp dentro del ejecutable**: una vez por día baja la versión nueva de PyPI, comprueba su SHA-256, la extrae con protección contra rutas maliciosas, la prueba en un proceso aparte y la usa al reiniciar; una actualización que no arranca se descarta. Se apaga con la casilla de la ventana o `SIFON_NO_AUTO_UPDATE=1`.
- `packaging/`: `build.py` (PyInstaller, descarga verificada de FFmpeg y Deno, ZIP, instalador), `smoke_test.py` (arranca el paquete con un `PATH` sin Python, FFmpeg ni Deno; descarga real con `--online`) y `test_installer.ps1` (instala, prueba y desinstala).
- GitHub Actions: `ci.yml` construye y prueba el paquete en cada PR; `release.yml` lo construye al empujar un tag `v*` y lo adjunta al release (como borrador si no existe); `canary.yml` lo reconstruye cada semana con el yt-dlp más nuevo y avisa si algo se rompió.
- Opciones `--no-browser`, `--port N` y `--no-window` en `sifon.exe`; cierre ordenado con `Ctrl+C`, `Ctrl+Break`, cierre de la ventana de consola o un archivo `stop.request`.

### Seguridad (revisión independiente del actualizador, el lanzador y los flujos)

- El actualizador comparaba la versión como texto: yt-dlp escribe `2026.08.19` y PyPI informa `2026.8.19`, así que habría descartado casi todas las actualizaciones; ahora se compara numéricamente.
- Una versión hostil en la respuesta del índice ya no puede usarse como ruta (borrado o reemplazo fuera de la carpeta de actualizaciones), ni apuntar a otro host o a `http`; las redirecciones también se validan y cada descarga tiene un plazo total.
- Preferencias dañadas o con tipos raros ya no rompen la búsqueda diaria; escritura atómica; un reloj movido no la apaga.
- Una actualización que no importa deja de contar como usable aunque ya exista su carpeta `.bad`; nunca se borra la carpeta de la que corre el proceso.
- Instancia única con un mutex de Windows (dos dobles clics seguidos ya no levantan dos servidores); `instance.json` solo lo borra su dueño; el chequeo de salud no sigue redirecciones y exige la forma de la respuesta de sifón; `--port` se valida; el reinicio conserva las opciones.
- `release.yml`: el nombre del tag llega a los scripts solo por variable de entorno y debe ser `vX.Y.Z`; el commit etiquetado debe estar en `main`; compila con permisos de solo lectura y un job aparte, mínimo, adjunta los archivos a un borrador y se niega a reemplazar los de un release publicado.
- Acciones de GitHub fijadas por SHA; Inno Setup y Deno con hash fijo; las descargas de la compilación son atómicas y un archivo que no verifica se borra.
- El test del instalador se niega a correr fuera de GitHub Actions sin un interruptor explícito (reemplaza la entrada de desinstalación real y borra los datos de sifón).

### Cambiado

- Con el ejecutable, todo lo que se escribe va a `%LOCALAPPDATA%\sifon` (registro `jobs.log` incluido), no junto al programa.
- Un test de higiene impide versionar binarios o la salida de la compilación.

### Arreglado

- El chequeo de salud del arranque ignora las variables de proxy: el servidor las apunta a su proxy de salida, que bloquea `127.0.0.1`, y el programa se quedaba esperando a sí mismo.

### Límites conocidos

- El instalador no está firmado: Windows muestra el aviso de SmartScreen.
- Windows 10 y un Windows recién instalado no se probaron en una máquina real (sí en el runner de GitHub Actions).

## [0.1.0] - 2026-10-02

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

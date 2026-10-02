# sifón v0.2.0

**Primera versión con ejecutable para Windows.** Bajás el instalador, lo ejecutás y listo: no hace falta instalar Python, FFmpeg ni nada más.

## Descargar

Desde los archivos de esta versión:

- `sifon-0.2.0-setup.exe`: instalador. No pide administrador, crea un acceso en el menú Inicio y se desinstala desde *Configuración > Aplicaciones*.
- `sifon-0.2.0-windows-portable.zip`: sin instalar, descomprimí y ejecutá `sifon.exe`.
- `SHA256SUMS.txt`: hashes para comprobar la descarga (`Get-FileHash .\sifon-0.2.0-setup.exe -Algorithm SHA256`).

**El instalador no está firmado.** Windows puede mostrar "Windows protegió su PC": elegí *Más información > Ejecutar de todas formas*. Algún antivirus puede marcar por error un ejecutable nuevo y sin firmar.

## Qué trae

- `sifon.exe` con Python, las dependencias, **FFmpeg y FFprobe** (compilación LGPL de BtbN) y **Deno**, todo verificado con SHA-256 al construir.
- Una ventanita de control: dirección, abrir la página, buscar actualización de yt-dlp, reiniciar para aplicarla y cerrar sifón (avisa si hay descargas en curso). Abrir sifón estando ya abierto solo muestra la página.
- **yt-dlp se actualiza solo**: una vez por día baja la versión nueva de PyPI, comprueba su hash, la prueba en un proceso aparte y la usa al reiniciar; si no arranca, se descarta. Se apaga con la casilla de la ventana o `SIFON_NO_AUTO_UPDATE=1`.
- Todo lo de 0.1.0 (límites, cancelación, protección contra redes privadas, archivos temporales que se borran solos) y el modo de código fuente (`install.cmd`, `run.cmd`, `update.cmd`) siguen igual.

## Qué se probó (2026-10-02, Windows 11 Home)

| Prueba | Resultado |
|---|---|
| Tests locales (sin red) | 462 pasaron |
| Tests de navegador | 17 pasaron |
| Eval con sitios reales (YouTube, SoundCloud, archive.org, Dailymotion) | 9 de 9 `PASS`; los 2 casos de Vimeo `KNOWN_DEAD` |
| Paquete con un `PATH` sin Python, FFmpeg, Deno ni Node (31 comprobaciones) | todas bien: arranque, FFmpeg/FFprobe/Deno incluidos, codificación MP3/Opus/AAC, actualización de yt-dlp con prioridad sobre la incluida, descarte de una actualización rota, instancia única, cierre ordenado |
| Descarga real con el paquete: `/api/info` y un MP3 de SoundCloud, verificado con el FFprobe incluido | bien |
| `sifon.exe` manejado por un navegador real: video 360p (AV1 + AAC) y MP3 de YouTube | bien |
| Instalador: instalación silenciosa sin administrador, prueba de lo instalado, desinstalación | bien: no queda programa, registro, acceso ni datos; el acceso se llama exactamente `sifón` |
| Revisión de seguridad independiente del actualizador, el lanzador y los flujos | 12 hallazgos; los corregibles están corregidos con tests de regresión (ver CHANGELOG) |

## Problemas conocidos

- El instalador no está firmado (SmartScreen).
- Windows 10 y un Windows recién instalado no se probaron en una máquina real; sí en un runner limpio de GitHub Actions (ver el resultado del CI del PR).
- El actualizador confía en PyPI por HTTPS (igual que `pip`); no protege contra un paquete malicioso publicado ahí.
- La compilación de FFmpeg viene de la versión "latest" de BtbN y se verifica con la lista de hashes del mismo release (integridad, no autenticidad del publicador).
- Un reinicio desde la ventana corta las descargas en curso (avisa antes).
- Los problemas conocidos de 0.1.0 siguen vigentes: solo YouTube, SoundCloud, archive.org y Dailymotion probados; Vimeo pide inicio de sesión; sin autenticación (no exponer a internet).

Reportar problemas: plantilla de Issues del repositorio, **sin cookies ni credenciales**. Vulnerabilidades: `SECURITY.md`.

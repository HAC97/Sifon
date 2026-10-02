# sifón

Descargador local de video y audio para Windows. Pegás el enlace de un video, elegís video (con la calidad que quieras) o solo audio (MP3, M4A u Opus) y bajás el archivo. Corre en tu computadora: un servidor FastAPI con [yt-dlp](https://github.com/yt-dlp/yt-dlp) y una página web propia que abrís en tu navegador. No hay cuentas, ni nube, ni anuncios.

![sifón con un video encontrado, listo para descargar](docs/screenshot.png)

- Los archivos se preparan en la carpeta temporal de tu equipo y se borran solos (ver [Archivos temporales](#archivos-temporales)).
- Solo escucha en `127.0.0.1`: nadie más en tu red puede usarlo. **No lo expongas a internet** (ver [Seguridad](#seguridad)).
- No inicia sesión en ningún sitio: los videos privados o con edad restringida no se pueden bajar.
- Bajá solo contenido sobre el que tengas derecho a hacerlo y respetá los términos de cada sitio.

## Requisitos

| Qué | Versión | Obligatorio | Probado con |
|---|---|---|---|
| Windows 10 u 11, 64 bits | | sí | Windows 11 Home |
| [Python](https://www.python.org/downloads/) | 3.10 o más nuevo | sí | 3.12.10 |
| [FFmpeg](https://ffmpeg.org/download.html) | cualquiera reciente | sí | 8.1.1 (compilación `full` de gyan.dev) |
| FFprobe | el que trae FFmpeg | no (ver abajo) | 8.1.1 |
| [Deno](https://deno.com) | 2.x | recomendado, para YouTube | ver [Versiones probadas](#versiones-probadas-y-limitaciones) |
| Conexión a internet | | sí | |

Linux y macOS **no están probados** y no se ofrecen como compatibles: los scripts son de Windows.

**FFmpeg** convierte el audio y une el video con el audio. Sin él, nada se descarga. **FFprobe** viene en el mismo paquete; sin él la app funciona (audio, video y fusión probados sin `ffprobe`), pero algunos videos HLS pueden fallar con el error `FFMPEG_MISSING`. **Deno** es el motor de JavaScript que yt-dlp usa para YouTube: sin Deno (ni Node.js) YouTube puede fallar o ofrecer menos calidades; las demás páginas no lo necesitan. Si Deno no está pero sí Node.js, sifón usa Node.js (menos probado).

Una forma de instalar los tres con `winget` (el instalador de paquetes de Windows):

```powershell
winget install Python.Python.3.12
winget install Gyan.FFmpeg
winget install DenoLand.Deno
```

Después de instalar, **cerrá la terminal y abrí otra** para que Windows vea los programas nuevos. Comprobá que están disponibles; cada comando debe imprimir una versión:

```powershell
py --version
ffmpeg -version
ffprobe -version
deno --version
```

Si `py --version` falla pero `python --version` imprime una versión, también sirve. Si un comando dice que no se reconoce, ese programa no está en el `PATH`. `install.cmd` hace estas comprobaciones por vos y se detiene con un mensaje claro si falta algo obligatorio.

## Descargar sifón

**Con ZIP** (no hace falta Git): en la página del repositorio en GitHub, botón verde **Code** → **Download ZIP**. Hacé clic derecho en el ZIP descargado → **Extraer todo…** y elegí una carpeta que puedas recordar (por ejemplo `C:\Users\vos\sifon`). Evitá carpetas dentro de OneDrive o del Escritorio sincronizado: el entorno virtual tiene miles de archivos chicos.

**Con Git:** `git clone` con la dirección que muestra el botón **Code**.

Después abrí una terminal **dentro de la carpeta del proyecto** (la que contiene `install.cmd` y `README.md`):

- En el Explorador de archivos, entrá a la carpeta, hacé clic en la barra de direcciones, escribí `powershell` y apretá Enter; o
- Clic derecho en un espacio vacío de la carpeta → **Abrir en Terminal**.

Para comprobar que estás en el lugar correcto, `dir` (o `ls`) tiene que mostrar `install.cmd`, `run.cmd` y `update.cmd`.

## Instalar

```powershell
.\install.cmd
```

(También podés hacer doble clic en `install.cmd`.) Hace, en orden: busca Python 3.10 o más nuevo, comprueba FFmpeg (y avisa si faltan FFprobe o Deno), crea el entorno virtual en `services\downloader\.venv`, instala las dependencias con `pip` y verifica el resultado. **Solo escribe dentro de la carpeta del proyecto**: no cambia el `PATH`, ni el registro, ni la política de ejecución de PowerShell, ni ningún Python global. Si algo falla, se detiene con un mensaje que dice qué pasó y qué hacer. Tarda unos minutos la primera vez.

`install.cmd` ejecuta el script con `-ExecutionPolicy Bypass` solo para ese proceso, así que no hace falta cambiar ninguna configuración de Windows. Si ejecutás `scripts\install.ps1` directamente y PowerShell lo bloquea, usá `install.cmd`.

Windows puede mostrar un aviso de SmartScreen al abrir un `.cmd` bajado de internet. Podés leer los scripts (son texto, en `scripts\`) antes de aceptar.

## Iniciar

```powershell
.\run.cmd
```

El lanzador comprueba que todo esté instalado, elige un puerto libre, muestra la dirección y **abre el navegador cuando el servidor ya responde**. La dirección normal es <http://127.0.0.1:8000>.

| Opción | Efecto |
|---|---|
| `.\run.cmd -Port 8765` | usa ese puerto; si está ocupado, se detiene con un mensaje |
| `.\run.cmd -NoBrowser` | no abre el navegador (abrí la dirección que muestra la ventana) |

Si no pasás `-Port` y el 8000 está ocupado, prueba del 8001 al 8020 y te dice cuál usó.

**Para cerrar la aplicación:** apretá `Ctrl+C` en la ventana de `run.cmd` (o cerrá la ventana). Las descargas en curso se cortan y sus archivos temporales se borran.

## Usar

1. Pegá el enlace del video. El botón **Pegar** lee el portapapeles (el navegador puede pedirte permiso la primera vez); con `Ctrl+V` dentro del campo también busca solo si el texto empieza con `http://` o `https://`.
2. Aparecen el título, la miniatura y las calidades disponibles. Elegí **Video** (con calidad) o **Solo audio** (MP3, M4A u Opus).
3. **Descargar.** Cuando termina, el navegador guarda el archivo en tu carpeta de descargas. **Cancelar descarga** corta una en curso.
4. La **✕** junto al enlace borra todo y vuelve al inicio para buscar otro video (queda desactivada mientras una descarga corre).

## Límites

Para que una descarga no sature tu equipo, sifón impone límites. Se cambian con variables de entorno **antes** de iniciar (valen solo para esa ventana):

| Variable | Por defecto | Qué limita |
|---|---|---|
| `SIFON_MAX_CONCURRENT` | 2 | descargas a la vez |
| `SIFON_MAX_QUEUE` | 10 | descargas en curso + en cola; la siguiente se rechaza (`QUEUE_FULL`) |
| `SIFON_MAX_FILESIZE_MB` | 2048 | tamaño de cada archivo bajado; si lo supera se aborta (`TOO_LARGE`) |
| `SIFON_MAX_DURATION_MIN` | 180 | duración del video; las transmisiones en vivo se rechazan (`TOO_LONG`) |
| `SIFON_MIN_FREE_DISK_MB` | 1024 | espacio libre mínimo; por debajo no se acepta ni se sigue una descarga (`DISK_FULL`) |
| `SIFON_TTL_MINUTES` | 30 | cuánto dura un archivo terminado antes de borrarse |
| `SIFON_MAX_MEMORY_MB` | 4096 | memoria máxima del servidor (Windows). Una página hostil que no termina nunca no puede agotar la RAM de tu equipo: la descarga falla en su lugar |

```powershell
$env:SIFON_MAX_FILESIZE_MB = "500"; $env:SIFON_MAX_DURATION_MIN = "30"
.\run.cmd
```

En `cmd.exe`: `set SIFON_MAX_FILESIZE_MB=500` y después `run.cmd`. Un valor que no es un entero positivo hace que `run.cmd` se detenga con el nombre de la variable. El límite de tamaño se aplica a cada archivo descargado: un video con audio separado baja dos, así que el total puede acercarse al doble. El límite de espacio libre se mide en la unidad de la carpeta temporal y se comprueba mientras se descarga, no durante la conversión final de ffmpeg.

## Archivos temporales

Mientras se descarga y se convierte, sifón trabaja en una carpeta dentro de la carpeta temporal de Windows (`%TEMP%\sifon-<número>`). El archivo que recibís en el navegador es una copia que baja de esa carpeta; sifón no guarda nada en la carpeta del proyecto. Se borra:

- **de inmediato**, los archivos parciales de una descarga que falla o que cancelás;
- **`SIFON_TTL_MINUTES` minutos (30 por defecto) después de terminar**, el archivo de una descarga completada (si querés bajarlo otra vez, hacelo antes);
- **al cerrar la aplicación** con `Ctrl+C`, todo;
- **al iniciar de nuevo**, lo que haya dejado una ejecución anterior que se cortó sin cerrar bien (por ejemplo, si apagaste la compu), una vez que pasaron 10 minutos sin señal de vida de esa ejecución.

`services\downloader\jobs.log` guarda una línea por descarga (fecha, modo, resultado, duración, código de error y solo el dominio del sitio, nunca la URL completa). Está ignorado por Git y podés borrarlo cuando quieras.

## Actualizar yt-dlp

yt-dlp se rompe cuando un sitio cambia su página; la mayoría de los errores de "no se pudo descargar" se arreglan actualizándolo. Cerrá sifón y ejecutá:

```powershell
.\update.cmd
```

Actualiza `yt-dlp[default,curl-cffi]` (yt-dlp con `yt-dlp-ejs` y `curl-cffi`), comprueba que el entorno quede consistente y que `yt-dlp-ejs` coincida con la versión que pide yt-dlp, y muestra las versiones antes y después. **Solo dice "Actualización verificada" si todas las comprobaciones pasaron**; si algo falla, se detiene con el motivo. Después reiniciá con `run.cmd`.

## Problemas frecuentes

| Síntoma | Qué hacer |
|---|---|
| `install.cmd`: "No encontré Python" | Instalá Python desde python.org o con `winget`; cerrá la terminal y abrí otra. El Python de la Microsoft Store (el que se abre al escribir `python` sin tenerlo instalado) no cuenta. |
| "No encontré ffmpeg" / error `FFMPEG_MISSING` | Instalá FFmpeg, abrí una terminal nueva y comprobá `ffmpeg -version`. Después reiniciá sifón. |
| YouTube falla o muestra pocas calidades | Instalá Deno (`winget install DenoLand.Deno`), abrí una terminal nueva y ejecutá `update.cmd`. |
| "El puerto 8000 ya está en uso" | Otra aplicación lo usa. Sin `-Port`, sifón busca uno libre solo; con `-Port`, elegí otro. |
| "No se pudo descargar el video. Probá de nuevo o actualizá yt-dlp" | Ejecutá `update.cmd` y reiniciá. |
| `LOGIN_REQUIRED` | El video es privado, de miembros o requiere edad: sifón no inicia sesión. |
| `BLOCKED_ADDRESS` | El enlace (o una redirección) apunta a una dirección de red local; está bloqueado a propósito. |
| PowerShell dice que la ejecución de scripts está deshabilitada | Usá los `.cmd` (`install.cmd`, `run.cmd`, `update.cmd`), que no dependen de esa configuración. |

Si nada de esto ayuda, abrí un reporte con la plantilla de **Issues** del repositorio. Te pide las versiones y los pasos. **No adjuntes cookies, contraseñas, tokens ni enlaces privados.**

## Seguridad

- El servidor escucha únicamente en `127.0.0.1` y rechaza pedidos cuyo `Host` u `Origin` no sean locales (protege de páginas web que intenten usarlo desde tu navegador).
- Todo el tráfico de yt-dlp pasa por un proxy interno que resuelve cada nombre una sola vez y **rechaza cualquier destino que no sea una dirección pública**, incluidas las redirecciones y los cambios de DNS (la protección contra acceder a tu red local o a `127.0.0.1` a través de un enlace). Si usabas un proxy de empresa para salir a internet, esta versión no lo respeta, y mientras corre ignora las variables `NO_PROXY` y `ALL_PROXY` de tu entorno (para que ni ffmpeg ni yt-dlp puedan saltarse la protección).
- **Esta versión no está preparada para exponerse directamente a internet ni a tu red local.** No tiene autenticación. No uses `--host 0.0.0.0`, ni túneles, ni un proxy inverso hacia ella.

Detalles técnicos y cómo reportar una vulnerabilidad: [`services/downloader/README.md`](services/downloader/README.md) y [`SECURITY.md`](SECURITY.md).

## Versiones probadas y limitaciones

Probado el 2026-10-02 en Windows 11 Home (compilación 10.0.26300), con Python 3.12.10, FFmpeg/FFprobe 8.1.1, yt-dlp 2026.08.19, yt-dlp-ejs 0.8.0, curl-cffi 0.16.3 y FastAPI 0.142.2. Los resultados de las pruebas y las limitaciones están en [`CHANGELOG.md`](CHANGELOG.md) y en [`docs/release-notes-v0.1.0.md`](docs/release-notes-v0.1.0.md).

## Estructura

```
install.cmd, run.cmd, update.cmd   lanzadores (ejecutan scripts\*.ps1 sin cambiar la política de ejecución)
scripts/                           install.ps1, run.ps1, update-ytdlp.ps1, check_env.py, gen_contract.py
contracts/api.openapi.json         contrato HTTP (generado)
services/downloader/               backend, tests y evals (ver su README)
web/                               interfaz (index.html, app.js, style.css)
```

Desarrollo y tests: [`services/downloader/README.md`](services/downloader/README.md). Componentes de terceros: [`THIRD_PARTY.md`](THIRD_PARTY.md).

## Licencia

[MIT](LICENSE). Las dependencias que instala `install.cmd` y los programas externos (FFmpeg, Deno) tienen sus propias licencias; ver [`THIRD_PARTY.md`](THIRD_PARTY.md).

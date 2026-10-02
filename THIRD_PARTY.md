# Recursos y componentes de terceros

## Incluido en este repositorio

Nada de terceros. Se revisó el árbol completo (`git ls-files`):

- **Código:** escrito para este proyecto, bajo la licencia MIT de `LICENSE`.
- **Interfaz (`web/`):** HTML, CSS y JavaScript propios, sin librerías ni frameworks. No carga fuentes, scripts ni imágenes desde internet. El CSS nombra fuentes que ya trae Windows (Bahnschrift, Segoe UI) y no las incluye.
- **Ícono (`web/favicon.svg`) y logo (SVG en línea en `web/index.html`):** dibujados para este proyecto.
- **`docs/screenshot.png`:** captura de la interfaz de sifón mostrando el video *Big Buck Bunny* (© Blender Foundation, https://peach.blender.org, licencia [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/)): se ve su miniatura y su título. La interfaz de la captura es de este proyecto (MIT); la miniatura, de la Blender Foundation. Está solo en la documentación y no forma parte del programa.

## Que se instala aparte (no se distribuye aquí)

`install.cmd` descarga estas dependencias de PyPI dentro de `services/downloader/.venv`. Cada una se rige por su propia licencia. Licencias leídas de los metadatos de los paquetes instalados el 2026-10-02:

| Componente | Versión probada | Licencia | Para qué |
|---|---|---|---|
| yt-dlp | 2026.8.19 | Unlicense | extrae y descarga los videos |
| yt-dlp-ejs | 0.8.0 | Unlicense AND MIT AND ISC | resuelve los desafíos de JavaScript de YouTube |
| curl-cffi | 0.16.3 | MIT | imita un navegador (Dailymotion y similares) |
| FastAPI | 0.142.2 | MIT | servidor HTTP |
| Starlette | 1.7.0 | BSD-3-Clause | base de FastAPI |
| Pydantic | 2.13.5 | MIT | validación de datos |
| Uvicorn | 0.54.0 | BSD-3-Clause | servidor ASGI |
| requests | 2.34.2 | Apache-2.0 | red de yt-dlp |
| urllib3 | 2.8.0 | MIT | red de yt-dlp |
| websockets | 17.1 | BSD-3-Clause | red de yt-dlp |
| certifi | 2026.7.22 | MPL-2.0 | certificados raíz |
| mutagen | 1.48.1 | GPL-2.0-or-later | metadatos de audio; lo instala yt-dlp, sifón no lo importa |
| pycryptodomex | 3.23.0 | BSD, Public Domain | descifrado de streams HLS |

Solo para desarrollo (`install.cmd -Dev`): pytest (MIT), httpx (BSD-3-Clause), jsonschema (MIT) y Playwright (Apache-2.0).

## Programas externos que instala el usuario

sifón no los incluye ni los redistribuye; los busca en el `PATH`.

- **FFmpeg / FFprobe:** licencia LGPL o GPL según la compilación que elijas. Ver https://ffmpeg.org/legal.html.
- **Deno:** MIT. Ver https://deno.com.

## Contenido descargado

sifón no incluye ni aloja contenido. Quien lo usa es responsable de tener derecho a descargar lo que baja y de respetar los términos de cada sitio.

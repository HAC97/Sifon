# Seguridad

## Qué cubre y qué no

sifón es una aplicación **local**: pensada para correr en tu propia computadora y usarse desde tu propio navegador.

- El servidor escucha solo en `127.0.0.1`.
- **No está preparado para exponerse a internet ni a tu red local.** No tiene login ni cuentas, y cualquiera que llegue al puerto puede iniciar descargas en tu equipo. No lo publiques con un proxy inverso, un túnel ni `--host 0.0.0.0`.

Detalle de las defensas (Host/Origin, bloqueo de redes privadas, límites) en `services/downloader/README.md`, sección "Seguridad".

## El paquete de Windows y las actualizaciones de yt-dlp

El instalador y el ZIP portable no están firmados digitalmente; se comprueban con `SHA256SUMS.txt` (ver el README) y los construye el flujo `release.yml` a partir del código del repositorio, que solo corre para un tag `vX.Y.Z` cuyo commit esté en `main`, con permisos de solo lectura durante la compilación y las pruebas, y que adjunta los archivos a un **borrador** de release sin reemplazar nunca los de uno ya publicado. Las acciones de GitHub que usa están fijadas por SHA, y Deno e Inno Setup por hash.

El paquete descarga una vez por día, de PyPI y por HTTPS, una versión nueva de yt-dlp (y de `yt-dlp-ejs`), y la ejecuta. Antes de usarla comprueba que el SHA-256 coincida con el que PyPI publica, solo acepta URL `https` de `pypi.org` y `files.pythonhosted.org` (también al seguir redirecciones), exige un número de versión estricto, extrae solo los paquetes `yt_dlp` y `yt_dlp_ejs` (rechaza rutas fuera de la carpeta, enlaces simbólicos, tamaños desmedidos y nombres con caracteres raros) y la prueba en un proceso aparte; si falla, la descarta. **No protege contra un paquete malicioso publicado en PyPI**: es la misma confianza que `pip install` y `update.cmd`. Se desactiva con `SIFON_NO_AUTO_UPDATE=1` o con la casilla de la ventana.

## Reportar una vulnerabilidad

Si encontrás una falla de seguridad, **no abras un issue público**. Usá "Report a vulnerability" en la pestaña Security del repositorio (reporte privado de GitHub). Incluí la versión de sifón (`/api/health`), los pasos para reproducirla y el impacto que ves.

Para errores que no son de seguridad, usá la plantilla de "Reporte de error". No adjuntes nunca cookies, contraseñas, tokens ni enlaces privados.

# Seguridad

## Qué cubre y qué no

sifón es una aplicación **local**: pensada para correr en tu propia computadora y usarse desde tu propio navegador.

- El servidor escucha solo en `127.0.0.1`.
- **No está preparado para exponerse a internet ni a tu red local.** No tiene login ni cuentas, y cualquiera que llegue al puerto puede iniciar descargas en tu equipo. No lo publiques con un proxy inverso, un túnel ni `--host 0.0.0.0`.

Detalle de las defensas (Host/Origin, bloqueo de redes privadas, límites) en `services/downloader/README.md`, sección "Seguridad".

## Reportar una vulnerabilidad

Si encontrás una falla de seguridad, **no abras un issue público**. Usá "Report a vulnerability" en la pestaña Security del repositorio (reporte privado de GitHub). Incluí la versión de sifón (`/api/health`), los pasos para reproducirla y el impacto que ves.

Para errores que no son de seguridad, usá la plantilla de "Reporte de error". No adjuntes nunca cookies, contraseñas, tokens ni enlaces privados.

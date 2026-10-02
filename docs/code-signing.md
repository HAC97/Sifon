# Firma de código con SignPath Foundation

SignPath Foundation firma gratis los instaladores de proyectos de código abierto. Los requisitos salen de https://signpath.org/terms (revisalos antes de solicitar: pueden cambiar). El estado del proyecto frente a cada uno:

| Requisito | Estado |
|---|---|
| Licencia OSI sin doble licencia comercial | Cumple (MIT) |
| Sin código propietario | Cumple (FFmpeg LGPL, Deno MIT, Python, yt-dlp: todos abiertos) |
| Proyecto mantenido y **ya publicado en la forma que se firma** | Publicar primero el release sin firmar |
| Funcionalidad documentada en la página de descarga | Cumple (README) |
| Autenticación en dos pasos en GitHub y en SignPath | Tuya: activarla |
| Aprobación manual de cada firma | Se hace en el panel de SignPath |
| Metadatos del binario (nombre, versión) | Cumple (`packaging/build.py` los escribe en `sifon.exe`) |
| Sin malware ni programas potencialmente no deseados | Lo decide SignPath |
| Política de firma de código en la página del proyecto | En el README (sección "Política de firma de código") |
| Privacidad: política o declaración | En el README (sección "Privacidad") |
| Instrucciones de desinstalación | En el README |

## Pasos

1. Publicar el release (por ejemplo `v0.2.0`) y comprobar que el README ya tiene las secciones **Privacidad** y **Política de firma de código**.
2. Activar la verificación en dos pasos en GitHub.
3. Solicitar la suscripción en https://signpath.org/apply con el nombre del proyecto, la URL `https://github.com/HAC97/Sifon`, la licencia y la descripción. Mencionar que el binario lo construye GitHub Actions y que el programa solo se conecta a PyPI para buscar actualizaciones de yt-dlp.
4. Si la aprueban, SignPath crea la organización y un proyecto. Hay que dejar anotados el **identificador de organización**, el **slug del proyecto**, el **slug de la política de firma** y un **token de API** (guardado como secreto `SIGNPATH_API_TOKEN` del repositorio).
5. Cuando tengas esos datos, el cambio en el repositorio es este (no está hecho porque no se puede probar antes de la aprobación):
   - `release.yml`: después de compilar, subir `dist/sifon-*-setup.exe` y `dist/sifon/sifon.exe` como artefacto y enviarlos con la acción oficial `signpath/github-action-submit-signing-request` (fijada por SHA, como las demás), esperando el resultado; el job de publicación usa los archivos firmados.
   - **Orden de firma:** `sifon.exe` se firma **antes** de empaquetarlo en el instalador y el ZIP, y después se firma el instalador. Hoy `build.py` genera todo junto: habría que separarlo en dos etapas.
   - `SHA256SUMS.txt` se calcula sobre los archivos ya firmados.
   - Actualizar el README: quitar "todavía no están firmados" y poner el aviso de SmartScreen solo como posible los primeros días (la reputación se construye con las descargas).
6. Cada release exige aprobar la firma a mano en el panel de SignPath antes de que el flujo continúe.

## Mientras tanto

- Publicar en winget (ver `packaging/winget/README.md`).
- Si Defender marca un release por error, enviarlo en https://www.microsoft.com/wdsi/filesubmission como falso positivo.

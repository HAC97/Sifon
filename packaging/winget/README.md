# Publicar sifón en winget

Con esto la gente instala con `winget install HAC97.sifon`. **Hacelo después de publicar el release de esa versión**: el manifiesto apunta al instalador del release y a su hash.

## 1. Generar los manifiestos

```powershell
python packaging\winget\make_manifest.py 0.2.0
```

Toma la URL del instalador, su SHA-256 (de `SHA256SUMS.txt` del release) y la fecha de publicación, y escribe cuatro archivos en `dist\winget\manifests\h\HAC97\sifon\0.2.0\`. No hay que copiar ningún hash a mano.

## 2. Validar

```powershell
winget validate --manifest dist\winget\manifests\h\HAC97\sifon\0.2.0
```

Tiene que decir "Validación del manifiesto correcta" sin advertencias. (Para probar la instalación local: `winget settings --enable LocalManifestFiles`, que pide administrador, y después `winget install --manifest <carpeta>`.)

## 3. Enviar a microsoft/winget-pkgs

**Camino directo, sin herramientas extra:**

1. Hacé un *fork* de https://github.com/microsoft/winget-pkgs y cloná tu fork.
2. Copiá la carpeta `manifests\h\HAC97\sifon\0.2.0` a la misma ruta dentro de tu fork.
3. Subila a una rama y abrí un Pull Request contra `microsoft/winget-pkgs`.
4. Un bot pide aceptar el CLA: comentá `@microsoft-github-policy-service agree`.
5. Corre su validación automática (instala el paquete en una máquina limpia y lo escanea) y después lo revisan personas. Si marca algo, lo dice en el PR; corregilo y volvé a generar solo si **el release no cambió** (ver abajo).

**Con `wingetcreate`** (`winget install wingetcreate`): `wingetcreate submit --help` muestra cómo enviar una carpeta de manifiestos ya generada, usando un token de GitHub tuyo. No lo usé; la guía de arriba sí es la que se probó hasta la validación.

## Versiones nuevas

Repetí los pasos 1 a 3 con la versión nueva. **Nunca reemplaces los archivos de un release ya enviado a winget**: el hash dejaría de coincidir. `release.yml` ya se niega a reemplazar los de un release publicado.

## Qué hay que mantener igual

- `PackageIdentifier` `HAC97.sifon`, `PackageName` `sifón` y `Publisher` `HAC97`: tienen que coincidir con lo que el instalador registra en *Agregar o quitar programas* (`AppName` y `AppPublisher` en `packaging/installer.iss`). Un test lo comprueba.
- `ProductCode`: es el `AppId` de `installer.iss` más `_is1`. Un test lo comprueba. Si cambiás el `AppId`, se rompen las actualizaciones.

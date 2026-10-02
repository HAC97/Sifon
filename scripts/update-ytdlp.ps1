# Actualiza yt-dlp junto con sus componentes (yt-dlp-ejs, curl-cffi) dentro del entorno de sifón.
# Solo informa éxito si pip terminó bien, el entorno es consistente y yt-dlp-ejs coincide con
# la versión que pide yt-dlp. Cerrá sifón antes (Windows bloquea archivos en uso).
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'services\downloader\.venv\Scripts\python.exe'
$checkEnv = Join-Path $PSScriptRoot 'check_env.py'

function Fail($problem, $fix) {
    Write-Host ''
    Write-Host "ERROR: $problem" -ForegroundColor Red
    if ($fix) { Write-Host "Qué hacer: $fix" -ForegroundColor Yellow }
    exit 1
}

if (-not (Test-Path $python)) {
    Fail 'Falta el entorno virtual: sifón todavía no está instalado.' 'Ejecutá install.cmd primero.'
}

$before = & $python $checkEnv --versions
Write-Host "Antes:   $before"

& $python -m pip install --disable-pip-version-check --upgrade --upgrade-strategy eager 'yt-dlp[default,curl-cffi]'
if ($LASTEXITCODE -ne 0) {
    Fail 'pip no pudo actualizar yt-dlp.' 'Cerrá sifón si está abierto, revisá tu conexión y repetí. El entorno anterior puede seguir funcionando.'
}

& $python -m pip check --disable-pip-version-check
if ($LASTEXITCODE -ne 0) {
    Fail 'Después de actualizar, pip check encontró dependencias incompatibles (arriba).' 'Repetí la actualización; si sigue igual, ejecutá install.cmd y abrí un reporte de problema.'
}

& $python $checkEnv --libs-only
if ($LASTEXITCODE -ne 0) {
    Fail 'La verificación posterior a la actualización falló (líneas FAIL arriba).' 'No uses esta instalación hasta repararla: ejecutá install.cmd.'
}

# pip exits 0 with "already satisfied" when the index is unreachable, so ask the index itself.
& $python $checkEnv --up-to-date
if ($LASTEXITCODE -ne 0) {
    Fail 'No se pudo confirmar que yt-dlp esté en la última versión (línea FAIL arriba).' 'Revisá tu conexión a internet y repetí la actualización.'
}

$after = & $python $checkEnv --versions
Write-Host ''
Write-Host "Antes:   $before"
Write-Host "Después: $after"
if ($before -eq $after) {
    Write-Host 'Ya estaba al día; no hubo cambios.' -ForegroundColor Green
} else {
    Write-Host 'Actualización verificada.' -ForegroundColor Green
}
Write-Host 'Reiniciá sifón (run.cmd) para usar la versión nueva.'

# Instala sifón: comprueba los requisitos, crea el entorno virtual del proyecto e instala las
# dependencias. Solo escribe dentro de services\downloader\.venv. No toca el PATH, el registro,
# la política de ejecución ni ningún Python global.
#
#   .\install.cmd            instalación normal
#   .\install.cmd -Dev       además las dependencias para correr los tests
param([switch]$Dev)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $PSScriptRoot
$service = Join-Path $root 'services\downloader'
$venv = Join-Path $service '.venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'
$checkEnv = Join-Path $PSScriptRoot 'check_env.py'

function Step($text) { Write-Host ''; Write-Host "==> $text" -ForegroundColor Cyan }
function Fail($problem, $fix) {
    Write-Host ''
    Write-Host "ERROR: $problem" -ForegroundColor Red
    if ($fix) { Write-Host "Qué hacer: $fix" -ForegroundColor Yellow }
    Write-Host 'La instalación se detuvo. No se cambió nada fuera de esta carpeta.' -ForegroundColor Red
    exit 1
}

if ($env:OS -ne 'Windows_NT') {
    Fail 'sifón solo está probado en Windows.' 'Usá una computadora con Windows 10 u 11.'
}

# --- 1. Python ---------------------------------------------------------------------------------
Step 'Buscando Python 3.10 o más nuevo'
$python = $null
$candidates = @(
    @{ Exe = 'py'; Args = @('-3') },
    @{ Exe = 'python'; Args = @() },
    @{ Exe = 'python3'; Args = @() }
)
foreach ($candidate in $candidates) {
    if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }
    try {
        # The Microsoft Store stub for python.exe prints a hint instead of a version: it fails this test.
        $out = & $candidate.Exe @($candidate.Args) -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    } catch { continue }
    if ($LASTEXITCODE -ne 0 -or "$out" -notmatch '^\d+\.\d+$') { continue }
    $parts = "$out".Split('.')
    if ([int]$parts[0] -gt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10)) {
        $python = $candidate
        $pythonVersion = "$out"
        break
    }
}
if (-not $python) {
    Fail 'No encontré Python 3.10 o más nuevo.' 'Instalalo desde https://www.python.org/downloads/ marcando "Add python.exe to PATH", cerrá esta ventana, abrí otra y repetí.'
}
Write-Host "Python $pythonVersion ($($python.Exe))"
if ($pythonVersion -ne '3.12') {
    Write-Host 'Aviso: la versión probada del proyecto es 3.12; otras pueden funcionar, pero no están probadas.' -ForegroundColor Yellow
}

# --- 2. Programas externos ---------------------------------------------------------------------
Step 'Comprobando ffmpeg'
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Fail 'No encontré ffmpeg en el PATH. Sin él no se puede descargar video ni convertir audio.' 'Instalalo (por ejemplo: winget install Gyan.FFmpeg), cerrá esta ventana, abrí otra y repetí. Comprobá con: ffmpeg -version'
}
& ffmpeg -version *> $null
if ($LASTEXITCODE -ne 0) { Fail 'ffmpeg está en el PATH pero no se pudo ejecutar.' 'Reinstalalo y comprobá con: ffmpeg -version' }
Write-Host 'ffmpeg OK'
if (-not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    Write-Host 'Aviso: no encontré ffprobe. Es opcional: la app funciona sin él, salvo algunos videos HLS.' -ForegroundColor Yellow
}
if (-not (Get-Command deno -ErrorAction SilentlyContinue)) {
    Write-Host 'Aviso: no encontré Deno. YouTube puede fallar o mostrar menos calidades sin un motor de JavaScript.' -ForegroundColor Yellow
    Write-Host '       Instalalo con: winget install DenoLand.Deno  (opcional; las demás páginas funcionan sin él).' -ForegroundColor Yellow
}

# --- 3. Entorno virtual ------------------------------------------------------------------------
Step 'Creando el entorno virtual en services\downloader\.venv'
if (Test-Path $venvPython) {
    & $venvPython -c 'import sys' *> $null
    if ($LASTEXITCODE -ne 0) {
        Fail 'El entorno virtual existente está roto.' "Borrá la carpeta $venv y repetí la instalación."
    }
    Write-Host 'Ya existía; se reutiliza.'
} else {
    & $python.Exe @($python.Args) -m venv $venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        Fail 'No se pudo crear el entorno virtual.' 'Si Python viene de la Microsoft Store, instalá el de python.org. Detalle del error arriba.'
    }
}

# --- 4. Dependencias ---------------------------------------------------------------------------
Step 'Instalando dependencias (puede tardar unos minutos)'
$requirements = if ($Dev) { 'requirements-dev.txt' } else { 'requirements.txt' }
& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $service $requirements)
if ($LASTEXITCODE -ne 0) {
    Fail 'pip no pudo instalar las dependencias.' 'Revisá tu conexión a internet y repetí. Si el error nombra un paquete, copiá ese texto en un reporte de problema.'
}

# --- 5. Verificación ---------------------------------------------------------------------------
Step 'Verificando la instalación'
& $venvPython $checkEnv
if ($LASTEXITCODE -ne 0) {
    Fail 'La verificación encontró un problema (líneas FAIL arriba).' 'Corregilo y repetí la instalación.'
}

Write-Host ''
Write-Host 'Listo. Para iniciar sifón ejecutá: run.cmd' -ForegroundColor Green

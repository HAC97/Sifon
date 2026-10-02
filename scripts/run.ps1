# Inicia sifón en http://127.0.0.1:<puerto> y abre el navegador cuando el servidor responde.
# Se cierra con Ctrl+C en esta ventana (o cerrando la ventana).
#
#   .\run.cmd                  puerto 8000 (si está ocupado, prueba 8001 a 8020)
#   .\run.cmd -Port 8765       un puerto concreto (si está ocupado, se detiene)
#   .\run.cmd -NoBrowser       no abre el navegador
param([int]$Port = 0, [switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $PSScriptRoot
$service = Join-Path $root 'services\downloader'
$python = Join-Path $service '.venv\Scripts\python.exe'
$checkEnv = Join-Path $PSScriptRoot 'check_env.py'

function Fail($problem, $fix) {
    Write-Host ''
    Write-Host "ERROR: $problem" -ForegroundColor Red
    if ($fix) { Write-Host "Qué hacer: $fix" -ForegroundColor Yellow }
    exit 1
}

function Test-PortBusy([int]$p) {
    $listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    return [bool]($listeners | Where-Object { $_.Port -eq $p })
}

if (-not (Test-Path $python)) {
    Fail 'Falta el entorno virtual: sifón todavía no está instalado.' 'Ejecutá install.cmd primero.'
}

# Libraries, programs and SIFON_* settings. WARN lines are shown and do not stop the start.
$report = & $python $checkEnv
$checkExit = $LASTEXITCODE
$report | Where-Object { $_ -match '^(WARN|FAIL)' } | ForEach-Object { Write-Host $_ -ForegroundColor Yellow }
if ($checkExit -ne 0) {
    Fail 'Falta algo para poder iniciar (líneas FAIL arriba).' 'Ejecutá install.cmd para repararlo.'
}

if ($Port -ne 0) {
    if ($Port -lt 1024 -or $Port -gt 65535) { Fail "Puerto inválido: $Port." 'Usá un número entre 1024 y 65535.' }
    if (Test-PortBusy $Port) {
        Fail "El puerto $Port ya está en uso." 'Elegí otro con -Port, por ejemplo: run.cmd -Port 8765'
    }
} else {
    $Port = 8000
    while ((Test-PortBusy $Port) -and $Port -lt 8020) { $Port++ }
    if (Test-PortBusy $Port) {
        Fail 'Los puertos 8000 a 8020 están todos en uso.' 'Elegí uno libre con -Port, por ejemplo: run.cmd -Port 9000'
    }
    if ($Port -ne 8000) { Write-Host "El puerto 8000 está ocupado; se usa el $Port." -ForegroundColor Yellow }
}

$url = "http://127.0.0.1:$Port"
Write-Host ''
Write-Host "sifón escucha en $url (solo en esta computadora)." -ForegroundColor Green
Write-Host 'Para cerrarlo: Ctrl+C en esta ventana.'
Write-Host ''

$server = Start-Process -FilePath $python -WorkingDirectory $service -NoNewWindow -PassThru -ArgumentList @(
    '-m', 'uvicorn', 'app.main:create_app', '--factory', '--host', '127.0.0.1', '--port', "$Port"
)
try {
    $ready = $false
    for ($i = 0; $i -lt 60 -and -not $server.HasExited; $i++) {
        try {
            $health = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 2
            if ($health.ok) { $ready = $true; break }
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if ($server.HasExited) {
        Fail 'El servidor se cerró al arrancar (el motivo está en el texto de arriba).' 'Si no se entiende, copialo en un reporte de problema (sin datos personales).'
    }
    if (-not $ready) {
        Fail 'El servidor no respondió en 30 segundos.' 'Cerralo con Ctrl+C y probá otra vez; si se repite, abrí un reporte de problema.'
    }
    Write-Host "Listo: $url" -ForegroundColor Green
    if (-not $NoBrowser) { Start-Process $url }
    $server.WaitForExit()
} finally {
    if (-not $server.HasExited) { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }
}

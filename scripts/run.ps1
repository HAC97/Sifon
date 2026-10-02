param([int]$Port = 8000)

$root = Split-Path -Parent $PSScriptRoot
$service = Join-Path $root "services\downloader"
$python = Join-Path $service ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "Falta el entorno virtual. Ejecutá: python -m venv services\downloader\.venv; services\downloader\.venv\Scripts\python.exe -m pip install -r services\downloader\requirements.txt"
    exit 1
}

Set-Location $service
Write-Host "VideoDownloader en http://127.0.0.1:$Port"
& $python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port $Port

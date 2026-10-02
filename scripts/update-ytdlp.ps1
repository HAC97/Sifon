$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "services\downloader\.venv\Scripts\python.exe"

& $python -m pip install -U yt-dlp
& $python -c "import yt_dlp.version as v; print('yt-dlp', v.__version__)"
Write-Host "Reiniciá la app para usar la nueva versión."

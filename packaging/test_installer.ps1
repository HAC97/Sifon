# Installs the built setup silently (per user, no administrator), runs the smoke test against the
# installed copy, uninstalls, and checks that nothing is left behind. Exits 1 on any failed check.
#   .\packaging\test_installer.ps1 -Setup dist\sifon-0.2.0-setup.exe -Python python -YtdlpSrc <site-packages>
param(
    [Parameter(Mandatory)][string]$Setup,
    [string]$Python = 'python',
    [string]$YtdlpSrc = ''
)
$ErrorActionPreference = 'Stop'
$failures = @()
function Check($name, [bool]$ok) {
    if ($ok) { Write-Host "PASS  $name" } else { Write-Host "FAIL  $name" -ForegroundColor Red; $script:failures += $name }
}

$here = Split-Path -Parent $PSCommandPath
$setupPath = (Resolve-Path $Setup).Path
$target = Join-Path $env:TEMP 'sifon-installed-test'
$guid = '{6F1D2E8B-3B7A-4C55-9E0A-5A1F2C7D9B31}_is1'
$uninstKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$guid"
$data = Join-Path $env:LOCALAPPDATA 'sifon'
if (Test-Path $target) { Remove-Item -Recurse -Force $target }

$p = Start-Process -FilePath $setupPath -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=$target", "/LOG=$env:TEMP\sifon-setup.log" -Wait -PassThru
Check 'setup exits with 0 (no administrator needed)' ($p.ExitCode -eq 0)
Check 'sifon.exe is installed' (Test-Path "$target\sifon.exe")
Check 'bundled ffmpeg is installed' (Test-Path "$target\bin\ffmpeg.exe")
Check 'an uninstaller is installed' (Test-Path "$target\unins000.exe")
Check 'it is registered for uninstall under the current user' (Test-Path $uninstKey)
Check 'a Start Menu shortcut exists' (@(Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu\Programs" -Filter 'sif*.lnk' -ErrorAction SilentlyContinue).Count -ge 1)

$smoke = @("$here\smoke_test.py", $target)
if ($YtdlpSrc) { $smoke += @('--ytdlp-src', $YtdlpSrc) }
& $Python @smoke
Check 'smoke test of the installed copy passes' ($LASTEXITCODE -eq 0)

Check 'the data folder exists before uninstalling' (Test-Path $data)
$u = Start-Process -FilePath "$target\unins000.exe" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait -PassThru
Check 'uninstaller exits with 0' ($u.ExitCode -eq 0)
Start-Sleep -Seconds 3
Check 'the program folder is gone' (-not (Test-Path "$target\sifon.exe"))
Check 'no files are left in the program folder' (-not (Test-Path $target) -or ((Get-ChildItem $target -Recurse -File | Measure-Object).Count -eq 0))
Check 'the uninstall registration is removed' (-not (Test-Path $uninstKey))
Check 'the per-user data folder is removed' (-not (Test-Path $data))
Check 'the Start Menu shortcut is removed' (@(Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu\Programs" -Filter 'sif*.lnk' -ErrorAction SilentlyContinue).Count -eq 0)

if ($failures.Count -gt 0) { Write-Host "`n$($failures.Count) check(s) failed." -ForegroundColor Red; exit 1 }
Write-Host "`nAll installer checks passed."

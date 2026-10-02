# Installs Inno Setup 6.7.3 from its official GitHub release into a temporary folder (no admin,
# nothing global), after checking the SHA-256 pinned below. In GitHub Actions it exports the path
# of ISCC.exe as the ISCC environment variable for the following steps.
param([string]$Dir = (Join-Path ($(if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP })) 'inno'))
$ErrorActionPreference = 'Stop'

$version = '6.7.3'
$sha256 = '9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732'
$url = "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-$version.exe"
$installer = Join-Path ($(if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP })) "innosetup-$version.exe"

Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
$actual = (Get-FileHash $installer -Algorithm SHA256).Hash.ToLower()
if ($actual -ne $sha256) {
    Remove-Item $installer -Force
    throw "Inno Setup SHA-256 mismatch: expected $sha256, got $actual"
}
Start-Process -FilePath $installer -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', "/DIR=$Dir", '/NOICONS' -Wait
$iscc = Join-Path $Dir 'ISCC.exe'
if (-not (Test-Path $iscc)) { throw "ISCC.exe was not installed in $Dir" }
Write-Host "Inno Setup $version ready: $iscc"
if ($env:GITHUB_ENV) { Add-Content -Path $env:GITHUB_ENV -Value "ISCC=$iscc" }

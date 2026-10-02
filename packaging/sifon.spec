# PyInstaller spec for sifon.exe (one folder, windowed). Run through packaging/build.py, which
# prepares build/ (icon, version resource, bundled.json) first.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
SERVICE = ROOT / "services" / "downloader"
BUILD = ROOT / "build"

datas = [(str(ROOT / "web"), "web"), (str(BUILD / "bundled.json"), "."), (str(BUILD / "sifon.ico"), ".")]
binaries = []
hiddenimports = []

# yt-dlp loads its ~1900 extractors by name, and ships yt-dlp-ejs as data.
hiddenimports += collect_submodules("yt_dlp")
datas += collect_data_files("yt_dlp_ejs")
hiddenimports += ["yt_dlp_ejs"]

# curl-cffi is a compiled extension with its own libcurl; certifi has the CA bundle.
for package in ("curl_cffi", "certifi"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# uvicorn picks its loop/protocol implementations at run time.
hiddenimports += collect_submodules("uvicorn") + ["httptools", "h11", "anyio._backends._asyncio"]

a = Analysis(
    [str(ROOT / "packaging" / "sifon_entry.py")],
    pathex=[str(SERVICE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "playwright", "httpx", "jsonschema", "pip", "setuptools", "wheel", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="sifon",
    console=False,
    icon=str(BUILD / "sifon.ico"),
    version=str(BUILD / "version_info.txt"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="sifon", upx=False)

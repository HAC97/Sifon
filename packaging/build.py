"""Build the Windows package: dist/sifon/ (folder), a portable ZIP, and (optionally) the installer.

    python packaging/build.py                 # folder + portable ZIP
    python packaging/build.py --installer     # also compile packaging/installer.iss (needs Inno Setup)

Run it with the service's virtualenv (it needs the app's dependencies plus requirements-build.txt).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "downloader"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tools  # noqa: E402
from app import __version__  # noqa: E402

BUILD = ROOT / "build"
DIST = ROOT / "dist"
PACKAGE = DIST / "sifon"
CACHE = BUILD / "cache"


def draw_icon(target: Path) -> None:
    """The logo (five bars and an arrow, as in web/favicon.svg) on a rounded purple square."""
    from PIL import Image, ImageDraw

    size = 256
    scale = size / 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=size // 5, fill=(106, 76, 255, 255))

    def line(points, width):
        pts = [(x * scale, y * scale) for x, y in points]
        w = width * scale
        draw.line(pts, fill="white", width=int(w), joint="curve")
        for x, y in (pts[0], pts[-1]):
            draw.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill="white")

    for x, (y1, y2) in zip((8, 20, 32, 44, 56), ((24, 32), (17, 39), (7, 43), (17, 39), (24, 32))):
        line([(x, y1), (x, y2)], 7)
    line([(23, 49), (32, 57), (41, 49)], 5.5)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="ICO", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])


def version_resource(version: str) -> str:
    numbers = (version.split(".") + ["0", "0", "0"])[:4]
    tup = ", ".join(n if n.isdigit() else "0" for n in numbers)
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({tup}), prodvers=({tup}), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'HAC97'),
      StringStruct('FileDescription', 'sifón'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'sifon'),
      StringStruct('LegalCopyright', 'MIT License'),
      StringStruct('OriginalFilename', 'sifon.exe'),
      StringStruct('ProductName', 'sifón'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def prepare() -> None:
    BUILD.mkdir(exist_ok=True)
    draw_icon(BUILD / "sifon.ico")
    (BUILD / "version_info.txt").write_text(version_resource(__version__), encoding="utf-8")
    (BUILD / "bundled.json").write_text(
        json.dumps({"sifon": __version__, "yt_dlp": importlib.metadata.version("yt-dlp")}), encoding="utf-8"
    )


def run_pyinstaller() -> None:
    shutil.rmtree(PACKAGE, ignore_errors=True)
    done = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(DIST),
         "--workpath", str(BUILD / "pyi"), str(ROOT / "packaging" / "sifon.spec")],
        cwd=ROOT,
    )
    if done.returncode != 0 or not (PACKAGE / "sifon.exe").is_file():
        raise SystemExit("PyInstaller failed")


def assemble(fetched: list[tools.Tool]) -> None:
    licenses = PACKAGE / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    for name in ("LICENSE", "THIRD_PARTY.md"):
        shutil.copy2(ROOT / name, licenses / name)
    ytdlp, ejs = importlib.metadata.version("yt-dlp"), importlib.metadata.version("yt-dlp-ejs")
    lines = [
        f"sifón {__version__}",
        "",
        "Programas incluidos en bin/ (verificados con SHA-256 al construir el paquete):",
        *[f"- {t.name} {t.version}\n  sha256 {t.sha256}\n  {t.source}" for t in fetched],
        "",
        f"Bibliotecas de Python incluidas: yt-dlp {ytdlp}, yt-dlp-ejs {ejs} y las de requirements.txt.",
        "",
        "FFmpeg se distribuye bajo la LGPL v3 como bibliotecas compartidas (DLL) que podés reemplazar.",
        "Código fuente de FFmpeg: https://ffmpeg.org/download.html (etiqueta n9.0.x);",
        "scripts de la compilación: https://github.com/BtbN/FFmpeg-Builds",
    ]
    (licenses / "BUNDLED.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_zip() -> Path:
    target = DIST / f"sifon-{__version__}-windows-portable.zip"
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(PACKAGE.rglob("*")):
            if path.is_file():
                z.write(path, Path("sifon") / path.relative_to(PACKAGE))
    return target


def make_installer(iscc: str | None) -> Path:
    compiler = iscc or shutil.which("iscc") or shutil.which("ISCC")
    if not compiler:
        for guess in (r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe", r"C:\Program Files\Inno Setup 6\ISCC.exe"):
            if Path(guess).is_file():
                compiler = guess
    if not compiler:
        raise SystemExit("Inno Setup (ISCC.exe) not found; install it or pass --iscc")
    done = subprocess.run(
        [compiler, f"/DAppVersion={__version__}", f"/DSourceDir={PACKAGE}", f"/DOutputDir={DIST}",
         f"/DIconFile={BUILD / 'sifon.ico'}", str(ROOT / "packaging" / "installer.iss")],
        cwd=ROOT,
    )
    target = DIST / f"sifon-{__version__}-setup.exe"
    if done.returncode != 0 or not target.is_file():
        raise SystemExit("Inno Setup failed")
    return target


def write_checksums(files: list[Path]) -> Path:
    target = DIST / "SHA256SUMS.txt"
    lines = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}" for f in files]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", action="store_true", help="also build the Inno Setup installer")
    parser.add_argument("--iscc", help="path to ISCC.exe")
    parser.add_argument("--skip-tools", action="store_true", help="reuse bin/ already in dist/sifon (development only)")
    args = parser.parse_args()

    prepare()
    run_pyinstaller()
    fetched = [] if args.skip_tools else tools.fetch_all(CACHE, PACKAGE / "bin", PACKAGE / "licenses")
    assemble(fetched)
    outputs = [make_zip()]
    if args.installer:
        outputs.append(make_installer(args.iscc))
    sums = write_checksums(outputs)
    print("\nBuilt:")
    for path in (*outputs, sums):
        print(f"  {path}  ({path.stat().st_size / 1048576:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

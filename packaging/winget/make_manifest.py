"""Generate the winget manifest for a published sifón release.

    python packaging/winget/make_manifest.py 0.2.0
    python packaging/winget/make_manifest.py 0.2.0 --sha256 <hash> --release-date 2026-10-03

The installer URL and its SHA-256 come from the GitHub release itself (the SHA256SUMS.txt that
release.yml attaches), so nobody copies a hash by hand. Output (default `dist/winget`) follows the
winget-pkgs layout: manifests/h/HAC97/sifon/<version>/ with four YAML files.

Never regenerate a manifest for a version after it was submitted if the release files changed:
winget checks the hash, and release.yml refuses to replace the files of a published release.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

REPO = "HAC97/Sifon"
IDENTIFIER = "HAC97.sifon"
# The Inno Setup AppId (packaging/installer.iss) plus "_is1": how Windows lists the install, and
# how winget correlates an installed copy with this package for upgrades.
PRODUCT_CODE = "{6F1D2E8B-3B7A-4C55-9E0A-5A1F2C7D9B31}_is1"
MANIFEST_VERSION = "1.12.0"
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
SHA_RE = re.compile(r"[0-9A-Fa-f]{64}")


def installer_name(version: str) -> str:
    return f"sifon-{version}-setup.exe"


def installer_url(version: str) -> str:
    return f"https://github.com/{REPO}/releases/download/v{version}/{installer_name(version)}"


def sums_url(version: str) -> str:
    return f"https://github.com/{REPO}/releases/download/v{version}/SHA256SUMS.txt"


def sha_from_sums(text: str, filename: str) -> str:
    """Hash of `filename` in a sha256sum-style file ('<hash>  <name>')."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == filename and SHA_RE.fullmatch(parts[0]):
            return parts[0].upper()
    raise ValueError(f"{filename} is not listed in SHA256SUMS.txt")


def fetch_text(url: str) -> str:
    if not url.startswith("https://"):
        raise ValueError("only https")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "sifon-winget"}), timeout=30) as r:  # noqa: S310
        return r.read().decode("utf-8")


def schema_header(kind: str) -> str:
    """The comment winget-pkgs puts first in every manifest (editors and `winget validate` use it)."""
    return f"# yaml-language-server: $schema=https://aka.ms/winget-manifest.{kind}.{MANIFEST_VERSION}.schema.json\n\n"


def head(version: str) -> str:
    return f"PackageIdentifier: {IDENTIFIER}\nPackageVersion: {version}\n"


def version_file(version: str) -> str:
    return schema_header("version") + head(version) + f"DefaultLocale: en-US\nManifestType: version\nManifestVersion: {MANIFEST_VERSION}\n"


def installer_file(version: str, sha256: str, release_date: str | None) -> str:
    date = f"ReleaseDate: {release_date}\n" if release_date else ""
    return (
        schema_header("installer")
        + head(version)
        + "InstallerLocale: es-AR\n"
        + "MinimumOSVersion: 10.0.17763.0\n"
        + "InstallerType: inno\n"
        + "Scope: user\n"
        + "InstallModes:\n- interactive\n- silent\n- silentWithProgress\n"
        + "UpgradeBehavior: install\n"
        + f"ProductCode: '{PRODUCT_CODE}'\n"
        + "AppsAndFeaturesEntries:\n"
        + f"- DisplayName: sifón\n  Publisher: HAC97\n  DisplayVersion: {version}\n  ProductCode: '{PRODUCT_CODE}'\n"
        + date
        + "Installers:\n"
        + f"- Architecture: x64\n  InstallerUrl: {installer_url(version)}\n  InstallerSha256: {sha256.upper()}\n"
        + f"ManifestType: installer\nManifestVersion: {MANIFEST_VERSION}\n"
    )


def locale_files(version: str) -> dict[str, str]:
    common = (
        "Publisher: HAC97\nPublisherUrl: https://github.com/HAC97\n"
        f"PublisherSupportUrl: https://github.com/{REPO}/issues\n"
        "Author: HAC97\nPackageName: sifón\n"
        f"PackageUrl: https://github.com/{REPO}\n"
        "License: MIT\n"
        f"LicenseUrl: https://github.com/{REPO}/blob/main/LICENSE\n"
        f"PrivacyUrl: https://github.com/{REPO}#privacidad\n"
        f"ReleaseNotesUrl: https://github.com/{REPO}/releases/tag/v{version}\n"
    )
    english = (
        schema_header("defaultLocale") + head(version) + "PackageLocale: en-US\n" + common
        + "ShortDescription: Local video and audio downloader for Windows, built on yt-dlp.\n"
        + "Description: |-\n"
        + "  Paste a link, pick video (with the quality you want) or audio only (MP3, M4A or Opus) and save the file.\n"
        + "  It runs on your computer: no accounts, no cloud. FFmpeg and Deno are included.\n"
        + "Moniker: sifon\n"
        + "Tags:\n- video-downloader\n- audio-downloader\n- yt-dlp\n- youtube\n- ffmpeg\n"
        + f"ManifestType: defaultLocale\nManifestVersion: {MANIFEST_VERSION}\n"
    )
    spanish = (
        schema_header("locale") + head(version) + "PackageLocale: es-AR\n" + common
        + "ShortDescription: Descargador local de video y audio para Windows, basado en yt-dlp.\n"
        + "Description: |-\n"
        + "  Pegás un enlace, elegís video (con la calidad que quieras) o solo audio (MP3, M4A u Opus) y guardás el archivo.\n"
        + "  Corre en tu computadora: sin cuentas ni nube. Incluye FFmpeg y Deno.\n"
        + f"ManifestType: locale\nManifestVersion: {MANIFEST_VERSION}\n"
    )
    return {f"{IDENTIFIER}.locale.en-US.yaml": english, f"{IDENTIFIER}.locale.es-AR.yaml": spanish}


def build(version: str, sha256: str, release_date: str | None = None) -> dict[str, str]:
    if not VERSION_RE.fullmatch(version):
        raise ValueError(f"version must look like 1.2.3, not {version!r}")
    if not SHA_RE.fullmatch(sha256):
        raise ValueError("sha256 must be 64 hex characters")
    if release_date is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", release_date):
        raise ValueError("release date must be YYYY-MM-DD")
    files = {
        f"{IDENTIFIER}.yaml": version_file(version),
        f"{IDENTIFIER}.installer.yaml": installer_file(version, sha256, release_date),
    }
    files.update(locale_files(version))
    return files


def target_dir(root: Path, version: str) -> Path:
    # winget-pkgs layout: manifests/<first letter, lower>/<Publisher>/<Package>/<version>
    publisher, package = IDENTIFIER.split(".")
    return root / "manifests" / publisher[0].lower() / publisher / package / version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("version", help="released version, e.g. 0.2.0")
    parser.add_argument("--sha256", help="installer hash; by default read from the release's SHA256SUMS.txt")
    parser.add_argument("--release-date", help="YYYY-MM-DD; by default the release's publication date")
    parser.add_argument("--out", type=Path, default=Path("dist/winget"))
    args = parser.parse_args(argv)

    sha = args.sha256
    if not sha:
        sha = sha_from_sums(fetch_text(sums_url(args.version)), installer_name(args.version))
    date = args.release_date
    if not date:
        try:
            meta = json.loads(fetch_text(f"https://api.github.com/repos/{REPO}/releases/tags/v{args.version}"))
            date = str(meta.get("published_at", ""))[:10] or None
        except (OSError, ValueError):
            date = None
    files = build(args.version, sha, date)
    folder = target_dir(args.out, args.version)
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (folder / name).write_text(content, encoding="utf-8", newline="\n")
    print(f"Wrote {len(files)} files to {folder}")
    print(f"Installer: {installer_url(args.version)}\nSHA-256:   {sha.upper()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

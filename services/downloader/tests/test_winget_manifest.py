import importlib.util
from pathlib import Path

import pytest
import yaml

SPEC = importlib.util.spec_from_file_location(
    "make_manifest", Path(__file__).resolve().parents[3] / "packaging" / "winget" / "make_manifest.py"
)
mm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mm)

SHA = "a" * 64
ROOT = Path(__file__).resolve().parents[3]


def parsed(files):
    return {name: yaml.safe_load(text) for name, text in files.items()}


def test_four_files_are_produced_and_all_parse_as_yaml():
    files = mm.build("0.2.0", SHA, "2026-10-03")
    assert sorted(files) == [
        "HAC97.sifon.installer.yaml", "HAC97.sifon.locale.en-US.yaml", "HAC97.sifon.locale.es-AR.yaml", "HAC97.sifon.yaml",
    ]
    assert all(isinstance(v, dict) for v in parsed(files).values())


def test_every_file_names_the_same_package_and_version():
    for name, doc in parsed(mm.build("0.2.0", SHA)).items():
        assert doc["PackageIdentifier"] == "HAC97.sifon", name
        assert doc["PackageVersion"] == "0.2.0", name
        assert doc["ManifestVersion"] == "1.12.0", name


def test_manifest_types_are_the_four_expected_ones():
    types = sorted(d["ManifestType"] for d in parsed(mm.build("0.2.0", SHA)).values())
    assert types == ["defaultLocale", "installer", "locale", "version"]


def test_the_installer_entry_points_at_the_release_asset_with_the_hash_uppercased():
    doc = parsed(mm.build("0.2.0", "ab" * 32))["HAC97.sifon.installer.yaml"]
    entry = doc["Installers"][0]
    assert entry["InstallerUrl"] == "https://github.com/HAC97/Sifon/releases/download/v0.2.0/sifon-0.2.0-setup.exe"
    assert entry["InstallerSha256"] == ("AB" * 32)
    assert entry["Architecture"] == "x64"
    assert doc["InstallerType"] == "inno" and doc["Scope"] == "user"
    assert "silent" in doc["InstallModes"]


def test_the_product_code_is_the_inno_app_id_of_the_installer_script():
    """Upgrades are correlated through it: it must be the AppId in installer.iss."""
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8-sig")
    import re

    guid = re.search(r"^AppId=\{\{([0-9A-Fa-f-]{36})\}", iss, re.M).group(1)  # '{{' is Inno's escape for '{'
    assert mm.PRODUCT_CODE == "{" + guid + "}_is1"
    doc = parsed(mm.build("0.2.0", SHA))["HAC97.sifon.installer.yaml"]
    assert doc["ProductCode"] == mm.PRODUCT_CODE
    assert doc["AppsAndFeaturesEntries"][0]["DisplayName"] == "sifón"
    assert doc["AppsAndFeaturesEntries"][0]["Publisher"] == "HAC97"


def test_the_publisher_and_name_match_what_the_installer_registers():
    """winget correlates by what Add/Remove Programs shows: Publisher and PackageName must match."""
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8-sig")
    assert "AppName=sifón" in iss and "AppPublisher=HAC97" in iss
    locale = parsed(mm.build("0.2.0", SHA))["HAC97.sifon.locale.en-US.yaml"]
    assert (locale["PackageName"], locale["Publisher"]) == ("sifón", "HAC97")


def test_the_default_locale_has_the_required_descriptive_fields():
    doc = parsed(mm.build("0.2.0", SHA))["HAC97.sifon.locale.en-US.yaml"]
    for field in ("Publisher", "PackageName", "License", "ShortDescription", "PackageUrl", "LicenseUrl", "Tags"):
        assert doc[field], field
    assert doc["License"] == "MIT" and doc["Moniker"] == "sifon"


def test_urls_use_the_renamed_repository_not_the_old_one():
    text = "".join(mm.build("0.2.0", SHA).values())
    assert "HAC97/Sifon" in text and "Tifon" not in text


@pytest.mark.parametrize("version", ["0.2", "v0.2.0", "0.2.0-rc1", "", "0.2.0 ", "../0.2.0"])
def test_a_bad_version_is_refused(version):
    with pytest.raises(ValueError):
        mm.build(version, SHA)


@pytest.mark.parametrize("sha", ["", "abc", "g" * 64, "a" * 63, "a" * 65])
def test_a_bad_hash_is_refused(sha):
    with pytest.raises(ValueError):
        mm.build("0.2.0", sha)


def test_a_bad_release_date_is_refused():
    with pytest.raises(ValueError):
        mm.build("0.2.0", SHA, "03/10/2026")


def test_the_hash_is_read_from_sha256sums_by_exact_file_name():
    sums = f"{'1' * 64}  sifon-0.2.0-windows-portable.zip\n{'2' * 64}  sifon-0.2.0-setup.exe\n"
    assert mm.sha_from_sums(sums, "sifon-0.2.0-setup.exe") == "2" * 64
    with pytest.raises(ValueError):
        mm.sha_from_sums(sums, "sifon-9.9.9-setup.exe")
    with pytest.raises(ValueError):
        mm.sha_from_sums(f"nothex  sifon-0.2.0-setup.exe\n", "sifon-0.2.0-setup.exe")


def test_the_output_follows_the_winget_pkgs_layout(tmp_path):
    folder = mm.target_dir(tmp_path, "0.2.0")
    assert folder == tmp_path / "manifests" / "h" / "HAC97" / "sifon" / "0.2.0"


def test_main_writes_the_files_with_an_explicit_hash_and_no_network(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, "fetch_text", lambda url: (_ for _ in ()).throw(OSError("no network")))
    assert mm.main(["0.2.0", "--sha256", SHA, "--release-date", "2026-10-03", "--out", str(tmp_path)]) == 0
    written = sorted(p.name for p in (tmp_path / "manifests" / "h" / "HAC97" / "sifon" / "0.2.0").iterdir())
    assert len(written) == 4 and "HAC97.sifon.installer.yaml" in written


def test_main_reads_hash_and_date_from_the_release(tmp_path, monkeypatch):
    def fake(url):
        if url.endswith("SHA256SUMS.txt"):
            return f"{'c' * 64}  sifon-0.2.0-setup.exe\n"
        return '{"published_at": "2026-10-04T12:00:00Z"}'

    monkeypatch.setattr(mm, "fetch_text", fake)
    mm.main(["0.2.0", "--out", str(tmp_path)])
    doc = yaml.safe_load((tmp_path / "manifests/h/HAC97/sifon/0.2.0/HAC97.sifon.installer.yaml").read_text(encoding="utf-8"))
    assert doc["Installers"][0]["InstallerSha256"] == "C" * 64
    assert str(doc["ReleaseDate"]) == "2026-10-04"

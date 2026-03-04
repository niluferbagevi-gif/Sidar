from pathlib import Path


def test_pypi_compare_reads_latest_from_json_not_regex_parsing():
    src = Path("managers/package_info.py").read_text(encoding="utf-8")
    assert "async def _fetch_pypi_json" in src
    assert "latest = data.get(\"info\", {}).get(\"version\", \"?\")" in src
    assert "re.search(r\"Güncel sürüm" not in src


def test_prerelease_detection_uses_packaging_version_and_semver_fallback():
    src = Path("managers/package_info.py").read_text(encoding="utf-8")
    assert "return Version(version).is_prerelease" in src
    assert "except InvalidVersion:" in src
    assert "re.search(r\"-([0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)$\", version)" in src

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


def test_package_info_has_timeout_headers_and_cache_layer():
    src = Path("managers/package_info.py").read_text(encoding="utf-8")
    assert "self.timeout = httpx.Timeout(float(self.TIMEOUT), connect=5.0)" in src
    assert "User-Agent" in src
    assert "self._cache: Dict[str, Tuple[Dict, datetime]] = {}" in src
    assert "self.cache_ttl = timedelta(seconds=max(60, int(cache_ttl_seconds)))" in src
    assert "def _cache_get" in src
    assert "def _cache_set" in src
    assert "async def _get_json" in src

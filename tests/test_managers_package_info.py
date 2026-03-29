"""
managers/package_info.py için birim testleri.
PackageInfoManager: constructor, _is_prerelease, _version_sort_key,
_cache_get/_cache_set, cache TTL.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch


def _get_pi():
    if "managers.package_info" in sys.modules:
        del sys.modules["managers.package_info"]
    import managers.package_info as pi
    return pi


# ══════════════════════════════════════════════════════════════
# Constructor
# ══════════════════════════════════════════════════════════════

class TestPackageInfoManagerInit:
    def test_default_timeout(self):
        pi = _get_pi()
        mgr = pi.PackageInfoManager()
        assert mgr.TIMEOUT == 12.0

    def test_default_cache_ttl(self):
        pi = _get_pi()
        mgr = pi.PackageInfoManager()
        assert mgr.CACHE_TTL_SECONDS == 1800

    def test_config_sets_timeout(self):
        pi = _get_pi()

        class _Cfg:
            PACKAGE_INFO_TIMEOUT = 5
            PACKAGE_INFO_CACHE_TTL = 900
            VERSION = "1.0"

        mgr = pi.PackageInfoManager(config=_Cfg())
        assert mgr.TIMEOUT == 5.0

    def test_config_sets_cache_ttl(self):
        pi = _get_pi()

        class _Cfg:
            PACKAGE_INFO_TIMEOUT = 12
            PACKAGE_INFO_CACHE_TTL = 600
            VERSION = "1.0"

        mgr = pi.PackageInfoManager(config=_Cfg())
        assert mgr.CACHE_TTL_SECONDS == 600

    def test_empty_cache_on_init(self):
        pi = _get_pi()
        mgr = pi.PackageInfoManager()
        assert mgr._cache == {}

    def test_headers_contain_user_agent(self):
        pi = _get_pi()
        mgr = pi.PackageInfoManager()
        assert "User-Agent" in mgr.headers
        assert "SidarAI" in mgr.headers["User-Agent"]


# ══════════════════════════════════════════════════════════════
# _is_prerelease
# ══════════════════════════════════════════════════════════════

class TestIsPrerelease:
    def _mgr(self):
        pi = _get_pi()
        return pi.PackageInfoManager()

    def test_alpha_is_prerelease(self):
        mgr = self._mgr()
        assert mgr._is_prerelease("1.0.0a1") is True

    def test_beta_is_prerelease(self):
        mgr = self._mgr()
        assert mgr._is_prerelease("2.0.0b3") is True

    def test_rc_is_prerelease(self):
        mgr = self._mgr()
        assert mgr._is_prerelease("3.0.0rc1") is True

    def test_dev_is_prerelease(self):
        mgr = self._mgr()
        assert mgr._is_prerelease("1.0.0.dev0") is True

    def test_stable_not_prerelease(self):
        mgr = self._mgr()
        assert mgr._is_prerelease("1.2.3") is False

    def test_stable_post_not_prerelease(self):
        mgr = self._mgr()
        assert mgr._is_prerelease("1.2.3.post1") is False


# ══════════════════════════════════════════════════════════════
# _version_sort_key
# ══════════════════════════════════════════════════════════════

class TestVersionSortKey:
    def _mgr(self):
        pi = _get_pi()
        return pi.PackageInfoManager()

    def test_valid_version_returns_comparable(self):
        mgr = self._mgr()
        key = mgr._version_sort_key("1.2.3")
        assert key is not None

    def test_invalid_version_returns_fallback(self):
        mgr = self._mgr()
        # Should not raise
        key = mgr._version_sort_key("not-a-version")
        assert key is not None

    def test_ordering(self):
        mgr = self._mgr()
        versions = ["1.0.0", "2.0.0", "1.5.0"]
        sorted_v = sorted(versions, key=mgr._version_sort_key, reverse=True)
        assert sorted_v[0] == "2.0.0"


# ══════════════════════════════════════════════════════════════
# _cache_get / _cache_set
# ══════════════════════════════════════════════════════════════

class TestCacheGetSet:
    def _mgr(self):
        pi = _get_pi()
        return pi.PackageInfoManager()

    def test_miss_on_empty_cache(self):
        mgr = self._mgr()
        hit, data = mgr._cache_get("missing_key")
        assert hit is False
        assert data == {}

    def test_set_then_get(self):
        mgr = self._mgr()
        mgr._cache_set("pypi:requests", {"info": {"version": "2.28.0"}})
        hit, data = mgr._cache_get("pypi:requests")
        assert hit is True
        assert data["info"]["version"] == "2.28.0"

    def test_expired_entry_returns_miss(self):
        mgr = self._mgr()
        # Manually insert an old entry
        mgr._cache["pypi:old"] = ({"info": {}}, datetime.now() - timedelta(seconds=9999))
        hit, data = mgr._cache_get("pypi:old")
        assert hit is False

    def test_expired_entry_removed(self):
        mgr = self._mgr()
        mgr._cache["pypi:old"] = ({"info": {}}, datetime.now() - timedelta(seconds=9999))
        mgr._cache_get("pypi:old")
        assert "pypi:old" not in mgr._cache


class TestGetJsonExceptionHandling:
    def _mgr(self):
        pi = _get_pi()
        return pi.PackageInfoManager()

    def test_get_json_timeout_exception_returns_timeout_error(self):
        pi = _get_pi()
        mgr = self._mgr()

        client_mock = AsyncMock()
        client_mock.get = AsyncMock(side_effect=pi.httpx.TimeoutException("mock timeout"))
        cm_mock = AsyncMock()
        cm_mock.__aenter__.return_value = client_mock
        cm_mock.__aexit__.return_value = False

        with patch.object(pi.httpx, "AsyncClient", return_value=cm_mock):
            ok, data, err = asyncio.run(mgr._get_json("https://example.test/pypi"))

        assert ok is False
        assert data == {}
        assert err == "timeout"

    def test_get_json_request_exception_returns_request_error(self):
        pi = _get_pi()
        mgr = self._mgr()

        client_mock = AsyncMock()
        client_mock.get = AsyncMock(side_effect=pi.httpx.RequestError("network down"))
        cm_mock = AsyncMock()
        cm_mock.__aenter__.return_value = client_mock
        cm_mock.__aexit__.return_value = False

        with patch.object(pi.httpx, "AsyncClient", return_value=cm_mock):
            ok, data, err = asyncio.run(mgr._get_json("https://example.test/npm"))

        assert ok is False
        assert data == {}
        assert err.startswith("request:")

    def test_get_json_unexpected_exception_returns_unexpected_error(self):
        pi = _get_pi()
        mgr = self._mgr()

        client_mock = AsyncMock()
        client_mock.get = AsyncMock(side_effect=Exception("mock error"))
        cm_mock = AsyncMock()
        cm_mock.__aenter__.return_value = client_mock
        cm_mock.__aexit__.return_value = False

        with patch.object(pi.httpx, "AsyncClient", return_value=cm_mock):
            ok, data, err = asyncio.run(mgr._get_json("https://example.test/unexpected"))

        assert ok is False
        assert data == {}
        assert err == "unexpected:mock error"


class TestPackageInfoHighLevelApis:
    def _mgr(self):
        pi = _get_pi()
        return pi.PackageInfoManager()

    def test_pypi_info_formats_data_and_filters_prereleases(self):
        mgr = self._mgr()
        payload = {
            "info": {
                "version": "3.0.0",
                "author": "Author Name",
                "license": "MIT",
                "requires_python": ">=3.11",
                "summary": "A package",
                "project_url": "https://example.test/project",
                "requires_dist": ["httpx>=0.24; extra == 'http'", "pydantic>=2.0"],
                "home_page": "https://example.test/home",
            },
            "releases": {
                "3.0.0": [],
                "2.5.0": [],
                "2.5.0rc1": [],
                "2.0.0-1": [],
            },
        }

        with patch.object(mgr, "_fetch_pypi_json", new=AsyncMock(return_value=(True, payload, ""))):
            ok, text = asyncio.run(mgr.pypi_info("demo"))

        assert ok is True
        assert "[PyPI: demo]" in text
        assert "Son sürümler  : 3.0.0, 2.5.0" in text
        assert "2.5.0rc1" not in text
        assert "Bağımlılıklar : httpx>=0.24, pydantic>=2.0" in text
        assert "Ana sayfa     : https://example.test/home" in text

    def test_pypi_info_returns_error_when_fetch_fails(self):
        mgr = self._mgr()
        with patch.object(mgr, "_fetch_pypi_json", new=AsyncMock(return_value=(False, {}, "boom"))):
            ok, text = asyncio.run(mgr.pypi_info("demo"))
        assert ok is False
        assert text == "boom"

    def test_pypi_latest_version_and_compare_paths(self):
        mgr = self._mgr()
        payload = {"info": {"version": "2.0.0"}}

        with patch.object(mgr, "_fetch_pypi_json", new=AsyncMock(return_value=(True, payload, ""))):
            ok, text = asyncio.run(mgr.pypi_latest_version("demo"))
        assert ok is True
        assert text == "demo==2.0.0"

        with patch.object(mgr, "_fetch_pypi_json", new=AsyncMock(return_value=(True, payload, ""))), patch.object(
            mgr, "pypi_info", new=AsyncMock(return_value=(True, "[PyPI: demo]"))
        ):
            ok, cmp_text = asyncio.run(mgr.pypi_compare("demo", "1.0.0"))
        assert ok is True
        assert "⚠ Güncelleme mevcut" in cmp_text

        with patch.object(mgr, "_fetch_pypi_json", new=AsyncMock(return_value=(True, payload, ""))), patch.object(
            mgr, "pypi_info", new=AsyncMock(return_value=(True, "[PyPI: demo]"))
        ):
            ok, cmp_text = asyncio.run(mgr.pypi_compare("demo", "2.0.0"))
        assert ok is True
        assert "✓ Güncel (2.0.0)" in cmp_text

    def test_pypi_compare_invalid_version_falls_back_to_string_compare(self):
        mgr = self._mgr()
        payload = {"info": {"version": "latest"}}
        with patch.object(mgr, "_fetch_pypi_json", new=AsyncMock(return_value=(True, payload, ""))), patch.object(
            mgr, "pypi_info", new=AsyncMock(return_value=(True, "[PyPI: demo]"))
        ):
            ok, cmp_text = asyncio.run(mgr.pypi_compare("demo", "legacy"))
        assert ok is True
        assert "legacy → latest" in cmp_text

    def test_npm_info_success_and_errors(self):
        mgr = self._mgr()
        payload = {
            "version": "1.2.3",
            "author": {"name": "npm-dev"},
            "license": "Apache-2.0",
            "description": "desc",
            "main": "index.js",
            "dependencies": {"a": "^1.0.0"},
            "peerDependencies": {"react": "^18"},
            "engines": {"node": ">=18"},
        }
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(True, payload, ""))):
            ok, text = asyncio.run(mgr.npm_info("demo"))
        assert ok is True
        assert "[npm: demo]" in text
        assert "a@^1.0.0" in text
        assert "Peer deps" in text

        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(False, {}, "not_found"))):
            ok, text = asyncio.run(mgr.npm_info("demo"))
        assert ok is False
        assert "bulunamadı" in text

        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(False, {}, "timeout"))):
            ok, text = asyncio.run(mgr.npm_info("demo"))
        assert ok is False
        assert "zaman aşımı" in text

    def test_github_release_methods(self):
        mgr = self._mgr()

        releases = [
            {
                "tag_name": "v2.0.0",
                "name": "2.0.0",
                "published_at": "2026-01-01T00:00:00Z",
                "prerelease": True,
                "body": "notes",
            }
        ]
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(True, releases, ""))):
            ok, text = asyncio.run(mgr.github_releases("org/repo", limit=1))
        assert ok is True
        assert "pre-release" in text
        assert "notes" in text

        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(True, [], ""))):
            ok, text = asyncio.run(mgr.github_releases("org/repo"))
        assert ok is True
        assert "Henüz release yok" in text

        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(False, {}, "not_found"))):
            ok, text = asyncio.run(mgr.github_latest_release("org/repo"))
        assert ok is False
        assert "release bulunamadı" in text

        latest = {"tag_name": "v3.0.0", "published_at": "2026-02-01T00:00:00Z"}
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(True, latest, ""))):
            ok, text = asyncio.run(mgr.github_latest_release("org/repo"))
        assert ok is True
        assert "v3.0.0 [2026-02-01]" in text

    def test_status_and_repr(self):
        mgr = self._mgr()
        assert "Aktif" in mgr.status()
        assert "PackageInfoManager" in repr(mgr)

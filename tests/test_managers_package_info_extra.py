"""
Additional tests for managers/package_info.py to improve coverage.

Targets missing lines:
  48-54, 81-83, 92-98, 113-123, 143, 146, 166->170, 171->174,
  180, 191, 198, 226-228, 247->251, 252->256, 257->260, 273-277,
  292->294, 305-307, 325, 333-338, 349
"""
from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


def _get_pi():
    if "managers.package_info" in sys.modules:
        del sys.modules["managers.package_info"]
    import managers.package_info as pi
    return pi


# ══════════════════════════════════════════════════════════════
# Constructor httpx.Timeout fallback paths — lines 48-54
# ══════════════════════════════════════════════════════════════

class TestConstructorTimeoutFallbacks:
    def test_timeout_type_error_first_fallback(self):
        """Lines 50-51: first TypeError → tries httpx.Timeout(timeout_seconds)."""
        pi = _get_pi()

        call_count = {"n": 0}
        original_timeout = pi.httpx.Timeout

        def patched_timeout(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise TypeError("unexpected keyword")
            if call_count["n"] == 2:
                return MagicMock()
            return MagicMock()

        with patch.object(pi.httpx, "Timeout", side_effect=patched_timeout):
            mgr = pi.PackageInfoManager()
        assert mgr.timeout is not None

    def test_timeout_both_type_errors_bare_fallback(self):
        """Lines 52-54: both TypeError paths → tries httpx.Timeout() bare call."""
        pi = _get_pi()

        call_count = {"n": 0}
        sentinel = MagicMock()

        def patched_timeout(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                raise TypeError("signature mismatch")
            return sentinel

        with patch.object(pi.httpx, "Timeout", side_effect=patched_timeout):
            mgr = pi.PackageInfoManager()
        assert mgr.timeout is sentinel

    def test_config_version_used_in_headers(self):
        """Line 56: config.VERSION → used in User-Agent header."""
        pi = _get_pi()

        class _Cfg:
            PACKAGE_INFO_TIMEOUT = 12
            PACKAGE_INFO_CACHE_TTL = 1800
            VERSION = "9.9.9"

        mgr = pi.PackageInfoManager(config=_Cfg())
        assert "SidarAI/9.9.9" in mgr.headers["User-Agent"]


# ══════════════════════════════════════════════════════════════
# _get_json — cache hit path, 404, raise_for_status, cache set
# Lines 81-83, 92-98
# ══════════════════════════════════════════════════════════════

class TestGetJsonCacheAndHttp:
    def _mgr(self):
        pi = _get_pi()
        return pi.PackageInfoManager()

    def test_get_json_returns_cached_value(self):
        """Lines 81-83: cache hit → return early without HTTP call."""
        mgr = self._mgr()
        mgr._cache_set("test:key", {"cached": True})

        with patch.object(mgr, "_cache_get", wraps=mgr._cache_get) as spy:
            ok, data, err = asyncio.run(mgr._get_json("https://example.test/ignored", cache_key="test:key"))
        assert ok is True
        assert data["cached"] is True
        assert err == ""

    def test_get_json_404_returns_not_found(self):
        """Lines 92-93: HTTP 404 → ('not_found' error string)."""
        pi = _get_pi()
        mgr = self._mgr()

        fake_resp = MagicMock()
        fake_resp.status_code = 404
        fake_resp.raise_for_status = MagicMock()

        client_mock = AsyncMock()
        client_mock.get = AsyncMock(return_value=fake_resp)
        cm_mock = AsyncMock()
        cm_mock.__aenter__.return_value = client_mock
        cm_mock.__aexit__.return_value = False

        with patch.object(pi.httpx, "AsyncClient", return_value=cm_mock):
            ok, data, err = asyncio.run(mgr._get_json("https://example.test/404"))
        assert ok is False
        assert err == "not_found"

    def test_get_json_success_sets_cache(self):
        """Lines 95-98: successful response → JSON parsed and cached."""
        pi = _get_pi()
        mgr = self._mgr()

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json = MagicMock(return_value={"info": {"version": "1.0.0"}})

        client_mock = AsyncMock()
        client_mock.get = AsyncMock(return_value=fake_resp)
        cm_mock = AsyncMock()
        cm_mock.__aenter__.return_value = client_mock
        cm_mock.__aexit__.return_value = False

        with patch.object(pi.httpx, "AsyncClient", return_value=cm_mock):
            ok, data, err = asyncio.run(mgr._get_json("https://example.test/ok", cache_key="my:key"))

        assert ok is True
        assert data["info"]["version"] == "1.0.0"
        # Verify cache was populated
        hit, cached = mgr._cache_get("my:key")
        assert hit is True

    def test_get_json_no_cache_key_does_not_cache(self):
        """Lines 96-97: no cache_key → _cache_set not called."""
        pi = _get_pi()
        mgr = self._mgr()

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json = MagicMock(return_value={"result": "data"})

        client_mock = AsyncMock()
        client_mock.get = AsyncMock(return_value=fake_resp)
        cm_mock = AsyncMock()
        cm_mock.__aenter__.return_value = client_mock
        cm_mock.__aexit__.return_value = False

        with patch.object(pi.httpx, "AsyncClient", return_value=cm_mock):
            ok, data, err = asyncio.run(mgr._get_json("https://example.test/no-cache"))

        assert ok is True
        assert mgr._cache == {}


# ══════════════════════════════════════════════════════════════
# _fetch_pypi_json error branches — lines 113-123
# ══════════════════════════════════════════════════════════════

class TestFetchPypiJson:
    def _mgr(self):
        pi = _get_pi()
        return pi.PackageInfoManager()

    def test_fetch_not_found(self):
        """Lines 117-118: not_found error from _get_json."""
        mgr = self._mgr()
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(False, {}, "not_found"))):
            ok, data, err = asyncio.run(mgr._fetch_pypi_json("nonexistent_pkg"))
        assert ok is False
        assert "bulunamadı" in err
        assert "nonexistent_pkg" in err

    def test_fetch_timeout(self):
        """Lines 119-120: timeout error."""
        mgr = self._mgr()
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(False, {}, "timeout"))):
            ok, data, err = asyncio.run(mgr._fetch_pypi_json("mypkg"))
        assert ok is False
        assert "zaman aşımı" in err

    def test_fetch_request_error(self):
        """Lines 121-122: request: error."""
        mgr = self._mgr()
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(False, {}, "request:connection refused"))):
            ok, data, err = asyncio.run(mgr._fetch_pypi_json("mypkg"))
        assert ok is False
        assert "bağlantı hatası" in err

    def test_fetch_generic_error(self):
        """Line 123: other error → generic [HATA] prefix."""
        mgr = self._mgr()
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(False, {}, "unexpected:something weird"))):
            ok, data, err = asyncio.run(mgr._fetch_pypi_json("mypkg"))
        assert ok is False
        assert "[HATA]" in err

    def test_fetch_success(self):
        """Lines 115-116: ok=True → returns data."""
        mgr = self._mgr()
        payload = {"info": {"version": "3.0.0"}}
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(True, payload, ""))):
            ok, data, err = asyncio.run(mgr._fetch_pypi_json("mypkg"))
        assert ok is True
        assert data == payload
        assert err == ""


# ══════════════════════════════════════════════════════════════
# pypi_info — missing lines 143, 146, 166->170, 171->174, 180
# ══════════════════════════════════════════════════════════════

class TestPypiInfo:
    def _mgr(self):
        pi = _get_pi()
        return pi.PackageInfoManager()

    def test_pypi_info_skip_none_version_key(self):
        """Line 143: None version keys are skipped."""
        mgr = self._mgr()
        payload = {
            "info": {
                "version": "1.0.0",
                "author": "Author",
                "license": "MIT",
                "requires_python": ">=3.8",
                "summary": "test",
                "project_url": None,
                "requires_dist": None,
                "home_page": None,
            },
            "releases": {None: [], "1.0.0": [], "": []},
        }
        with patch.object(mgr, "_fetch_pypi_json", new=AsyncMock(return_value=(True, payload, ""))):
            ok, text = asyncio.run(mgr.pypi_info("mypkg"))
        assert ok is True
        # Only "1.0.0" should be in recent versions, not None or empty
        assert "1.0.0" in text

    def test_pypi_info_skip_empty_version_key(self):
        """Line 146: empty string version keys skipped after strip."""
        mgr = self._mgr()
        payload = {
            "info": {
                "version": "2.0.0",
                "author": None,
                "author_email": "test@example.com",
                "license": None,
                "requires_python": None,
                "summary": None,
                "project_url": None,
                "requires_dist": None,
                "home_page": None,
            },
            "releases": {"  ": [], "2.0.0": []},
        }
        with patch.object(mgr, "_fetch_pypi_json", new=AsyncMock(return_value=(True, payload, ""))):
            ok, text = asyncio.run(mgr.pypi_info("mypkg"))
        assert ok is True
        assert "2.0.0" in text

    def test_pypi_info_requires_dist_cleaned(self):
        """Lines 166-168: requires_dist split on semicolon."""
        mgr = self._mgr()
        payload = {
            "info": {
                "version": "1.0.0",
                "author": "Dev",
                "license": "MIT",
                "requires_python": ">=3.8",
                "summary": "pkg",
                "project_url": "https://pypi.org/project/mypkg",
                "requires_dist": ["httpx>=0.24; extra == 'http'", "pydantic>=2.0"],
                "home_page": None,
            },
            "releases": {"1.0.0": []},
        }
        with patch.object(mgr, "_fetch_pypi_json", new=AsyncMock(return_value=(True, payload, ""))):
            ok, text = asyncio.run(mgr.pypi_info("mypkg"))
        assert ok is True
        assert "httpx>=0.24" in text
        assert "extra ==" not in text

    def test_pypi_info_home_page_appended(self):
        """Lines 170-172: home_page or project_url → appended."""
        mgr = self._mgr()
        payload = {
            "info": {
                "version": "1.0.0",
                "author": "Dev",
                "license": "MIT",
                "requires_python": ">=3.8",
                "summary": "pkg",
                "project_url": "https://pypi.org/project/mypkg",
                "requires_dist": None,
                "home_page": "https://home.example.com",
            },
            "releases": {"1.0.0": []},
        }
        with patch.object(mgr, "_fetch_pypi_json", new=AsyncMock(return_value=(True, payload, ""))):
            ok, text = asyncio.run(mgr.pypi_info("mypkg"))
        assert ok is True
        assert "https://home.example.com" in text

    def test_pypi_info_no_home_page_no_extra_line(self):
        """Lines 171->174: home_page is None/empty → no extra line."""
        mgr = self._mgr()
        payload = {
            "info": {
                "version": "1.0.0",
                "author": "Dev",
                "license": "MIT",
                "requires_python": ">=3.8",
                "summary": "pkg",
                "project_url": None,
                "requires_dist": None,
                "home_page": None,
            },
            "releases": {"1.0.0": []},
        }
        with patch.object(mgr, "_fetch_pypi_json", new=AsyncMock(return_value=(True, payload, ""))):
            ok, text = asyncio.run(mgr.pypi_info("mypkg"))
        assert ok is True
        assert "Ana sayfa" not in text

    def test_pypi_info_fallback_project_url(self):
        """Line 161: no project_url → fallback to /project/ URL."""
        mgr = self._mgr()
        payload = {
            "info": {
                "version": "1.0.0",
                "author": "Dev",
                "license": "MIT",
                "requires_python": ">=3.8",
                "summary": "pkg",
                "project_url": None,
                "requires_dist": None,
                "home_page": None,
            },
            "releases": {"1.0.0": []},
        }
        with patch.object(mgr, "_fetch_pypi_json", new=AsyncMock(return_value=(True, payload, ""))):
            ok, text = asyncio.run(mgr.pypi_info("mypkg"))
        assert ok is True
        assert "https://pypi.org/project/mypkg" in text


# ══════════════════════════════════════════════════════════════
# pypi_latest_version — line 180
# ══════════════════════════════════════════════════════════════

class TestPypiLatestVersion:
    def _mgr(self):
        pi = _get_pi()
        return pi.PackageInfoManager()

    def test_pypi_latest_version_none_becomes_question_mark(self):
        """Line 180: version=None → '?'."""
        mgr = self._mgr()
        payload = {"info": {"version": None}}
        with patch.object(mgr, "_fetch_pypi_json", new=AsyncMock(return_value=(True, payload, ""))):
            ok, text = asyncio.run(mgr.pypi_latest_version("mypkg"))
        assert ok is True
        assert text == "mypkg==?"

    def test_pypi_latest_version_error_forwarded(self):
        """Line 179: fetch fails → error forwarded."""
        mgr = self._mgr()
        with patch.object(mgr, "_fetch_pypi_json", new=AsyncMock(return_value=(False, {}, "not_found_msg"))):
            ok, text = asyncio.run(mgr.pypi_latest_version("mypkg"))
        assert ok is False
        assert text == "not_found_msg"


# ══════════════════════════════════════════════════════════════
# pypi_compare — line 191, 198
# ══════════════════════════════════════════════════════════════

class TestPypiCompare:
    def _mgr(self):
        pi = _get_pi()
        return pi.PackageInfoManager()

    def test_pypi_compare_fetch_fails(self):
        """Line 190: fetch fails → error forwarded."""
        mgr = self._mgr()
        with patch.object(mgr, "_fetch_pypi_json", new=AsyncMock(return_value=(False, {}, "timeout_err"))):
            ok, text = asyncio.run(mgr.pypi_compare("mypkg", "1.0.0"))
        assert ok is False
        assert text == "timeout_err"

    def test_pypi_compare_latest_none_becomes_question_mark(self):
        """Line 191: latest version None → '?'."""
        mgr = self._mgr()
        payload = {"info": {"version": None}}
        with patch.object(mgr, "_fetch_pypi_json", new=AsyncMock(return_value=(True, payload, ""))):
            with patch.object(mgr, "pypi_info", new=AsyncMock(return_value=(True, "[PyPI: mypkg]"))):
                ok, text = asyncio.run(mgr.pypi_compare("mypkg", "1.0.0"))
        assert ok is True
        # "?" as latest, "1.0.0" as current → update available (strings differ)
        assert "1.0.0" in text

    def test_pypi_compare_pypi_info_fails(self):
        """Line 197-198: pypi_info fails → error forwarded."""
        mgr = self._mgr()
        payload = {"info": {"version": "2.0.0"}}
        with patch.object(mgr, "_fetch_pypi_json", new=AsyncMock(return_value=(True, payload, ""))):
            with patch.object(mgr, "pypi_info", new=AsyncMock(return_value=(False, "pypi_info_error"))):
                ok, text = asyncio.run(mgr.pypi_compare("mypkg", "1.0.0"))
        assert ok is False
        assert text == "pypi_info_error"

    def test_pypi_compare_current_version_none_becomes_question_mark(self):
        """Line 195: current_version=None → '?'."""
        mgr = self._mgr()
        payload = {"info": {"version": "2.0.0"}}
        with patch.object(mgr, "_fetch_pypi_json", new=AsyncMock(return_value=(True, payload, ""))):
            with patch.object(mgr, "pypi_info", new=AsyncMock(return_value=(True, "[PyPI: mypkg]"))):
                ok, text = asyncio.run(mgr.pypi_compare("mypkg", None))
        assert ok is True


# ══════════════════════════════════════════════════════════════
# npm_info — lines 226-228 (request error), 247->251, 252->256, 257->260
# ══════════════════════════════════════════════════════════════

class TestNpmInfo:
    def _mgr(self):
        pi = _get_pi()
        return pi.PackageInfoManager()

    def test_npm_info_request_error(self):
        """Lines 226-227: request: error."""
        mgr = self._mgr()
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(False, {}, "request:host not found"))):
            ok, text = asyncio.run(mgr.npm_info("mypkg"))
        assert ok is False
        assert "bağlantı hatası" in text

    def test_npm_info_generic_error(self):
        """Line 228: other error → generic prefix."""
        mgr = self._mgr()
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(False, {}, "unexpected:server 503"))):
            ok, text = asyncio.run(mgr.npm_info("mypkg"))
        assert ok is False
        assert "[HATA] npm:" in text

    def test_npm_info_author_string(self):
        """Lines 231-235: author as plain string (not dict)."""
        mgr = self._mgr()
        payload = {
            "version": "1.0.0",
            "author": "Jane Doe",
            "license": "MIT",
            "description": "desc",
            "main": "index.js",
        }
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(True, payload, ""))):
            ok, text = asyncio.run(mgr.npm_info("mypkg"))
        assert ok is True
        assert "Jane Doe" in text

    def test_npm_info_peer_dependencies(self):
        """Lines 251-254: peerDependencies → 'Peer deps' line."""
        mgr = self._mgr()
        payload = {
            "version": "2.0.0",
            "author": {"name": "Dev"},
            "license": "MIT",
            "description": "",
            "main": "index.js",
            "peerDependencies": {"react": "^18", "react-dom": "^18"},
        }
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(True, payload, ""))):
            ok, text = asyncio.run(mgr.npm_info("mypkg"))
        assert ok is True
        assert "Peer deps" in text
        assert "react@^18" in text

    def test_npm_info_engines(self):
        """Lines 256-258: engines → 'Engine gerek' line."""
        mgr = self._mgr()
        payload = {
            "version": "3.0.0",
            "author": {"name": "Dev"},
            "license": "ISC",
            "description": "",
            "main": "index.js",
            "engines": {"node": ">=18"},
        }
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(True, payload, ""))):
            ok, text = asyncio.run(mgr.npm_info("mypkg"))
        assert ok is True
        assert "Engine gerek" in text
        assert "node" in text

    def test_npm_info_dependencies(self):
        """Lines 246-249: dependencies → 'Bağımlılıklar' line."""
        mgr = self._mgr()
        payload = {
            "version": "1.0.0",
            "author": {"name": "Dev"},
            "license": "MIT",
            "description": "",
            "main": "index.js",
            "dependencies": {"lodash": "^4.0.0", "axios": "^1.0.0"},
        }
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(True, payload, ""))):
            ok, text = asyncio.run(mgr.npm_info("mypkg"))
        assert ok is True
        assert "Bağımlılıklar" in text
        assert "lodash@^4.0.0" in text

    def test_npm_info_no_optional_fields(self):
        """No deps, no peerDeps, no engines → still succeeds."""
        mgr = self._mgr()
        payload = {
            "version": "1.0.0",
            "author": {},
            "license": "MIT",
            "description": "",
            "main": None,
        }
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(True, payload, ""))):
            ok, text = asyncio.run(mgr.npm_info("mypkg"))
        assert ok is True
        assert "[npm: mypkg]" in text


# ══════════════════════════════════════════════════════════════
# github_releases — lines 273-277
# ══════════════════════════════════════════════════════════════

class TestGithubReleases:
    def _mgr(self):
        pi = _get_pi()
        return pi.PackageInfoManager()

    def test_github_releases_timeout(self):
        """Lines 275-276: timeout error."""
        mgr = self._mgr()
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(False, {}, "timeout"))):
            ok, text = asyncio.run(mgr.github_releases("org/repo"))
        assert ok is False
        assert "zaman aşımı" in text

    def test_github_releases_generic_error(self):
        """Line 277: generic error."""
        mgr = self._mgr()
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(False, {}, "unexpected:err"))):
            ok, text = asyncio.run(mgr.github_releases("org/repo"))
        assert ok is False
        assert "GitHub Releases" in text

    def test_github_releases_non_list_data(self):
        """Line 279: data is not a list → empty releases."""
        mgr = self._mgr()
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(True, {"unexpected": "dict"}, ""))):
            ok, text = asyncio.run(mgr.github_releases("org/repo"))
        assert ok is True
        assert "Henüz release yok" in text

    def test_github_releases_body_truncated(self):
        """Lines 289-293: body is stripped and truncated."""
        mgr = self._mgr()
        releases = [
            {
                "tag_name": "v1.0.0",
                "name": "Release 1",
                "published_at": "2026-01-01T00:00:00Z",
                "prerelease": False,
                "body": "Line1\nLine2\nLine3",
            }
        ]
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(True, releases, ""))):
            ok, text = asyncio.run(mgr.github_releases("org/repo"))
        assert ok is True
        assert "Line1" in text
        # Newlines replaced with spaces
        assert "\n    Line1\nLine2" not in text


# ══════════════════════════════════════════════════════════════
# github_latest_release — lines 292->294, 305-307
# ══════════════════════════════════════════════════════════════

class TestGithubLatestRelease:
    def _mgr(self):
        pi = _get_pi()
        return pi.PackageInfoManager()

    def test_github_latest_release_timeout(self):
        """Lines 305-306: timeout error."""
        mgr = self._mgr()
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(False, {}, "timeout"))):
            ok, text = asyncio.run(mgr.github_latest_release("org/repo"))
        assert ok is False
        assert "zaman aşımı" in text

    def test_github_latest_release_generic_error(self):
        """Line 307: generic error."""
        mgr = self._mgr()
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(False, {}, "request:network down"))):
            ok, text = asyncio.run(mgr.github_latest_release("org/repo"))
        assert ok is False
        assert "GitHub" in text

    def test_github_latest_release_published_at_none(self):
        """Lines 308-310: published_at=None → '?'."""
        mgr = self._mgr()
        data = {"tag_name": "v1.0.0", "published_at": None}
        with patch.object(mgr, "_get_json", new=AsyncMock(return_value=(True, data, ""))):
            ok, text = asyncio.run(mgr.github_latest_release("org/repo"))
        assert ok is True
        assert "v1.0.0" in text
        assert "[?]" in text


# ══════════════════════════════════════════════════════════════
# _is_prerelease — line 325, 333-338
# ══════════════════════════════════════════════════════════════

class TestIsPrerelease:
    def test_none_version_returns_false(self):
        """Line 323: None → '' → returns False."""
        pi = _get_pi()
        assert pi.PackageInfoManager._is_prerelease(None) is False

    def test_empty_string_returns_false(self):
        """Line 325: empty after strip → returns False."""
        pi = _get_pi()
        assert pi.PackageInfoManager._is_prerelease("") is False
        assert pi.PackageInfoManager._is_prerelease("   ") is False

    def test_npm_numeric_prerelease(self):
        """Lines 328-330: npm semver numeric pre-release (1.0.0-0)."""
        pi = _get_pi()
        assert pi.PackageInfoManager._is_prerelease("1.0.0-0") is True
        assert pi.PackageInfoManager._is_prerelease("2.0.0-42") is True

    def test_invalid_version_with_prerelease_label(self):
        """Lines 333-338: InvalidVersion + regex match → True."""
        pi = _get_pi()
        # These are not valid PEP440 but match semver pre-release pattern
        assert pi.PackageInfoManager._is_prerelease("1.2.3-alpha.1") is True
        assert pi.PackageInfoManager._is_prerelease("2.0.0-rc") is True

    def test_invalid_version_unknown_format_returns_false(self):
        """Line 338: Unknown format with no match → False (stable assumption)."""
        pi = _get_pi()
        # No dash pre-release suffix, just weird string
        assert pi.PackageInfoManager._is_prerelease("not.a.version.at.all.nohyphen") is False


# ══════════════════════════════════════════════════════════════
# _version_sort_key — line 349
# ══════════════════════════════════════════════════════════════

class TestVersionSortKey:
    def test_none_returns_zero_version(self):
        """Line 347: None → '' → returns Version('0.0.0')."""
        pi = _get_pi()
        from packaging.version import Version
        key = pi.PackageInfoManager._version_sort_key(None)
        assert key == Version("0.0.0")

    def test_empty_returns_zero_version(self):
        """Line 348-349: empty string → Version('0.0.0')."""
        pi = _get_pi()
        from packaging.version import Version
        key = pi.PackageInfoManager._version_sort_key("")
        assert key == Version("0.0.0")
        key2 = pi.PackageInfoManager._version_sort_key("   ")
        assert key2 == Version("0.0.0")

    def test_invalid_version_returns_zero_version(self):
        """Lines 352-353: InvalidVersion → Version('0.0.0')."""
        pi = _get_pi()
        from packaging.version import Version
        key = pi.PackageInfoManager._version_sort_key("not-valid-pep440-xyz")
        assert key == Version("0.0.0")

    def test_valid_version_sorts_correctly(self):
        pi = _get_pi()
        from packaging.version import Version
        key = pi.PackageInfoManager._version_sort_key("2.5.0")
        assert key == Version("2.5.0")

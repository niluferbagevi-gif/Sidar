"""
Extended runtime tests for managers/package_info.py — targets uncovered branches:
  _cache_get miss (line 54), cache expiry cleanup (58-59),
  _get_json full paths (65-90): cache hit, 404, timeout, RequestError, generic exception,
  pypi_latest_version (104-108), pypi_compare equal versions (173-176),
  npm_info error paths (194, 197-199),
  github_releases not_found / empty (245, 247, 253),
  github_latest_release not_found / timeout (274-278),
  _is_prerelease InvalidVersion paths (300-305).
"""
import asyncio
import sys
import types
import importlib
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ─── Module fixture ──────────────────────────────────────────────────────────

def _load_pkg():
    """Load PackageInfoManager fresh with httpx stub."""
    class _Timeout:
        def __init__(self, *a, **kw): pass

    class _TimeoutException(Exception): pass
    class _RequestError(Exception): pass

    class _AsyncClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def get(self, url):
            return types.SimpleNamespace(
                status_code=200, json=lambda: {},
                raise_for_status=lambda: None,
            )

    sys.modules["httpx"] = types.SimpleNamespace(
        Timeout=_Timeout,
        TimeoutException=_TimeoutException,
        RequestError=_RequestError,
        AsyncClient=_AsyncClient,
    )

    spec = importlib.util.spec_from_file_location(
        "pkg_info_ext", Path("managers/package_info.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PKG = _load_pkg()
PackageInfoManager = PKG.PackageInfoManager


# ─── _cache_get — cache miss (line 54) ──────────────────────────────────────

def test_cache_get_miss_returns_false_empty():
    mgr = PackageInfoManager()
    hit, data = mgr._cache_get("nonexistent_key")
    assert hit is False
    assert data == {}


def test_cache_get_expired_pops_and_returns_false():
    """Covers lines 58-59: expired cache entry is removed."""
    mgr = PackageInfoManager()
    # Insert an entry with an old timestamp
    old_ts = datetime.now() - timedelta(seconds=7200)
    mgr._cache["expired_key"] = ({"some": "data"}, old_ts)

    hit, data = mgr._cache_get("expired_key")
    assert hit is False
    assert data == {}
    # Entry should be removed from cache
    assert "expired_key" not in mgr._cache


def test_cache_get_fresh_entry_returns_true():
    mgr = PackageInfoManager()
    mgr._cache_set("fresh_key", {"x": 42})
    hit, data = mgr._cache_get("fresh_key")
    assert hit is True
    assert data["x"] == 42


# ─── _get_json ───────────────────────────────────────────────────────────────

def test_get_json_cache_hit_returns_without_http():
    """Covers lines 65-68: cache_key hit → return cached data without HTTP."""
    mgr = PackageInfoManager()
    mgr._cache_set("pypi:requests", {"info": {"version": "2.31.0"}})

    result = asyncio.run(
        mgr._get_json("https://pypi.org/pypi/requests/json", cache_key="pypi:requests")
    )
    ok, data, err = result
    assert ok is True
    assert data["info"]["version"] == "2.31.0"
    assert err == ""


def test_get_json_404_returns_not_found(monkeypatch):
    """Covers line 78: status_code 404 returns not_found."""
    mgr = PackageInfoManager()

    fake_resp = types.SimpleNamespace(
        status_code=404,
        raise_for_status=lambda: None,
        json=lambda: {},
    )

    class _FakeClientCls:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def get(self, url): return fake_resp

    # Patch AsyncClient on the module's httpx reference
    monkeypatch.setattr(PKG.httpx, "AsyncClient", _FakeClientCls)

    ok, data, err = asyncio.run(mgr._get_json("https://example.com/notfound"))

    assert ok is False
    assert err == "not_found"


def test_get_json_timeout_exception(monkeypatch):
    """Covers line 84-85: TimeoutException → timeout error."""
    mgr = PackageInfoManager()
    TimeoutException = PKG.httpx.TimeoutException

    class _FakeClientCls:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def get(self, url):
            raise TimeoutException("timed out")

    monkeypatch.setattr(PKG.httpx, "AsyncClient", _FakeClientCls)

    ok, data, err = asyncio.run(mgr._get_json("https://example.com/slow"))
    assert ok is False
    assert err == "timeout"


def test_get_json_request_error(monkeypatch):
    """Covers lines 86-87: RequestError → request:... error."""
    mgr = PackageInfoManager()
    RequestError = PKG.httpx.RequestError

    class _FakeClientCls:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def get(self, url):
            raise RequestError("connection refused")

    monkeypatch.setattr(PKG.httpx, "AsyncClient", _FakeClientCls)

    ok, data, err = asyncio.run(mgr._get_json("https://example.com/fail"))
    assert ok is False
    assert err.startswith("request:")


def test_get_json_generic_exception(monkeypatch):
    """Covers lines 88-90: generic exception → unexpected:... error."""
    mgr = PackageInfoManager()

    class _FakeClientCls:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def get(self, url):
            raise ValueError("unexpected json error")

    monkeypatch.setattr(PKG.httpx, "AsyncClient", _FakeClientCls)

    ok, data, err = asyncio.run(mgr._get_json("https://example.com/bad"))
    assert ok is False
    assert err.startswith("unexpected:")


# ─── pypi_latest_version ────────────────────────────────────────────────────

def test_pypi_latest_version_success(monkeypatch):
    """Covers lines 104-108 + 154-160."""
    mgr = PackageInfoManager()

    async def fake_fetch_pypi(pkg):
        return True, {"info": {"version": "3.0.1"}, "releases": {}}, ""

    monkeypatch.setattr(mgr, "_fetch_pypi_json", fake_fetch_pypi)
    ok, result = asyncio.run(mgr.pypi_latest_version("mylib"))
    assert ok is True
    assert "mylib==3.0.1" in result


def test_pypi_latest_version_failure(monkeypatch):
    """Covers line 157-158: fetch fails → returns error."""
    mgr = PackageInfoManager()

    async def failing_fetch(pkg):
        return False, {}, "✗ PyPI'de 'bad_pkg' paketi bulunamadı."

    monkeypatch.setattr(mgr, "_fetch_pypi_json", failing_fetch)
    ok, result = asyncio.run(mgr.pypi_latest_version("bad_pkg"))
    assert ok is False
    assert "bulunamadı" in result


# ─── pypi_compare — equal versions ──────────────────────────────────────────

def test_pypi_compare_fetch_failure_returns_error(monkeypatch):
    """Covers line 168: _fetch_pypi_json fails → returns propagated error."""
    mgr = PackageInfoManager()

    async def failing_fetch(pkg):
        return False, {}, "timeout"

    monkeypatch.setattr(mgr, "_fetch_pypi_json", failing_fetch)
    ok, result = asyncio.run(mgr.pypi_compare("pkg", "2.0.0"))
    assert ok is False
    assert result == "timeout"


def test_pypi_compare_equal_versions_shows_up_to_date(monkeypatch):
    """Covers line 175-176: current_version == latest → 'Güncel'."""
    mgr = PackageInfoManager()

    async def fake_fetch(pkg):
        return True, {"info": {"version": "2.0.0"}, "releases": {"2.0.0": {}}}, ""

    async def fake_info(pkg):
        return True, "[PyPI: pkg]\n  Güncel sürüm  : 2.0.0"

    monkeypatch.setattr(mgr, "_fetch_pypi_json", fake_fetch)
    monkeypatch.setattr(mgr, "pypi_info", fake_info)

    ok, result = asyncio.run(mgr.pypi_compare("pkg", "2.0.0"))
    assert ok is True
    assert "Güncel" in result


def test_pypi_compare_update_available(monkeypatch):
    """Covers line 178: current != latest → 'Güncelleme mevcut'."""
    mgr = PackageInfoManager()

    async def fake_fetch(pkg):
        return True, {"info": {"version": "3.0.0"}, "releases": {}}, ""

    async def fake_info(pkg):
        return True, "[PyPI: pkg]\n  Güncel sürüm  : 3.0.0"

    monkeypatch.setattr(mgr, "_fetch_pypi_json", fake_fetch)
    monkeypatch.setattr(mgr, "pypi_info", fake_info)

    ok, result = asyncio.run(mgr.pypi_compare("pkg", "2.0.0"))
    assert ok is True
    assert "Güncelleme mevcut" in result


def test_pypi_compare_pypi_info_fails(monkeypatch):
    """Covers lines 172-173: pypi_info fails → return False."""
    mgr = PackageInfoManager()

    async def fake_fetch(pkg):
        return True, {"info": {"version": "3.0.0"}, "releases": {}}, ""

    async def bad_info(pkg):
        return False, "error fetching info"

    monkeypatch.setattr(mgr, "_fetch_pypi_json", fake_fetch)
    monkeypatch.setattr(mgr, "pypi_info", bad_info)

    ok, result = asyncio.run(mgr.pypi_compare("pkg", "2.0.0"))
    assert ok is False


# ─── npm_info error paths ────────────────────────────────────────────────────

def test_npm_info_not_found(monkeypatch):
    """Covers line 194: not_found error."""
    mgr = PackageInfoManager()

    async def nf(*a, **kw):
        return False, {}, "not_found"

    monkeypatch.setattr(mgr, "_get_json", nf)
    ok, msg = asyncio.run(mgr.npm_info("nonexistent-pkg"))
    assert ok is False
    assert "bulunamadı" in msg


def test_npm_info_timeout(monkeypatch):
    """Covers lines 195-196: timeout error."""
    mgr = PackageInfoManager()

    async def timeout_fn(*a, **kw):
        return False, {}, "timeout"

    monkeypatch.setattr(mgr, "_get_json", timeout_fn)
    ok, msg = asyncio.run(mgr.npm_info("slow-pkg"))
    assert ok is False
    assert "zaman aşımı" in msg


def test_npm_info_request_error(monkeypatch):
    """Covers lines 197-198: request: error."""
    mgr = PackageInfoManager()

    async def req_fn(*a, **kw):
        return False, {}, "request:connect failed"

    monkeypatch.setattr(mgr, "_get_json", req_fn)
    ok, msg = asyncio.run(mgr.npm_info("connect-fail-pkg"))
    assert ok is False
    assert "bağlantı hatası" in msg


def test_npm_info_generic_error(monkeypatch):
    """Covers line 199: generic error fallback."""
    mgr = PackageInfoManager()

    async def generic_fn(*a, **kw):
        return False, {}, "unexpected:weird error"

    monkeypatch.setattr(mgr, "_get_json", generic_fn)
    ok, msg = asyncio.run(mgr.npm_info("weird-pkg"))
    assert ok is False
    assert "npm" in msg


# ─── github_releases ─────────────────────────────────────────────────────────

def test_github_releases_not_found(monkeypatch):
    """Covers line 245: not_found error."""
    mgr = PackageInfoManager()

    async def nf(*a, **kw):
        return False, {}, "not_found"

    monkeypatch.setattr(mgr, "_get_json", nf)
    ok, msg = asyncio.run(mgr.github_releases("noorg/norepo"))
    assert ok is False
    assert "bulunamadı" in msg


def test_github_releases_empty_list_returns_no_releases(monkeypatch):
    """Covers lines 247, 252-253: empty list → 'Henüz release yok'."""
    mgr = PackageInfoManager()

    async def empty_fn(*a, **kw):
        return True, [], ""

    monkeypatch.setattr(mgr, "_get_json", empty_fn)
    ok, msg = asyncio.run(mgr.github_releases("org/repo"))
    assert ok is True
    assert "release yok" in msg


def test_github_releases_non_list_data_returns_no_releases(monkeypatch):
    """Covers line 250: data is not a list → releases=[] → 'Henüz release yok'."""
    mgr = PackageInfoManager()

    async def dict_fn(*a, **kw):
        return True, {"message": "not a list"}, ""

    monkeypatch.setattr(mgr, "_get_json", dict_fn)
    ok, msg = asyncio.run(mgr.github_releases("org/repo"))
    assert ok is True
    assert "release yok" in msg


def test_github_releases_timeout_error(monkeypatch):
    """Covers line 247: timeout error."""
    mgr = PackageInfoManager()

    async def timeout_fn(*a, **kw):
        return False, {}, "timeout"

    monkeypatch.setattr(mgr, "_get_json", timeout_fn)
    ok, msg = asyncio.run(mgr.github_releases("org/repo"))
    assert ok is False
    assert "zaman aşımı" in msg


# ─── github_latest_release ───────────────────────────────────────────────────

def test_github_latest_release_not_found(monkeypatch):
    """Covers lines 274-275: not_found → 'release bulunamadı'."""
    mgr = PackageInfoManager()

    async def nf(*a, **kw):
        return False, {}, "not_found"

    monkeypatch.setattr(mgr, "_get_json", nf)
    ok, msg = asyncio.run(mgr.github_latest_release("org/norepo"))
    assert ok is False
    assert "bulunamadı" in msg


def test_github_latest_release_timeout(monkeypatch):
    """Covers lines 276-277: timeout → error message."""
    mgr = PackageInfoManager()

    async def timeout_fn(*a, **kw):
        return False, {}, "timeout"

    monkeypatch.setattr(mgr, "_get_json", timeout_fn)
    ok, msg = asyncio.run(mgr.github_latest_release("org/repo"))
    assert ok is False
    assert "zaman aşımı" in msg


def test_github_latest_release_other_error(monkeypatch):
    """Covers line 278: generic error."""
    mgr = PackageInfoManager()

    async def err_fn(*a, **kw):
        return False, {}, "unexpected:api down"

    monkeypatch.setattr(mgr, "_get_json", err_fn)
    ok, msg = asyncio.run(mgr.github_latest_release("org/repo"))
    assert ok is False
    assert "GitHub" in msg


# ─── _is_prerelease ──────────────────────────────────────────────────────────

def test_is_prerelease_invalid_version_with_semver_pre_release():
    """Covers lines 301-303: InvalidVersion + semver pre-release pattern."""
    # "1.2.3-alpha.1" is a valid semver pre-release but may trigger InvalidVersion
    result = PackageInfoManager._is_prerelease("1.2.3-alpha.1")
    # Should be True (recognized as prerelease)
    assert result is True


def test_is_prerelease_invalid_version_no_match_returns_false():
    """Covers line 305: InvalidVersion and no pre-release regex match → False."""
    # A version like "abc" is neither PEP440 nor semver pre-release
    result = PackageInfoManager._is_prerelease("notaversion")
    assert result is False


def test_is_prerelease_pep440_alpha():
    """Standard PEP440 pre-release detected via Version.is_prerelease."""
    assert PackageInfoManager._is_prerelease("2.0.0a1") is True
    assert PackageInfoManager._is_prerelease("2.0.0rc1") is True
    assert PackageInfoManager._is_prerelease("2.0.0b2") is True


def test_is_prerelease_npm_numeric():
    """npm numeric pre-release: 1.0.0-0, 2.0.0-42."""
    assert PackageInfoManager._is_prerelease("1.0.0-0") is True
    assert PackageInfoManager._is_prerelease("2.0.0-42") is True


def test_is_prerelease_stable_version():
    """Stable versions should not be prerelease."""
    assert PackageInfoManager._is_prerelease("1.0.0") is False
    assert PackageInfoManager._is_prerelease("2.31.0") is False
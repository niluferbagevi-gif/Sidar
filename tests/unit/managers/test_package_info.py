import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from managers.package_info import PackageInfoManager


def run(coro):
    return asyncio.run(coro)


class DummyResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload if payload is not None else {}
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("GET", "https://example.com")
            resp = httpx.Response(self.status_code, request=req)
            raise httpx.HTTPStatusError("boom", request=req, response=resp)


class DummyAsyncClient:
    def __init__(self, *, response=None, exc=None, capture=None, **kwargs):
        self.response = response
        self.exc = exc
        self.kwargs = kwargs
        self.capture = capture if capture is not None else {}

    async def __aenter__(self):
        self.capture["client_kwargs"] = self.kwargs
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        self.capture["url"] = url
        if self.exc:
            raise self.exc
        return self.response


def test_dummy_response_raise_for_status_raises_http_status_error():
    response = DummyResponse(status_code=500)

    with pytest.raises(httpx.HTTPStatusError):
        response.raise_for_status()


def test_init_defaults_and_config_variants(monkeypatch):
    init_paths = []

    def fake_timeout(*args, **kwargs):
        init_paths.append((args, kwargs))
        # İlk iki imza denemesini düşür, argümansız çağrıya kadar ilerlesin.
        if kwargs or args:
            raise TypeError("bad-signature")
        return "timeout-object"

    monkeypatch.setattr(httpx, "Timeout", fake_timeout)

    cfg = SimpleNamespace(PACKAGE_INFO_TIMEOUT="9", PACKAGE_INFO_CACHE_TTL="15", VERSION="9.9.9")
    manager = PackageInfoManager(cfg)

    assert manager.TIMEOUT == 9.0
    assert manager.CACHE_TTL_SECONDS == "15"
    assert manager.cache_ttl == timedelta(seconds=60)
    assert manager.timeout == "timeout-object"
    assert manager.headers["User-Agent"] == "SidarAI/9.9.9 (Software Engineer Assistant)"
    assert len(init_paths) == 3

    default_manager = PackageInfoManager()
    assert default_manager.TIMEOUT == 12.0
    assert default_manager.cache_ttl == timedelta(seconds=1800)


def test_cache_get_set_and_expire():
    manager = PackageInfoManager()

    hit, value = manager._cache_get("missing")
    assert (hit, value) == (False, {})

    manager._cache_set("k", {"v": 1})
    hit, value = manager._cache_get("k")
    assert (hit, value) == (True, {"v": 1})

    manager._cache["old"] = ({"x": 1}, datetime.now() - manager.cache_ttl - timedelta(seconds=1))
    hit, value = manager._cache_get("old")
    assert (hit, value) == (False, {})
    assert "old" not in manager._cache


def test_get_json_cache_and_all_error_paths(monkeypatch):
    manager = PackageInfoManager()
    manager._cache_set("cached-key", {"ok": True})
    assert run(manager._get_json("https://unused", cache_key="cached-key")) == (
        True,
        {"ok": True},
        "",
    )

    capture = {}
    ok_client = DummyAsyncClient(response=DummyResponse(payload={"a": 1}), capture=capture)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: ok_client)
    assert run(manager._get_json("https://example.com/a", cache_key="fresh")) == (
        True,
        {"a": 1},
        "",
    )
    assert capture["url"] == "https://example.com/a"
    assert manager._cache_get("fresh")[0] is True

    not_found_client = DummyAsyncClient(response=DummyResponse(payload={}, status_code=404))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: not_found_client)
    assert run(manager._get_json("https://example.com/404")) == (False, {}, "not_found")

    timeout_client = DummyAsyncClient(exc=httpx.TimeoutException("slow"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: timeout_client)
    assert run(manager._get_json("https://example.com/timeout")) == (False, {}, "timeout")

    req_err_client = DummyAsyncClient(
        exc=httpx.RequestError("net-fail", request=httpx.Request("GET", "https://x"))
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: req_err_client)
    ok, data, err = run(manager._get_json("https://example.com/request"))
    assert (ok, data) == (False, {})
    assert err.startswith("request:")

    boom_client = DummyAsyncClient(exc=RuntimeError("kaboom"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: boom_client)
    ok, data, err = run(manager._get_json("https://example.com/unexpected"))
    assert (ok, data) == (False, {})
    assert err.startswith("unexpected:")


def test_fetch_pypi_json_error_mapping(monkeypatch):
    manager = PackageInfoManager()

    async def fake_get_json(_url, cache_key=""):
        assert cache_key == "pypi:fastapi"
        return True, {"info": {}}, ""

    monkeypatch.setattr(manager, "_get_json", fake_get_json)
    assert run(manager._fetch_pypi_json("FastAPI")) == (True, {"info": {}}, "")

    for err, expected in [
        ("not_found", "bulunamadı"),
        ("timeout", "zaman aşımı"),
        ("request:boom", "bağlantı hatası"),
        ("other", "[HATA] PyPI: other"),
    ]:

        async def fake_err(_url, cache_key="", error=err):
            return False, {}, error

        monkeypatch.setattr(manager, "_get_json", fake_err)
        ok, _data, msg = run(manager._fetch_pypi_json("pkg"))
        assert ok is False
        assert expected in msg


def test_fetch_pypi_json_explicit_timeout_request_and_other(monkeypatch):
    manager = PackageInfoManager()

    async def get_timeout(_url, cache_key=""):
        return False, {}, "timeout"

    async def get_request(_url, cache_key=""):
        return False, {}, "request:network down"

    async def get_other(_url, cache_key=""):
        return False, {}, "mystery"

    monkeypatch.setattr(manager, "_get_json", get_timeout)
    assert run(manager._fetch_pypi_json("pkg"))[2] == "[HATA] PyPI zaman aşımı: pkg"
    monkeypatch.setattr(manager, "_get_json", get_request)
    assert "bağlantı hatası" in run(manager._fetch_pypi_json("pkg"))[2]
    monkeypatch.setattr(manager, "_get_json", get_other)
    assert run(manager._fetch_pypi_json("pkg"))[2] == "[HATA] PyPI: mystery"


def test_pypi_info_latest_and_compare(monkeypatch):
    manager = PackageInfoManager()
    payload = {
        "info": {
            "version": "2.0.0",
            "author": "Author Name",
            "author_email": "mail@example.com",
            "license": "MIT",
            "requires_python": ">=3.11",
            "summary": "short summary",
            "project_url": "https://example.org/project",
            "requires_dist": ["httpx>=0.27 ; extra == 'dev'", "pytest>=8"],
            "home_page": "https://example.org",
        },
        "releases": {
            None: {},
            "": {},
            "2.0.0": {},
            "1.5.0": {},
            "1.5.0-0": {},
            "1.0.0rc1": {},
            "0.9.0": {},
        },
    }

    async def fake_fetch(_package):
        return True, payload, ""

    monkeypatch.setattr(manager, "_fetch_pypi_json", fake_fetch)
    ok, info = run(manager.pypi_info("demo"))
    assert ok is True
    assert "[PyPI: demo]" in info
    assert "Güncel sürüm  : 2.0.0" in info
    assert "Bağımlılıklar : httpx>=0.27, pytest>=8" in info
    assert "Ana sayfa     : https://example.org" in info
    assert "1.5.0-0" not in info

    ok, latest = run(manager.pypi_latest_version("demo"))
    assert (ok, latest) == (True, "demo==2.0.0")

    async def fake_info(_pkg):
        return True, "INFO-BLOCK"

    monkeypatch.setattr(manager, "pypi_info", fake_info)
    ok, same = run(manager.pypi_compare("demo", "2.0.0"))
    assert ok is True and "✓ Güncel" in same

    ok, outdated = run(manager.pypi_compare("demo", "1.0.0"))
    assert ok is True and "⚠ Güncelleme mevcut" in outdated

    ok, invalid = run(manager.pypi_compare("demo", "not-a-version"))
    assert ok is True and "⚠ Güncelleme mevcut" in invalid


def test_pypi_info_and_compare_failure_paths(monkeypatch):
    manager = PackageInfoManager()

    async def fetch_fail(_pkg):
        return False, {}, "fetch-error"

    monkeypatch.setattr(manager, "_fetch_pypi_json", fetch_fail)
    assert run(manager.pypi_info("x")) == (False, "fetch-error")
    assert run(manager.pypi_latest_version("x")) == (False, "fetch-error")
    assert run(manager.pypi_compare("x", "1.0")) == (False, "fetch-error")

    async def fetch_ok(_pkg):
        return True, {"info": {"version": "1.0.0"}, "releases": {}}, ""

    async def info_fail(_pkg):
        return False, "bad-info"

    monkeypatch.setattr(manager, "_fetch_pypi_json", fetch_ok)
    monkeypatch.setattr(manager, "pypi_info", info_fail)
    assert run(manager.pypi_compare("x", None)) == (False, "bad-info")

    async def fetch_min(_pkg):
        return True, {"info": {}, "releases": {}}, ""

    monkeypatch.setattr(manager, "_fetch_pypi_json", fetch_min)
    monkeypatch.setattr(
        manager,
        "pypi_info",
        PackageInfoManager.pypi_info.__get__(manager, PackageInfoManager),
    )
    ok, text = run(manager.pypi_info("x"))
    assert ok is True
    assert "Bağımlılıklar" not in text
    assert "Ana sayfa" not in text


def test_npm_info_success_and_error_paths(monkeypatch):
    manager = PackageInfoManager()

    async def get_ok(_url, cache_key=""):
        assert cache_key == "npm:react"
        return (
            True,
            {
                "version": "19.0.0",
                "author": {"name": "Meta"},
                "license": "MIT",
                "description": "UI lib",
                "main": "index.js",
                "dependencies": {"a": "1", "b": "2"},
                "peerDependencies": {"c": "3"},
                "engines": {"node": ">=18"},
            },
            "",
        )

    monkeypatch.setattr(manager, "_get_json", get_ok)
    ok, text = run(manager.npm_info("react"))
    assert ok is True
    assert "[npm: react]" in text
    assert "Bağımlılıklar: a@1, b@2" in text
    assert "Peer deps    : c@3" in text
    assert "Engine gerek : {'node': '>=18'}" in text

    async def get_ok_author_str(_url, cache_key=""):
        return True, {"version": "1", "author": "Someone", "license": "Apache-2.0"}, ""

    monkeypatch.setattr(manager, "_get_json", get_ok_author_str)
    ok, text = run(manager.npm_info("pkg"))
    assert ok is True and "Yazar        : Someone" in text

    for err, expected in [
        ("not_found", "bulunamadı"),
        ("timeout", "zaman aşımı"),
        ("request:oops", "bağlantı hatası"),
        ("weird", "[HATA] npm: weird"),
    ]:

        async def get_err(_url, cache_key="", error=err):
            return False, {}, error

        monkeypatch.setattr(manager, "_get_json", get_err)
        ok, msg = run(manager.npm_info("x"))
        assert ok is False
        assert expected in msg


def test_github_releases_and_latest_release_paths(monkeypatch):
    manager = PackageInfoManager()

    async def get_releases(_url, cache_key=""):
        return (
            True,
            [
                {
                    "tag_name": "v2.0.0",
                    "name": "Major",
                    "published_at": "2026-01-10T12:00:00Z",
                    "prerelease": True,
                    "body": "line1\nline2",
                },
                {
                    "tag_name": "v1.0.0",
                    "published_at": "2025-05-01T12:00:00Z",
                    "body": "",
                },
            ],
            "",
        )

    monkeypatch.setattr(manager, "_get_json", get_releases)
    ok, text = run(manager.github_releases("owner/repo", limit=2))
    assert ok is True
    assert "(pre-release)" in text
    assert "line1 line2" in text
    assert "v1.0.0" in text

    async def get_release_without_body(_url, cache_key=""):
        return (
            True,
            [{"tag_name": "v0.1.0", "published_at": "2024-01-01T00:00:00Z", "body": ""}],
            "",
        )

    monkeypatch.setattr(manager, "_get_json", get_release_without_body)
    ok, text = run(manager.github_releases("owner/repo", limit=1))
    assert ok is True
    assert "v0.1.0" in text
    assert "    " not in text.splitlines()[-1]

    async def get_non_list(_url, cache_key=""):
        return True, {"unexpected": True}, ""

    monkeypatch.setattr(manager, "_get_json", get_non_list)
    assert run(manager.github_releases("owner/repo")) == (
        True,
        "[GitHub Releases: owner/repo]\n  Henüz release yok.",
    )

    for err, expected in [
        ("not_found", "deposu bulunamadı"),
        ("timeout", "zaman aşımı"),
        ("other", "[HATA] GitHub Releases: other"),
    ]:

        async def get_err(_url, cache_key="", error=err):
            return False, {}, error

        monkeypatch.setattr(manager, "_get_json", get_err)
        ok, msg = run(manager.github_releases("x/y"))
        assert ok is False
        assert expected in msg

    async def get_latest(_url, cache_key=""):
        return True, {"tag_name": "v3.1.4", "published_at": "2026-03-01T00:00:00Z"}, ""

    monkeypatch.setattr(manager, "_get_json", get_latest)
    assert run(manager.github_latest_release("x/y")) == (
        True,
        "x/y — En güncel: v3.1.4 [2026-03-01]",
    )

    async def get_latest_min(_url, cache_key=""):
        return True, {}, ""

    monkeypatch.setattr(manager, "_get_json", get_latest_min)
    assert run(manager.github_latest_release("x/y")) == (True, "x/y — En güncel: ? [?]")

    for err, expected in [
        ("not_found", "release bulunamadı"),
        ("timeout", "zaman aşımı"),
        ("other", "[HATA] GitHub: other"),
    ]:

        async def get_latest_err(_url, cache_key="", error=err):
            return False, {}, error

        monkeypatch.setattr(manager, "_get_json", get_latest_err)
        ok, msg = run(manager.github_latest_release("x/y"))
        assert ok is False
        assert expected in msg


def test_prerelease_helpers_status_and_repr():
    assert PackageInfoManager._is_prerelease(None) is False
    assert PackageInfoManager._is_prerelease("") is False
    assert PackageInfoManager._is_prerelease("1.0.0-1") is True
    assert PackageInfoManager._is_prerelease("1.0.0rc1") is True
    assert PackageInfoManager._is_prerelease("2.0.0-rc") is True
    assert PackageInfoManager._is_prerelease("1.2.3-foo") is True
    assert PackageInfoManager._is_prerelease("1.2.3") is False
    assert PackageInfoManager._is_prerelease("strange_version") is False

    assert str(PackageInfoManager._version_sort_key(None)) == "0.0.0"
    assert str(PackageInfoManager._version_sort_key("")) == "0.0.0"
    assert str(PackageInfoManager._version_sort_key("invalid")) == "0.0.0"
    assert str(PackageInfoManager._version_sort_key("2.1.0")) == "2.1.0"

    manager = PackageInfoManager()
    assert manager.status() == "PackageInfo: PyPI + npm + GitHub Releases — Aktif (Asenkron)"
    repr_text = repr(manager)
    assert "timeout=12.0s" in repr_text
    assert "cache_ttl=1800s" in repr_text


def test_get_json_success_without_cache_key(monkeypatch):
    manager = PackageInfoManager()
    client = DummyAsyncClient(response=DummyResponse(payload={"x": 1}))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)

    ok, data, err = run(manager._get_json("https://example.com/no-cache", cache_key=""))
    assert (ok, data, err) == (True, {"x": 1}, "")


def test_package_info_manager_isolated(monkeypatch):
    pkg = PackageInfoManager()

    async def _fake_fetch(_package):
        return True, {"info": {"version": "1.2.3"}, "releases": {"1.2.3": {}}}, ""

    monkeypatch.setattr(pkg, "_fetch_pypi_json", _fake_fetch)
    ok, latest = run(pkg.pypi_latest_version("sidar"))
    assert ok is True
    assert latest == "sidar==1.2.3"

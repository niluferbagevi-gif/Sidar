from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import asyncio

import pytest

try:
    import httpx  # type: ignore
except Exception:  # pragma: no cover - test env stub
    import sys
    import types

    httpx = types.ModuleType("httpx")

    class _Timeout:
        def __init__(self, *_args, **_kwargs):
            pass

    class _TimeoutException(Exception):
        pass

    class _RequestError(Exception):
        pass

    httpx.Timeout = _Timeout
    httpx.TimeoutException = _TimeoutException
    httpx.RequestError = _RequestError
    httpx.AsyncClient = object
    sys.modules["httpx"] = httpx

from managers.package_info import PackageInfoManager



class _DummyResponse:
    def __init__(self, *, status_code=200, payload=None, raise_exc=None):
        self.status_code = status_code
        self._payload = payload or {}
        self._raise_exc = raise_exc

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc

    def json(self):
        return self._payload


class _DummyClient:
    def __init__(self, response: _DummyResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, _url):
        return self._response


def test_get_json_uses_cache_without_http_call(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = PackageInfoManager()
    mgr._cache_set("pypi:httpx", {"ok": True})

    called = {"count": 0}

    def _forbidden_client(*_args, **_kwargs):
        called["count"] += 1
        raise AssertionError("HTTP should not be called when cache hit")

    monkeypatch.setattr("managers.package_info.httpx.AsyncClient", _forbidden_client)

    ok, data, err = asyncio.run(mgr._get_json("https://example.test", cache_key="pypi:httpx"))

    assert ok is True
    assert data == {"ok": True}
    assert err == ""
    assert called["count"] == 0


def test_get_json_returns_not_found_for_404(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = PackageInfoManager()
    response = _DummyResponse(status_code=404)
    monkeypatch.setattr("managers.package_info.httpx.AsyncClient", lambda **_kwargs: _DummyClient(response))

    ok, data, err = asyncio.run(mgr._get_json("https://example.test/not-found"))

    assert ok is False
    assert data == {}
    assert err == "not_found"


def test_pypi_compare_reports_update_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = PackageInfoManager()

    async def _fake_fetch(_package: str):
        return True, {"info": {"version": "2.0.0"}}, ""

    async def _fake_info(_package: str):
        return True, "[PyPI: demo]"

    monkeypatch.setattr(mgr, "_fetch_pypi_json", _fake_fetch)
    monkeypatch.setattr(mgr, "pypi_info", _fake_info)

    ok, text = asyncio.run(mgr.pypi_compare("demo", "1.0.0"))

    assert ok is True
    assert "⚠ Güncelleme mevcut" in text
    assert "1.0.0 → 2.0.0" in text


def test_is_prerelease_handles_numeric_npm_pre_release() -> None:
    assert PackageInfoManager._is_prerelease("1.2.3-42") is True
    assert PackageInfoManager._is_prerelease("1.2.3") is False


def test_status_and_repr_include_runtime_settings() -> None:
    mgr = PackageInfoManager(SimpleNamespace(PACKAGE_INFO_TIMEOUT=3, PACKAGE_INFO_CACHE_TTL=120, VERSION="9.9.9"))

    assert "Asenkron" in mgr.status()
    assert "timeout=3.0s" in repr(mgr)
    assert mgr.cache_ttl == timedelta(seconds=120)

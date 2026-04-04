from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return name in sys.modules


if not _has_module("httpx"):
    fake_httpx = types.ModuleType("httpx")

    class Timeout:
        def __init__(self, *args, **kwargs):
            return None

    fake_httpx.Timeout = Timeout
    fake_httpx.TimeoutException = Exception
    fake_httpx.RequestError = Exception
    fake_httpx.AsyncClient = object
    sys.modules["httpx"] = fake_httpx

from managers.package_info import PackageInfoManager


def test_init_timeout_fallback_signatures(monkeypatch: pytest.MonkeyPatch) -> None:
    class _TimeoutSecondOnly:
        def __init__(self, *args, **kwargs):
            if kwargs:
                raise TypeError("kwargs unsupported")

    monkeypatch.setattr("managers.package_info.httpx.Timeout", _TimeoutSecondOnly)
    mgr = PackageInfoManager(SimpleNamespace(PACKAGE_INFO_CACHE_TTL=10))
    assert isinstance(mgr.timeout, _TimeoutSecondOnly)
    assert mgr.cache_ttl == timedelta(seconds=60)

    class _TimeoutNoArgsOnly:
        def __init__(self, *args, **kwargs):
            if args or kwargs:
                raise TypeError("no args only")

    monkeypatch.setattr("managers.package_info.httpx.Timeout", _TimeoutNoArgsOnly)
    mgr2 = PackageInfoManager()
    assert isinstance(mgr2.timeout, _TimeoutNoArgsOnly)


def test_cache_get_miss_and_expired_entry() -> None:
    mgr = PackageInfoManager()

    hit, data = mgr._cache_get("missing")
    assert hit is False
    assert data == {}

    mgr._cache["old"] = ({"v": 1}, datetime.now() - (mgr.cache_ttl + timedelta(seconds=1)))
    hit_old, data_old = mgr._cache_get("old")
    assert hit_old is False
    assert data_old == {}
    assert "old" not in mgr._cache


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    def __init__(self, response: _Resp):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, _url):
        return self.response


def test_get_json_sets_cache_and_handles_unexpected_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = PackageInfoManager()
    monkeypatch.setattr("managers.package_info.httpx.AsyncClient", lambda **_kwargs: _Client(_Resp(payload={"x": 1})))

    ok, data, err = asyncio.run(mgr._get_json("https://example.test", cache_key="k1"))
    assert ok is True and err == "" and data == {"x": 1}
    assert "k1" in mgr._cache

    class _BoomClient:
        async def __aenter__(self):
            raise RuntimeError("boom")

        async def __aexit__(self, *_args):
            return False

    class _TimeoutExc(Exception):
        pass

    class _ReqExc(Exception):
        pass

    monkeypatch.setattr("managers.package_info.httpx.TimeoutException", _TimeoutExc)
    monkeypatch.setattr("managers.package_info.httpx.RequestError", _ReqExc)
    monkeypatch.setattr("managers.package_info.httpx.AsyncClient", lambda **_kwargs: _BoomClient())
    ok2, data2, err2 = asyncio.run(mgr._get_json("https://example.test/boom", cache_key="k2"))
    assert ok2 is False and data2 == {}
    assert err2.startswith("unexpected:")


def test_fetch_pypi_json_error_mappings(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = PackageInfoManager()

    async def _nf(*_args, **_kwargs):
        return False, {}, "not_found"

    async def _to(*_args, **_kwargs):
        return False, {}, "timeout"

    async def _rq(*_args, **_kwargs):
        return False, {}, "request:offline"

    async def _uk(*_args, **_kwargs):
        return False, {}, "weird"

    monkeypatch.setattr(mgr, "_get_json", _nf)
    ok_nf, _, msg_nf = asyncio.run(mgr._fetch_pypi_json("pkg"))
    assert ok_nf is False and "bulunamadı" in msg_nf

    monkeypatch.setattr(mgr, "_get_json", _to)
    ok_to, _, msg_to = asyncio.run(mgr._fetch_pypi_json("pkg"))
    assert ok_to is False and "zaman aşımı" in msg_to

    monkeypatch.setattr(mgr, "_get_json", _rq)
    ok_rq, _, msg_rq = asyncio.run(mgr._fetch_pypi_json("pkg"))
    assert ok_rq is False and "bağlantı hatası" in msg_rq

    monkeypatch.setattr(mgr, "_get_json", _uk)
    ok_uk, _, msg_uk = asyncio.run(mgr._fetch_pypi_json("pkg"))
    assert ok_uk is False and msg_uk.endswith("weird")


def test_pypi_paths_latest_compare_and_info(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = PackageInfoManager()

    async def _fail_fetch(_package: str):
        return False, {}, "fetch-error"

    monkeypatch.setattr(mgr, "_fetch_pypi_json", _fail_fetch)
    ok_info, msg_info = asyncio.run(mgr.pypi_info("demo"))
    assert ok_info is False and msg_info == "fetch-error"

    ok_latest_fail, msg_latest_fail = asyncio.run(mgr.pypi_latest_version("demo"))
    assert ok_latest_fail is False and msg_latest_fail == "fetch-error"

    ok_cmp_fail, msg_cmp_fail = asyncio.run(mgr.pypi_compare("demo", "1.0.0"))
    assert ok_cmp_fail is False and msg_cmp_fail == "fetch-error"

    async def _success_fetch(_package: str):
        return True, {
            "info": {
                "version": "",
                "author": "",
                "author_email": "mail@example.org",
                "license": "",
                "requires_python": "",
                "summary": "",
                "requires_dist": ["a>=1; python_version>'3.10'", "b==2"],
                "home_page": "https://home.example",
            },
            "releases": {None: {}, " ": {}, "1.0.0": {}, "1.0.0rc1": {}},
        }, ""

    monkeypatch.setattr(mgr, "_fetch_pypi_json", _success_fetch)
    ok_info2, text = asyncio.run(mgr.pypi_info("demo"))
    assert ok_info2 is True
    assert "mail@example.org" in text
    assert "Bağımlılıklar" in text
    assert "Ana sayfa" in text

    ok_latest_ok, latest_text = asyncio.run(mgr.pypi_latest_version("demo"))
    assert ok_latest_ok is True and latest_text == "demo==?"

    async def _info_fail(_package: str):
        return False, "info-fail"

    monkeypatch.setattr(mgr, "pypi_info", _info_fail)
    ok_cmp_info_fail, msg_cmp_info_fail = asyncio.run(mgr.pypi_compare("demo", "1.0.0"))
    assert ok_cmp_info_fail is False and msg_cmp_info_fail == "info-fail"

    async def _info_ok(_package: str):
        return True, "[PyPI: demo]"

    async def _fetch_ver(_package: str):
        return True, {"info": {"version": "stable"}}, ""

    monkeypatch.setattr(mgr, "pypi_info", _info_ok)
    monkeypatch.setattr(mgr, "_fetch_pypi_json", _fetch_ver)

    ok_cmp_same, cmp_same = asyncio.run(mgr.pypi_compare("demo", "stable"))
    assert ok_cmp_same is True and "✓ Güncel" in cmp_same

    ok_cmp_diff, cmp_diff = asyncio.run(mgr.pypi_compare("demo", "legacy"))
    assert ok_cmp_diff is True and "⚠ Güncelleme mevcut" in cmp_diff


def test_npm_and_github_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = PackageInfoManager()

    async def _err(_url: str, cache_key: str = ""):
        if cache_key.startswith("npm"):
            return False, {}, "request:offline"
        if cache_key.startswith("ghrel"):
            return False, {}, "timeout"
        return False, {}, "bad"

    monkeypatch.setattr(mgr, "_get_json", _err)

    ok_npm, npm_msg = asyncio.run(mgr.npm_info("demo"))
    assert ok_npm is False and "bağlantı hatası" in npm_msg

    ok_ghrel, ghrel_msg = asyncio.run(mgr.github_releases("org/repo"))
    assert ok_ghrel is False and "zaman aşımı" in ghrel_msg

    ok_ghlatest, ghlatest_msg = asyncio.run(mgr.github_latest_release("org/repo"))
    assert ok_ghlatest is False and "[HATA] GitHub:" in ghlatest_msg

    async def _err2(_url: str, cache_key: str = ""):
        if cache_key.startswith("npm"):
            return False, {}, "unexpected"
        if cache_key.startswith("ghrel"):
            return False, {}, "other"
        return False, {}, "timeout"

    monkeypatch.setattr(mgr, "_get_json", _err2)
    ok_npm2, npm_msg2 = asyncio.run(mgr.npm_info("demo"))
    assert ok_npm2 is False and npm_msg2.endswith("unexpected")

    ok_ghrel2, ghrel_msg2 = asyncio.run(mgr.github_releases("org/repo"))
    assert ok_ghrel2 is False and "GitHub Releases" in ghrel_msg2

    ok_ghlatest2, ghlatest_msg2 = asyncio.run(mgr.github_latest_release("org/repo"))
    assert ok_ghlatest2 is False and "zaman aşımı" in ghlatest_msg2


def test_npm_success_and_github_release_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = PackageInfoManager()

    async def _ok(_url: str, cache_key: str = ""):
        if cache_key.startswith("npm"):
            return True, {
                "version": "1.0.0",
                "author": "plain-author",
                "description": "desc",
                "main": "index.js",
                "dependencies": {},
                "peerDependencies": {},
                "engines": {},
            }, ""
        if cache_key.startswith("ghrel"):
            return True, [{"tag_name": "v1", "prerelease": True, "body": "   \n", "published_at": None}], ""
        return True, {"tag_name": "v1", "published_at": None}, ""

    monkeypatch.setattr(mgr, "_get_json", _ok)

    ok_npm, text_npm = asyncio.run(mgr.npm_info("demo"))
    assert ok_npm is True and "plain-author" in text_npm
    assert "Bağımlılıklar" not in text_npm and "Peer deps" not in text_npm and "Engine gerek" not in text_npm

    ok_rel, text_rel = asyncio.run(mgr.github_releases("org/repo", limit=1))
    assert ok_rel is True and "(pre-release)" in text_rel

    async def _no_releases(_url: str, cache_key: str = ""):
        return True, {"not": "a-list"}, ""

    monkeypatch.setattr(mgr, "_get_json", _no_releases)
    ok_none, text_none = asyncio.run(mgr.github_releases("org/repo", limit=1))
    assert ok_none is True and "Henüz release yok" in text_none


def test_helper_methods_for_empty_and_invalid_versions() -> None:
    assert PackageInfoManager._is_prerelease("") is False
    assert PackageInfoManager._is_prerelease("definitely_invalid") is False
    assert str(PackageInfoManager._version_sort_key(None)) == "0.0.0"

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types


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


def test_package_info_npm_and_github_paths(monkeypatch):
    mgr = PackageInfoManager()

    async def _fake_get_json(url: str, cache_key: str = ""):
        if "npmjs" in url:
            return True, {
                "version": "1.2.3",
                "author": {"name": "pkg-team"},
                "dependencies": {"a": "^1", "b": "^2"},
                "peerDependencies": {"react": "^18"},
                "engines": {"node": ">=18"},
            }, ""
        if url.endswith("/releases"):
            return True, [{"tag_name": "v2.0.0", "name": "Stable", "published_at": "2026-01-01T00:00:00Z", "body": "notes"}], ""
        return True, {"tag_name": "v2.0.0", "published_at": "2026-01-01T00:00:00Z"}, ""

    monkeypatch.setattr(mgr, "_get_json", _fake_get_json)

    ok_npm, npm_text = asyncio.run(mgr.npm_info("demo"))
    assert ok_npm is True
    assert "Bağımlılıklar" in npm_text
    assert "Peer deps" in npm_text

    ok_rel, rel_text = asyncio.run(mgr.github_releases("org/repo", limit=1))
    assert ok_rel is True
    assert "v2.0.0" in rel_text

    ok_latest, latest = asyncio.run(mgr.github_latest_release("org/repo"))
    assert ok_latest is True
    assert "En güncel: v2.0.0" in latest


def test_package_info_error_and_version_helpers(monkeypatch):
    mgr = PackageInfoManager()

    async def _not_found(*_args, **_kwargs):
        return False, {}, "not_found"

    monkeypatch.setattr(mgr, "_get_json", _not_found)
    ok_release, err_release = asyncio.run(mgr.github_releases("missing/repo"))
    ok_latest, err_latest = asyncio.run(mgr.github_latest_release("missing/repo"))

    assert ok_release is False and "bulunamadı" in err_release
    assert ok_latest is False and "release bulunamadı" in err_latest

    assert PackageInfoManager._is_prerelease("1.2.3-alpha.1") is True
    assert str(PackageInfoManager._version_sort_key("bad-version")) == "0.0.0"

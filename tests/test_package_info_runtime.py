import asyncio
import importlib.util
from pathlib import Path
import types
import sys


def _load_package_info_module():
    if "httpx" not in sys.modules:
        class _Timeout:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        class _TimeoutException(Exception):
            pass

        class _RequestError(Exception):
            pass

        class _AsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def get(self, url):
                return types.SimpleNamespace(status_code=200, json=lambda: {}, raise_for_status=lambda: None)

        sys.modules["httpx"] = types.SimpleNamespace(
            Timeout=_Timeout,
            TimeoutException=_TimeoutException,
            RequestError=_RequestError,
            AsyncClient=_AsyncClient,
        )
    spec = importlib.util.spec_from_file_location("package_info_under_test", Path("managers/package_info.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


PKG = _load_package_info_module()
PackageInfoManager = PKG.PackageInfoManager


def test_cache_and_helpers_behavior():
    mgr = PackageInfoManager()
    mgr._cache_set("x", {"a": 1})
    hit, data = mgr._cache_get("x")
    assert hit is True and data["a"] == 1

    assert mgr._is_prerelease("1.0.0-0") is True
    assert mgr._is_prerelease("1.0.0") is False
    assert str(mgr._version_sort_key("bad")) == "0.0.0"
    assert "PackageInfo" in mgr.status()
    assert "PackageInfoManager" in repr(mgr)


def test_pypi_npm_and_github_formatting(monkeypatch):
    mgr = PackageInfoManager(config=types.SimpleNamespace(VERSION="3.1", PACKAGE_INFO_TIMEOUT=5, PACKAGE_INFO_CACHE_TTL=120))

    async def fake_get_json(url, cache_key=""):
        if "pypi.org" in url:
            return True, {
                "info": {
                    "version": "2.0.0",
                    "author": "dev",
                    "license": "MIT",
                    "requires_python": ">=3.11",
                    "summary": "sum",
                    "project_url": "https://pypi.org/project/x",
                    "requires_dist": ["a>=1; python_version>='3.11'"],
                    "home_page": "https://x.dev",
                },
                "releases": {"2.0.0": {}, "1.9.0": {}, "2.0.0rc1": {}},
            }, ""
        if "registry.npmjs.org" in url:
            return True, {
                "version": "1.2.3",
                "author": {"name": "npmdev"},
                "license": "ISC",
                "description": "npm desc",
                "main": "index.js",
                "dependencies": {"a": "^1", "b": "^2"},
                "peerDependencies": {"react": "^18"},
                "engines": {"node": ">=18"},
            }, ""
        if url.endswith("/latest"):
            return True, {"tag_name": "v2.1", "published_at": "2024-01-03T12:00:00Z"}, ""
        return True, [
            {
                "tag_name": "v2",
                "name": "Release 2",
                "published_at": "2024-01-02T10:00:00Z",
                "prerelease": False,
                "body": "notes",
            }
        ], ""

    monkeypatch.setattr(mgr, "_get_json", fake_get_json)

    ok, info = asyncio.run(mgr.pypi_info("pkg"))
    assert ok is True and "Güncel sürüm" in info and "Bağımlılıklar" in info

    ok, latest = asyncio.run(mgr.pypi_latest_version("pkg"))
    assert ok is True and latest.endswith("==2.0.0")

    ok, cmp_text = asyncio.run(mgr.pypi_compare("pkg", "1.0.0"))
    assert ok is True and "Güncelleme mevcut" in cmp_text

    ok, npm = asyncio.run(mgr.npm_info("leftpad"))
    assert ok is True and "Peer deps" in npm and "Engine gerek" in npm

    ok, rel = asyncio.run(mgr.github_releases("org/repo", limit=1))
    assert ok is True and "GitHub Releases" in rel

    ok, latest_rel = asyncio.run(mgr.github_latest_release("org/repo"))
    assert ok is True and "En güncel" in latest_rel


def test_error_mapping_paths(monkeypatch):
    mgr = PackageInfoManager()

    async def nf(*args, **kwargs):
        return False, {}, "not_found"

    monkeypatch.setattr(mgr, "_get_json", nf)
    ok, msg = asyncio.run(mgr.pypi_info("x"))
    assert ok is False and "bulunamadı" in msg

    async def timeout(*args, **kwargs):
        return False, {}, "timeout"

    monkeypatch.setattr(mgr, "_get_json", timeout)
    ok, msg = asyncio.run(mgr.npm_info("x"))
    assert ok is False and "zaman aşımı" in msg

    async def req(*args, **kwargs):
        return False, {}, "request:boom"

    monkeypatch.setattr(mgr, "_get_json", req)
    ok, msg = asyncio.run(mgr.github_releases("x/y"))
    assert ok is False and "request:boom" in msg

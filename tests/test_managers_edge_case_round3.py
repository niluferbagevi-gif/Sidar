import asyncio
import sys
import types
from pathlib import Path

from tests.test_code_manager_runtime import CM_MOD, DummySecurity
from tests.test_github_manager_runtime import GM
from tests.test_web_search_runtime import _load_web_search_module


def test_code_manager_execute_code_truncates_large_docker_logs(monkeypatch, tmp_path: Path):
    sec = DummySecurity(tmp_path, can_execute=True)
    monkeypatch.setattr(CM_MOD.CodeManager, "_init_docker", lambda self: None)
    mgr = CM_MOD.CodeManager(sec, tmp_path)
    mgr.docker_available = True
    mgr.max_output_chars = 20

    class _Container:
        status = "running"

        def reload(self):
            self.status = "exited"

        def logs(self, **kwargs):
            return ("x" * 200).encode("utf-8")

        def remove(self, force=False):
            return None

    class _Containers:
        def run(self, **kwargs):
            return _Container()

    class _DockerErrors:
        class ImageNotFound(Exception):
            pass

    monkeypatch.setitem(sys.modules, "docker", types.SimpleNamespace(errors=_DockerErrors))
    mgr.docker_client = types.SimpleNamespace(containers=_Containers())

    ok, out = mgr.execute_code("print('x')")
    assert ok is True
    assert "ÇIKTI KIRPILDI" in out


def test_code_manager_init_docker_wsl_fallback_all_sockets_fail(monkeypatch, tmp_path: Path):
    sec = DummySecurity(tmp_path)
    monkeypatch.setattr(CM_MOD.CodeManager, "_init_docker", lambda self: None)
    mgr = CM_MOD.CodeManager(sec, tmp_path)

    class _DockerClient:
        def __init__(self, base_url=None):
            self.base_url = base_url

        def ping(self):
            raise RuntimeError("socket down")

    class _DockerModule:
        DockerClient = _DockerClient

        @staticmethod
        def from_env():
            raise RuntimeError("daemon down")

    monkeypatch.setitem(sys.modules, "docker", _DockerModule)
    CM_MOD.CodeManager._init_docker(mgr)
    assert mgr.docker_available is False


def test_github_manager_missing_token_with_repo_name_raises_and_not_found_strings():
    try:
        GM.GitHubManager(token="", repo_name="org/repo", require_token=False)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "GITHUB_TOKEN" in str(exc)

    assert GM._is_not_found_error(Exception("UnknownObjectException: Not Found")) is True
    assert GM._is_not_found_error(Exception("403 forbidden")) is False


def test_github_read_remote_file_handles_directory_listing_objects():
    m = GM.GitHubManager.__new__(GM.GitHubManager)
    m._repo = types.SimpleNamespace(
        get_contents=lambda *_a, **_k: [
            types.SimpleNamespace(type="dir", name="sub"),
            types.SimpleNamespace(type="file", name="a.py"),
        ]
    )
    ok, txt = m.read_remote_file("src")
    assert ok is True
    assert "[Dizin: src]" in txt and "📂 sub" in txt and "📄 a.py" in txt


def test_web_search_no_results_and_network_warning_paths(monkeypatch, caplog):
    mod = _load_web_search_module(monkeypatch)
    monkeypatch.setattr(mod.WebSearchManager, "_check_ddg", lambda self: False)

    cfg = types.SimpleNamespace(
        SEARCH_ENGINE="auto",
        TAVILY_API_KEY="t",
        GOOGLE_SEARCH_API_KEY="g",
        GOOGLE_SEARCH_CX="cx",
        WEB_SEARCH_MAX_RESULTS=5,
        WEB_FETCH_TIMEOUT=15,
        WEB_SCRAPE_MAX_CHARS=12000,
    )
    m = mod.WebSearchManager(cfg)

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": []}

    class _ClientNoRes:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(mod.httpx, "AsyncClient", _ClientNoRes)
    ok, txt = asyncio.run(m._search_tavily("query", 3))
    assert ok is True and "NO_RESULTS" in txt

    class _ClientBoom(_ClientNoRes):
        async def get(self, *a, **k):
            raise RuntimeError("network boom")

    monkeypatch.setattr(mod.httpx, "AsyncClient", _ClientBoom)
    with caplog.at_level("WARNING"):
        ok2, txt2 = asyncio.run(m._search_google("query", 3))
    assert ok2 is False and "Google Search" in txt2
    assert any("Google API hatası" in rec.message for rec in caplog.records)

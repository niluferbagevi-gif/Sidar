import asyncio
import importlib
import sys
import types
from unittest.mock import AsyncMock

import pytest


class Dummy:
    def __init__(self, *args, **kwargs):
        pass


def _load_auto_handle(monkeypatch: pytest.MonkeyPatch):
    for module_name, class_name in [
        ("managers.code_manager", "CodeManager"),
        ("managers.system_health", "SystemHealthManager"),
        ("managers.github_manager", "GitHubManager"),
        ("managers.web_search", "WebSearchManager"),
        ("managers.package_info", "PackageInfoManager"),
        ("core.memory", "ConversationMemory"),
        ("core.rag", "DocumentStore"),
    ]:
        mod = types.ModuleType(module_name)
        setattr(mod, class_name, Dummy)
        monkeypatch.setitem(sys.modules, module_name, mod)

    sys.modules.pop("agent.auto_handle", None)
    return importlib.import_module("agent.auto_handle")


class FakeMemory:
    def __init__(self):
        self._last_file = None
        self.cleared = False

    def get_last_file(self):
        return self._last_file

    def set_last_file(self, path: str):
        self._last_file = path

    def clear(self):
        self.cleared = True


class AsyncClearMemory(FakeMemory):
    async def clear(self):
        self.cleared = True


class FakeCode:
    def __init__(self, read_map=None):
        self.read_map = read_map or {}
        self.security = types.SimpleNamespace(status_report=lambda: "security")

    def list_directory(self, path):
        return True, f"listed:{path}"

    def read_file(self, path):
        return self.read_map.get(path, (False, "missing"))

    def validate_python_syntax(self, content):
        return True, "valid py"

    def validate_json(self, content):
        return True, "valid json"

    def audit_project(self, path):
        return "audit-ok"


class FakeHealth:
    def full_report(self):
        return "health-ok"

    def optimize_gpu_memory(self):
        return "gpu-ok"


class FakeGithub:
    def __init__(self, available=True):
        self.available = available
        self.last_list_pr_args = None

    def is_available(self):
        return self.available

    def list_pull_requests(self, state="open", limit=10):
        self.last_list_pr_args = (state, limit)
        return True, f"prs:{state}:{limit}"


class FakeWeb:
    async def search(self, query):
        return True, f"search:{query}"

    async def fetch_url(self, url):
        return True, f"url:{url}"

    async def search_docs(self, lib, topic):
        return True, f"docs:{lib}:{topic}"

    async def search_stackoverflow(self, query):
        return True, f"so:{query}"


class FakePkg:
    async def pypi_info(self, package):
        return True, f"pypi:{package}"

    async def pypi_compare(self, package, version):
        return True, f"pypi:{package}:{version}"

    async def npm_info(self, package):
        return True, f"npm:{package}"

    async def github_releases(self, repo):
        return True, f"releases:{repo}"


class FakeDocs:
    def search(self, query, _unused=None, mode="auto"):
        return True, f"docs_search:{query}:{mode}"

    def list_documents(self):
        return "docs_list"

    async def add_document_from_url(self, url, title=""):
        return True, f"docs_add:{url}:{title}"


def _build_handler(monkeypatch, memory=None, code=None, github=None):
    mod = _load_auto_handle(monkeypatch)
    return mod.AutoHandle(
        code=code or FakeCode(),
        health=FakeHealth(),
        github=github or FakeGithub(),
        memory=memory or FakeMemory(),
        web=FakeWeb(),
        pkg=FakePkg(),
        docs=FakeDocs(),
    )


def test_handle_rejects_long_input(monkeypatch):
    h = _build_handler(monkeypatch)
    handled, response = asyncio.run(h.handle("x" * 2001))
    assert (handled, response) == (False, "")


def test_dot_status_shortcut_calls_health(monkeypatch):
    h = _build_handler(monkeypatch)
    h._try_health = AsyncMock(return_value=(True, "health"))

    handled, response = asyncio.run(h.handle(".status"))

    assert handled is True
    assert response == "health"
    h._try_health.assert_awaited_once_with(".status")


def test_handle_defers_multi_step_commands(monkeypatch):
    h = _build_handler(monkeypatch)
    handled, response = asyncio.run(h.handle("Önce durumu göster sonra commitleri listele"))
    assert (handled, response) == (False, "")


def test_try_read_file_uses_memory_and_truncates_preview(monkeypatch):
    memory = FakeMemory()
    memory.set_last_file("agent/demo.py")
    long_content = "\n".join([f"line {i}" for i in range(85)])
    code = FakeCode(read_map={"agent/demo.py": (True, long_content)})
    h = _build_handler(monkeypatch, memory=memory, code=code)

    handled, response = h._try_read_file("dosya içeriğini göster", "dosya içeriğini göster")

    assert handled is True
    assert "[agent/demo.py]" in response
    assert "... (5 satır daha)" in response
    assert "line 79" in response


def test_try_read_file_without_path_returns_warning(monkeypatch):
    h = _build_handler(monkeypatch, memory=FakeMemory())
    handled, response = h._try_read_file("dosya içeriğini getir", "dosya içeriğini getir")
    assert handled is True
    assert "Hangi dosyayı" in response


def test_try_clear_memory_accepts_async_clear(monkeypatch):
    memory = AsyncClearMemory()
    h = _build_handler(monkeypatch, memory=memory)

    handled, response = asyncio.run(h._try_clear_memory(".clear"))

    assert handled is True
    assert memory.cleared is True
    assert "temizlendi" in response


def test_try_github_list_prs_parses_state_and_limit(monkeypatch):
    github = FakeGithub(available=True)
    h = _build_handler(monkeypatch, github=github)

    handled, response = h._try_github_list_prs("kapalı 25 pr listele", "kapalı 25 pr listele")

    assert handled is True
    assert response == "prs:closed:25"
    assert github.last_list_pr_args == ("closed", 25)


def test_try_docs_add_supports_secondary_url_form(monkeypatch):
    h = _build_handler(monkeypatch)

    handled, response = asyncio.run(
        h._try_docs_add(
            'bu belgeyi depoya ekle https://example.com/docs "FastAPI Rehberi"',
            'bu belgeyi depoya ekle https://example.com/docs "FastAPI Rehberi"',
        )
    )

    assert handled is True
    assert response == "docs_add:https://example.com/docs:FastAPI Rehberi"

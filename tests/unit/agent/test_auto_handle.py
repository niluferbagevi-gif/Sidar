"""Unit tests for ``agent.auto_handle``."""

import asyncio
import importlib
import logging
import sys
import types
from unittest.mock import AsyncMock

import pytest


class Dummy:
    """Placeholder class that accepts and ignores any constructor arguments."""

    def __init__(self, *args, **kwargs):
        """Ignore all arguments."""
        pass


def test_dummy_constructor_accepts_any_args():
    """Dummy constructor accepts any args."""
    Dummy(1, 2, key="value")


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

    module = importlib.import_module("agent.auto_handle")
    return importlib.reload(module)


class FakeMemory:
    """Memory stand-in that tracks the last file and whether it was cleared."""

    def __init__(self):
        """Start with no last file and not cleared."""
        self._last_file = None
        self.cleared = False

    def get_last_file(self):
        """Return the last recorded file path."""
        return self._last_file

    def set_last_file(self, path: str):
        """Record the last file path."""
        self._last_file = path

    def clear(self):
        """Mark the memory cleared."""
        self.cleared = True


class AsyncClearMemory(FakeMemory):
    """FakeMemory variant with an async ``clear``."""

    async def clear(self):
        """Mark the memory cleared asynchronously."""
        self.cleared = True


class FakeCode:
    """CodeManager stand-in that serves reads from a preset map."""

    def __init__(self, read_map=None):
        """Store the read map and a stub security reporter."""
        self.read_map = read_map or {}
        self.security = types.SimpleNamespace(status_report=lambda: "security")

    def list_directory(self, path):
        """Return a fixed listing for the path."""
        return True, f"listed:{path}"

    def read_file(self, path):
        """Return the preset result for the path, or a missing-file failure."""
        return self.read_map.get(path, (False, "missing"))

    def validate_python_syntax(self, content):
        """Report the Python content as valid."""
        return True, "valid py"

    def validate_json(self, content):
        """Report the JSON content as valid."""
        return True, "valid json"

    def audit_project(self, path):
        """Return a fixed audit report."""
        return "audit-ok"


class FakeHealth:
    """SystemHealthManager stand-in with fixed reports."""

    def full_report(self):
        """Return a fixed health report."""
        return "health-ok"

    def optimize_gpu_memory(self):
        """Return a fixed GPU optimization result."""
        return "gpu-ok"


class FakeGithub:
    """GitHubManager stand-in that records the arguments of each call."""

    def __init__(self, available=True):
        """Set availability and clear the recorded call arguments."""
        self.available = available
        self.last_list_pr_args = None
        self.last_commits_n = None
        self.last_get_pr = None
        self.last_get_pr_files = None
        self.last_read_path = None

    def is_available(self):
        """Return the configured availability."""
        return self.available

    def list_commits(self, n=10):
        """Record the commit count and return a fixed result."""
        self.last_commits_n = n
        return True, f"commits:{n}"

    def get_repo_info(self):
        """Return fixed repository info."""
        return True, "repo:info"

    def list_files(self, path=""):
        """Return a fixed listing for the path."""
        return True, f"files:{path}"

    def read_remote_file(self, path):
        """Record the path and return fixed remote content."""
        self.last_read_path = path
        return True, f"remote:{path}"

    def list_pull_requests(self, state="open", limit=10):
        """Record the state and limit and return a fixed PR list."""
        self.last_list_pr_args = (state, limit)
        return True, f"prs:{state}:{limit}"

    def get_pull_request(self, number):
        """Record the PR number and return fixed PR details."""
        self.last_get_pr = number
        return True, f"pr:{number}"

    def get_pr_files(self, number):
        """Record the PR number and return its fixed file list."""
        self.last_get_pr_files = number
        return True, f"pr_files:{number}"


class FakeWeb:
    """WebSearchManager stand-in with echoing async results."""

    async def search(self, query):
        """Echo the search query."""
        return True, f"search:{query}"

    async def fetch_url(self, url):
        """Echo the URL."""
        return True, f"url:{url}"

    async def search_docs(self, lib, topic):
        """Echo the library and topic."""
        return True, f"docs:{lib}:{topic}"

    async def search_stackoverflow(self, query):
        """Echo the Stack Overflow query."""
        return True, f"so:{query}"


class FakePkg:
    """PackageInfoManager stand-in with echoing async results."""

    async def pypi_info(self, package):
        """Echo the PyPI package."""
        return True, f"pypi:{package}"

    async def pypi_compare(self, package, version):
        """Echo the PyPI package and version."""
        return True, f"pypi:{package}:{version}"

    async def npm_info(self, package):
        """Echo the npm package."""
        return True, f"npm:{package}"

    async def github_releases(self, repo):
        """Echo the GitHub releases repository."""
        return True, f"releases:{repo}"


class FakeDocs:
    """Document store stand-in with echoing results."""

    def search(self, query, _unused=None, mode="auto"):
        """Echo the search query and mode."""
        return True, f"docs_search:{query}:{mode}"

    def list_documents(self):
        """Return a fixed document list."""
        return "docs_list"

    async def add_document_from_url(self, url, title=""):
        """Echo the URL and title."""
        return True, f"docs_add:{url}:{title}"


class AsyncDocs(FakeDocs):
    """FakeDocs variant with an async ``search``."""

    async def search(self, query, _unused=None, mode="auto"):
        """Echo the search query and mode asynchronously."""
        return True, f"docs_search_async:{query}:{mode}"


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
    """Handle rejects long input."""
    h = _build_handler(monkeypatch)
    handled, response = asyncio.run(h.handle("x" * 2001))
    assert (handled, response) == (False, "")


def test_dot_status_shortcut_calls_health(monkeypatch):
    """Dot status shortcut calls health."""
    h = _build_handler(monkeypatch)
    h._try_health = AsyncMock(return_value=(True, "health"))

    handled, response = asyncio.run(h.handle(".status"))

    assert handled is True
    assert response == "health"
    h._try_health.assert_awaited_once_with(".status")


def test_handle_defers_multi_step_commands(monkeypatch):
    """Handle defers multi step commands."""
    h = _build_handler(monkeypatch)
    handled, response = asyncio.run(h.handle("Önce durumu göster sonra commitleri listele"))
    assert (handled, response) == (False, "")


def test_try_read_file_uses_memory_and_truncates_preview(monkeypatch):
    """Try read file uses memory and truncates preview."""
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
    """Try read file without path returns warning."""
    h = _build_handler(monkeypatch, memory=FakeMemory())
    handled, response = h._try_read_file("dosya içeriğini getir", "dosya içeriğini getir")
    assert handled is True
    assert "Hangi dosyayı" in response


def test_try_clear_memory_accepts_async_clear(monkeypatch):
    """Try clear memory accepts async clear."""
    memory = AsyncClearMemory()
    h = _build_handler(monkeypatch, memory=memory)

    handled, response = asyncio.run(h._try_clear_memory(".clear"))

    assert handled is True
    assert memory.cleared is True
    assert "temizlendi" in response


def test_try_github_list_prs_parses_state_and_limit(monkeypatch):
    """Try github list prs parses state and limit."""
    github = FakeGithub(available=True)
    h = _build_handler(monkeypatch, github=github)

    handled, response = h._try_github_list_prs("kapalı 25 pr listele", "kapalı 25 pr listele")

    assert handled is True
    assert response == "prs:closed:25"
    assert github.last_list_pr_args == ("closed", 25)


def test_try_docs_add_supports_secondary_url_form(monkeypatch):
    """Try docs add supports secondary url form."""
    h = _build_handler(monkeypatch)

    handled, response = asyncio.run(
        h._try_docs_add(
            'bu belgeyi depoya ekle https://example.com/docs "FastAPI Rehberi"',
            'bu belgeyi depoya ekle https://example.com/docs "FastAPI Rehberi"',
        )
    )

    assert handled is True
    assert response == "docs_add:https://example.com/docs:FastAPI Rehberi"


def test_try_list_directory_extracts_default_and_explicit_path(monkeypatch):
    """Try list directory extracts default and explicit path."""
    h = _build_handler(monkeypatch)
    handled, response = h._try_list_directory(
        "klasör içeriğini listele", "klasör içeriğini listele"
    )
    assert (handled, response) == (True, "listed:.")

    handled, response = h._try_list_directory("kök dizin listele", 'kök dizin listele "/tmp/demo"')
    assert (handled, response) == (True, "listed:/tmp/demo")


def test_dot_heal_command_parses_local_log(monkeypatch, tmp_path):
    """Dot heal command parses local log."""
    h = _build_handler(monkeypatch)
    log_file = tmp_path / "mypy.log"
    log_file.write_text(
        "core/x.py:7: error: Incompatible types in assignment [assignment]\n",
        encoding="utf-8",
    )

    handled, response = asyncio.run(h.handle(f".heal {log_file}"))

    assert handled is True
    assert "Yerel self-heal analizi hazır" in response
    assert "core/x.py" in response


def test_dot_heal_command_requires_existing_file(monkeypatch):
    """Dot heal command requires existing file."""
    h = _build_handler(monkeypatch)
    handled, response = asyncio.run(h.handle(".heal /tmp/does-not-exist.log"))
    assert handled is True
    assert "bulunamadı" in response


def test_try_validate_file_paths_and_extensions(monkeypatch):
    """Try validate file paths and extensions."""
    memory = FakeMemory()
    memory.set_last_file("app.py")
    code = FakeCode(read_map={"app.py": (True, "print('ok')"), "data.toml": (True, "x=1")})
    h = _build_handler(monkeypatch, memory=memory, code=code)

    handled, response = h._try_validate_file("python doğrula", "python doğrula")
    assert (handled, response) == (True, "✓ valid py")

    handled, response = h._try_validate_file("dosya doğrula", "dosya doğrula data.toml")
    assert handled is True
    assert "desteklenmiyor" in response


def test_try_validate_file_read_fail_and_no_path(monkeypatch):
    """Try validate file read fail and no path."""
    h = _build_handler(monkeypatch, memory=FakeMemory(), code=FakeCode())

    handled, response = h._try_validate_file("sözdizimi", "sözdizimi")
    assert handled is True
    assert "dosya yolunu" in response

    handled, response = h._try_validate_file("dosya doğrula", "dosya doğrula x.py")
    assert handled is True
    assert response.startswith("✗ Dosya okunamadı")


def test_try_audit_health_gpu_timeout_and_exception(monkeypatch, caplog):
    """Try audit health gpu timeout and exception."""
    h = _build_handler(monkeypatch)

    async def raise_timeout(*_args, **_kwargs):
        raise TimeoutError()

    async def raise_exc(*_args, **_kwargs):
        raise RuntimeError("boom")

    h._run_blocking = raise_timeout
    assert asyncio.run(h._try_audit(".audit")) == (True, "⚠ Denetim işlemi zaman aşımına uğradı.")
    assert asyncio.run(h._try_health(".health")) == (True, "⚠ Sağlık raporu zaman aşımına uğradı.")
    assert asyncio.run(h._try_gpu_optimize(".gpu")) == (
        True,
        "⚠ GPU optimizasyonu zaman aşımına uğradı.",
    )

    h._run_blocking = raise_exc
    with caplog.at_level(logging.ERROR, logger="agent.auto_handle"):
        assert (asyncio.run(h._try_audit("audit")))[1].startswith("⚠ Denetim sırasında hata oluştu")
        assert (asyncio.run(h._try_health(".health")))[1].startswith("⚠ Sağlık raporu alınamadı")
        assert (asyncio.run(h._try_gpu_optimize(".gpu")))[1].startswith(
            "⚠ GPU optimizasyonu başarısız"
        )
    assert "AutoHandle audit command failed" in caplog.text
    assert "AutoHandle health report command failed" in caplog.text
    assert "AutoHandle GPU optimization command failed" in caplog.text


def test_try_health_gpu_requires_health_manager(monkeypatch):
    """Try health gpu requires health manager."""
    h = _build_handler(monkeypatch)
    h.health = None
    assert asyncio.run(h._try_health(".health")) == (
        True,
        "⚠ Sistem sağlık monitörü başlatılamadı.",
    )
    assert asyncio.run(h._try_gpu_optimize(".gpu")) == (
        True,
        "⚠ Sistem sağlık monitörü başlatılamadı.",
    )


def test_try_github_helpers_available_and_unavailable(monkeypatch):
    """Try github helpers available and unavailable."""
    h = _build_handler(monkeypatch, github=FakeGithub(available=False))
    assert h._try_github_commits("commit listele")[1].startswith("⚠ GitHub token")
    assert h._try_github_info("repo bilgi al")[1].startswith("⚠ GitHub token")
    assert h._try_github_list_files("depodaki dosyaları listele")[1].startswith("⚠ GitHub token")
    assert h._try_github_read("github dosya oku", "github dosya oku a.py")[1].startswith(
        "⚠ GitHub token"
    )

    h2 = _build_handler(monkeypatch, github=FakeGithub(available=True))
    assert h2._try_github_commits("5 commit listele") == (True, "commits:5")
    assert h2._try_github_info("repo info göster") == (True, "repo:info")
    assert h2._try_github_list_files("repo dosya listele") == (True, "files:")
    assert h2._try_github_read("github file oku", "github file oku src/a.py") == (
        True,
        "remote:src/a.py",
    )


def test_try_github_get_pr_detail_and_files(monkeypatch):
    """Try github get pr detail and files."""
    gh = FakeGithub(available=True)
    h = _build_handler(monkeypatch, github=gh)

    handled, response = asyncio.run(h._try_github_get_pr("pr #12 detay", "pr #12 detay"))
    assert (handled, response) == (True, "pr:12")
    assert gh.last_get_pr == 12

    handled, response = asyncio.run(
        h._try_github_get_pr("pull request #7 dosya", "pull request #7 dosya")
    )
    assert (handled, response) == (True, "pr_files:7")
    assert gh.last_get_pr_files == 7


def test_try_github_get_pr_unavailable_and_non_match(monkeypatch):
    """Try github get pr unavailable and non match."""
    h = _build_handler(monkeypatch, github=FakeGithub(available=False))
    assert asyncio.run(h._try_github_get_pr("pr #3", "pr #3")) == (
        True,
        "⚠ GitHub token ayarlanmamış.",
    )
    assert asyncio.run(h._try_github_get_pr("rastgele metin", "rastgele metin")) == (False, "")


def test_web_package_and_docs_handlers(monkeypatch):
    """Web package and docs handlers."""
    h = _build_handler(monkeypatch)

    assert asyncio.run(h._try_web_search("web'de ara python", "web'de ara python")) == (
        True,
        "search:python",
    )
    assert asyncio.run(h._try_fetch_url("url fetch", "url fetch https://example.com")) == (
        True,
        "url:https://example.com",
    )
    assert asyncio.run(
        h._try_search_docs("docs ara fastapi response", "docs ara fastapi response")
    ) == (
        True,
        "docs:fastapi:response",
    )
    assert asyncio.run(h._try_search_stackoverflow("so: asyncio gather", "so: asyncio gather")) == (
        True,
        "so:asyncio gather",
    )

    assert asyncio.run(h._try_pypi("pypi requests", "pypi requests")) == (True, "pypi:requests")
    assert asyncio.run(h._try_pypi("pypi requests 2.31.0", "pypi requests 2.31.0")) == (
        True,
        "pypi:requests:2.31.0",
    )
    assert asyncio.run(h._try_npm("npm react", "npm react")) == (True, "npm:react")
    assert asyncio.run(
        h._try_gh_releases("github releases tiangolo/fastapi", "github releases tiangolo/fastapi")
    ) == (
        True,
        "releases:tiangolo/fastapi",
    )


def test_docs_handlers_and_helper_extractors(monkeypatch):
    """Docs handlers and helper extractors."""
    h = _build_handler(monkeypatch)
    assert asyncio.run(
        h._try_docs_search("depoda ara indeksleme mode:vector", "depoda ara indeksleme mode:vector")
    ) == (
        True,
        "docs_search:indeksleme:vector",
    )
    assert h._try_docs_list("belge deposu listele", "belge deposu listele") == (True, "docs_list")
    assert asyncio.run(
        h._try_docs_add(
            "belge ekle https://example.com/docs",
            "belge ekle https://example.com/docs",
        )
    ) == (True, "docs_add:https://example.com/docs:")

    h.docs = AsyncDocs()
    assert asyncio.run(h._try_docs_search("rag ara vektör", "rag ara vektör")) == (
        True,
        "docs_search_async:vektör:auto",
    )

    assert h._extract_path('oku "a/b/c.py"') == "a/b/c.py"
    assert h._extract_path("oku src/app.json") == "src/app.json"
    assert h._extract_dir_path('listele "/tmp/proje"') == "/tmp/proje"
    assert h._extract_dir_path("listele ./agent") == "./agent"
    assert h._extract_dir_path("listele ./agent/main.py") is None
    assert h._extract_url("bak https://example.com/test?a=1") == "https://example.com/test?a=1"


def test_try_heal_local_usage_and_read_error_branches(monkeypatch, tmp_path):
    """Try heal local usage and read error branches."""
    h = _build_handler(monkeypatch)

    handled, response = asyncio.run(h._try_heal_local(".heal"))
    assert handled is True
    assert response == "⚠ Kullanım: .heal <log_dosyası>"

    bad_path = tmp_path / "bad.log"
    bad_path.write_text("x", encoding="utf-8")

    def _raise(*_args, **_kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(type(bad_path), "read_text", _raise)
    handled, response = asyncio.run(h._try_heal_local(f".heal {bad_path}"))
    assert handled is True
    assert response.startswith("⚠ Log dosyası okunamadı:")


def test_try_docs_search_invalid_result_shape(monkeypatch):
    """Try docs search invalid result shape."""
    h = _build_handler(monkeypatch)

    class InvalidDocs(FakeDocs):
        def search(self, query, _unused=None, mode="auto"):
            return {"query": query, "mode": mode}

    h.docs = InvalidDocs()
    assert asyncio.run(h._try_docs_search("depoda ara indeksleme", "depoda ara indeksleme")) == (
        True,
        "✗ Belge araması geçersiz yanıt döndürdü.",
    )


def test_handle_full_fallback_and_dot_routes(monkeypatch):
    """Handle full fallback and dot routes."""
    h = _build_handler(monkeypatch)
    assert asyncio.run(h.handle("anlamsız bir ifade")) == (False, "")

    h._try_clear_memory = AsyncMock(return_value=(True, "cleared"))
    assert asyncio.run(h._try_dot_command(".clear", ".clear")) == (True, "cleared")

    h._try_audit = AsyncMock(return_value=(True, "audit"))
    assert asyncio.run(h._try_dot_command(".audit", ".audit")) == (True, "audit")

    h._try_gpu_optimize = AsyncMock(return_value=(True, "gpu"))
    assert asyncio.run(h._try_dot_command(".gpu", ".gpu")) == (True, "gpu")

    assert asyncio.run(h._try_dot_command(".unknown", ".unknown")) == (False, "")


def test_run_blocking_executes_sync_function(monkeypatch):
    """Run blocking executes sync function."""
    h = _build_handler(monkeypatch)
    h.command_timeout = 1
    result = asyncio.run(h._run_blocking(lambda x: x + 1, 4))
    assert result == 5


def test_security_status_pattern(monkeypatch):
    """Security status pattern."""
    h = _build_handler(monkeypatch)
    assert h._try_security_status("openclaw erişim seviyesi nedir") == (True, "security")
    assert h._try_security_status("genel güvenlik analizi yap") == (False, "")


def test_handle_short_circuit_routes_cover_each_return_branch(monkeypatch):
    """Handle short circuit routes cover each return branch."""
    h = _build_handler(monkeypatch)

    async def _false_async(*_args, **_kwargs):
        return False, ""

    def _false_sync(*_args, **_kwargs):
        return False, ""

    # handle içindeki sıralı tüm kontrol noktalarını tek tek short-circuit ile doğrula.
    ordered_steps = [
        "_try_clear_memory",
        "_try_list_directory",
        "_try_read_file",
        "_try_audit",
        "_try_health",
        "_try_gpu_optimize",
        "_try_validate_file",
        "_try_github_commits",
        "_try_github_info",
        "_try_github_list_files",
        "_try_github_read",
        "_try_github_list_prs",
        "_try_github_get_pr",
        "_try_security_status",
        "_try_web_search",
        "_try_fetch_url",
        "_try_search_docs",
        "_try_search_stackoverflow",
        "_try_pypi",
        "_try_npm",
        "_try_gh_releases",
        "_try_docs_search",
        "_try_docs_add",
        "_try_docs_list",
    ]

    async_steps = {
        "_try_clear_memory",
        "_try_audit",
        "_try_health",
        "_try_gpu_optimize",
        "_try_github_get_pr",
        "_try_web_search",
        "_try_fetch_url",
        "_try_search_docs",
        "_try_search_stackoverflow",
        "_try_pypi",
        "_try_npm",
        "_try_gh_releases",
        "_try_docs_search",
        "_try_docs_add",
    }

    for target in ordered_steps:
        for step in ordered_steps:
            if step in async_steps:
                setattr(h, step, _false_async)
            else:
                setattr(h, step, _false_sync)

        if target in async_steps:

            async def _true_async(*_args, _target=target, **_kwargs):
                return True, f"ok:{_target}"

            setattr(h, target, _true_async)
        else:

            def _true_sync(*_args, _target=target, **_kwargs):
                return True, f"ok:{_target}"

            setattr(h, target, _true_sync)

        handled, response = asyncio.run(h.handle("tek adım"))
        assert handled is True
        assert response == f"ok:{target}"


def test_remaining_auto_handle_branches(monkeypatch):
    """Remaining auto handle branches."""
    h = _build_handler(monkeypatch)

    # _try_dot_command: regex eşleşip tanınmayan komut dalı
    import re

    h._DOT_CMD_RE = re.compile(r"^\s*\.(\w+)\b", re.IGNORECASE)
    assert asyncio.run(h._try_dot_command(".noop", ".noop")) == (False, "")

    # _try_read_file: read_file başarısız dalı
    h.code = FakeCode(read_map={"nope.py": (False, "not found")})
    handled, response = h._try_read_file("dosyayı oku", "dosyayı oku nope.py")
    assert handled is True
    assert response == "✗ not found"

    # _try_audit/_try_health/_try_gpu_optimize: başarılı dal
    assert asyncio.run(h._try_audit("audit")) == (True, "audit-ok")
    assert asyncio.run(h._try_health(".health")) == (True, "health-ok")
    assert asyncio.run(h._try_gpu_optimize(".gpu")) == (True, "gpu-ok")

    # _try_validate_file: json doğrulama dalı
    h.memory.set_last_file("data.json")
    h.code = FakeCode(read_map={"data.json": (True, '{"ok": true}')})
    assert h._try_validate_file("dosya doğrula", "dosya doğrula") == (True, "✓ valid json")

    # _try_github_read: path eksik uyarısı
    h.github = FakeGithub(available=True)
    assert h._try_github_read("github dosya oku", "github dosya oku") == (
        True,
        "⚠ Okunacak GitHub dosya yolunu belirtin.",
    )

    # _try_github_list_prs: unavailable + all + open dalları
    h.github = FakeGithub(available=False)
    assert h._try_github_list_prs("pr listele", "pr listele") == (
        True,
        "⚠ GitHub token ayarlanmamış.",
    )

    h.github = FakeGithub(available=True)
    assert h._try_github_list_prs("tüm pr listele", "tüm pr listele") == (True, "prs:all:10")
    assert h.github.last_list_pr_args == ("all", 10)
    assert h._try_github_list_prs("pr listele", "pr listele") == (True, "prs:open:10")
    assert h.github.last_list_pr_args == ("open", 10)

    # _try_github_get_pr: dosya alt-komutunda unavailable dalı
    h.github = FakeGithub(available=False)
    assert asyncio.run(h._try_github_get_pr("pr #8 dosya", "pr #8 dosya")) == (
        True,
        "⚠ GitHub token ayarlanmamış.",
    )

    # _try_clear_memory: sync clear dalı (await edilmemeli)
    sync_memory = FakeMemory()
    h.memory = sync_memory
    assert asyncio.run(h._try_clear_memory(".clear")) == (True, "✓ Konuşma belleği temizlendi.")
    assert sync_memory.cleared is True

    # _try_web_search: boş sorgu dalı
    assert asyncio.run(h._try_web_search("google:   ", "google:   ")) == (
        True,
        "⚠ Arama sorgusu belirtilmedi.",
    )

    # _try_fetch_url: URL bulunamadı dalı
    assert asyncio.run(h._try_fetch_url("url fetch", "url fetch")) == (
        True,
        "⚠ Geçerli bir URL bulunamadı.",
    )


def test_auto_handle_try_web_search_isolated(monkeypatch):
    """Auto handle try web search isolated."""
    h = _build_handler(monkeypatch)
    handled, out = asyncio.run(h._try_web_search("web'de ara sidar", "web'de ara sidar"))

    assert handled is True
    assert out == "search:sidar"

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def _load_auto_handle_class():
    """Load AutoHandle with temporary import stubs, without polluting global sys.modules."""
    stub_keys = {
        "managers.code_manager": types.ModuleType("managers.code_manager"),
        "managers.system_health": types.ModuleType("managers.system_health"),
        "managers.github_manager": types.ModuleType("managers.github_manager"),
        "managers.web_search": types.ModuleType("managers.web_search"),
        "managers.package_info": types.ModuleType("managers.package_info"),
        "core.memory": types.ModuleType("core.memory"),
        "core.rag": types.ModuleType("core.rag"),
    }
    stub_keys["managers.code_manager"].CodeManager = object
    stub_keys["managers.system_health"].SystemHealthManager = object
    stub_keys["managers.github_manager"].GitHubManager = object
    stub_keys["managers.web_search"].WebSearchManager = object
    stub_keys["managers.package_info"].PackageInfoManager = object
    stub_keys["core.memory"].ConversationMemory = object
    stub_keys["core.rag"].DocumentStore = object

    saved = {k: sys.modules.get(k) for k in stub_keys}
    try:
        for k, v in stub_keys.items():
            sys.modules[k] = v
        spec = importlib.util.spec_from_file_location("auto_handle_under_test", Path("agent/auto_handle.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod.AutoHandle
    finally:
        for k, old in saved.items():
            if old is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = old


AutoHandle = _load_auto_handle_class()


class _Code:
    def __init__(self):
        self.security = SimpleNamespace(status_report=lambda: "sec-status")

    def list_directory(self, path):
        return True, f"LIST:{path}"

    def read_file(self, path):
        if path == "bad.txt":
            return False, "read err"
        if path.endswith(".py"):
            return True, "x = 1\n"
        if path.endswith(".json"):
            return True, '{"a": 1}'
        return True, "hello"

    def validate_python_syntax(self, content):
        return True, "py-ok"

    def validate_json(self, content):
        return False, "json-bad"

    def audit_project(self, root):
        return f"AUDIT:{root}"


class _Health:
    def full_report(self):
        return "health-ok"

    def optimize_gpu_memory(self):
        return "gpu-ok"


class _Github:
    def __init__(self, available=True):
        self.available = available

    def is_available(self):
        return self.available

    def list_commits(self, n=10):
        return True, f"commits:{n}"

    def get_repo_info(self):
        return True, "repo-info"

    def list_files(self, path):
        return True, "files"

    def read_remote_file(self, path):
        return (path != "missing.py"), f"remote:{path}"

    def list_pull_requests(self, state="open", limit=10):
        return True, f"prs:{state}:{limit}"

    def get_pr_files(self, number):
        return True, f"pr-files:{number}"

    def get_pull_request(self, number):
        return True, f"pr:{number}"


class _Memory:
    def __init__(self):
        self._last = None
        self.cleared = 0

    def clear(self):
        self.cleared += 1

    def get_last_file(self):
        return self._last

    def set_last_file(self, path):
        self._last = path


class _Web:
    async def search(self, q):
        return True, f"web:{q}"

    async def fetch_url(self, url):
        return True, f"fetch:{url}"

    async def search_docs(self, lib, topic):
        return True, f"docs:{lib}:{topic}"

    async def search_stackoverflow(self, q):
        return True, f"so:{q}"


class _Pkg:
    async def pypi_compare(self, package, version):
        return True, f"cmp:{package}:{version}"

    async def pypi_info(self, package):
        return True, f"pypi:{package}"

    async def npm_info(self, package):
        return True, f"npm:{package}"

    async def github_releases(self, repo):
        return True, f"rel:{repo}"


class _Docs:
    def search(self, query, *_args):
        return True, f"dsearch:{query}"

    def list_documents(self):
        return "dlist"

    async def add_document_from_url(self, url, title=""):
        return True, f"dadd:{url}:{title}"


def _make_auto(*, github_available=True, health=True):
    return AutoHandle(
        code=_Code(),
        health=_Health() if health else None,
        github=_Github(available=github_available),
        memory=_Memory(),
        web=_Web(),
        pkg=_Pkg(),
        docs=_Docs(),
        cfg=SimpleNamespace(AUTO_HANDLE_TIMEOUT=1),
    )


def test_handle_dot_commands_and_multi_step_gate():
    auto = _make_auto()

    handled, msg = asyncio.run(auto.handle(".clear"))
    assert handled is True
    assert "temizlendi" in msg

    handled, msg = asyncio.run(auto.handle("önce dizin listele sonra dosya oku"))
    assert handled is False
    assert msg == ""


def test_health_and_gpu_timeout_exception_and_none_paths(monkeypatch):
    auto = _make_auto(health=False)
    handled, msg = asyncio.run(auto._try_health("sistem sağlık raporu"))
    assert handled is True and "başlatılamadı" in msg

    auto2 = _make_auto()

    async def raise_timeout(*_args, **_kwargs):
        raise asyncio.TimeoutError

    monkeypatch.setattr(auto2, "_run_blocking", raise_timeout)
    handled, msg = asyncio.run(auto2._try_health("sistem sağlık raporu"))
    assert handled is True and "zaman aşımı" in msg

    async def raise_exc(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(auto2, "_run_blocking", raise_exc)
    handled, msg = asyncio.run(auto2._try_gpu_optimize("gpu optimize et"))
    assert handled is True and "başarısız" in msg


def test_validate_file_paths_and_formats():
    auto = _make_auto()

    handled, msg = auto._try_validate_file("sözdizimi doğrula", "sözdizimi doğrula")
    assert handled is True and "belirtin" in msg

    auto.memory.set_last_file("bad.txt")
    handled, msg = auto._try_validate_file("sözdizimi doğrula", "sözdizimi doğrula")
    assert handled is True and "Dosya okunamadı" in msg

    handled, msg = auto._try_validate_file("sözdizimi doğrula", "app.py sözdizimi doğrula")
    assert handled is True and msg.startswith("✓")

    handled, msg = auto._try_validate_file("sözdizimi doğrula", "data.json sözdizimi doğrula")
    assert handled is True and msg.startswith("✗")

    handled, msg = auto._try_validate_file("sözdizimi doğrula", "readme.md sözdizimi doğrula")
    assert handled is True and "desteklenmiyor" in msg


def test_github_variants_unavailable_and_pr_modes():
    auto = _make_auto(github_available=False)
    handled, msg = auto._try_github_commits("github commitleri listele")
    assert handled is True and "token" in msg

    auto2 = _make_auto(github_available=True)
    handled, msg = auto2._try_github_commits("5 commit listele")
    assert handled is True and msg == "commits:5"

    handled, msg = auto2._try_github_list_prs("kapalı pr listele", "kapalı pr listele")
    assert handled is True and msg == "prs:closed:10"

    handled, msg = auto2._try_github_list_prs("tüm pull requestler 7 pr", "")
    assert handled is True and msg == "prs:all:7"

    handled, msg = asyncio.run(auto2._try_github_get_pr("pr #12 dosyaları", ""))
    assert handled is True and msg == "pr-files:12"

    handled, msg = asyncio.run(auto2._try_github_get_pr("#8 pull request", ""))
    assert handled is True and msg == "pr:8"


def test_web_pkg_docs_and_helpers_paths():
    auto = _make_auto()

    assert asyncio.run(auto._try_web_search("webde ara pytest", "")) == (True, "web:pytest")
    assert asyncio.run(auto._try_fetch_url("url oku", "url oku https://x.dev")) == (True, "fetch:https://x.dev")
    assert asyncio.run(auto._try_search_docs("docs ara fastapi routing", "")) == (True, "docs:fastapi:routing")
    assert asyncio.run(auto._try_search_stackoverflow("stackoverflow: asyncio wait_for", "")) == (True, "so:asyncio wait_for")

    assert asyncio.run(auto._try_pypi("pypi requests 2.31.0", "")) == (True, "cmp:requests:2.31.0")
    assert asyncio.run(auto._try_npm("npm react", "")) == (True, "npm:react")
    assert asyncio.run(auto._try_gh_releases("github releases tiangolo/fastapi", "")) == (True, "rel:tiangolo/fastapi")

    assert asyncio.run(auto._try_docs_search("depoda ara: vector db", "")) == (True, "dsearch:vector db")
    assert auto._try_docs_list("belge deposu listele", "") == (True, "dlist")
    assert asyncio.run(auto._try_docs_add("belge ekle", 'belge ekle https://a.b "Baslik"')) == (True, "dadd:https://a.b:Baslik")

    assert auto._extract_path('"a/b/config.py"') == "a/b/config.py"
    assert auto._extract_dir_path('klasör listele "src/utils"') == "src/utils"
    assert auto._extract_url("bak https://example.org/path?a=1") == "https://example.org/path?a=1"

def test_dot_command_and_github_info_list_read_variants():
    auto = _make_auto(github_available=True)

    handled, msg = asyncio.run(auto._try_dot_command(".health", ".health"))
    assert handled is True and "health" in msg

    handled, msg = asyncio.run(auto._try_dot_command(".audit", ".audit"))
    assert handled is True and "audit" in msg.lower()

    handled, msg = asyncio.run(auto._try_dot_command(".clear", ".clear"))
    assert handled is True and "temizlendi" in msg

    handled, msg = auto._try_github_info("repo bilgi göster")
    assert handled is True and msg == "repo-info"

    handled, msg = auto._try_github_list_files("repodaki dosyaları listele")
    assert handled is True and msg == "files"

    handled, msg = auto._try_github_read("github dosya oku", 'github dosya oku "README.md"')
    assert handled is True and msg == "remote:README.md"


def test_handle_multistep_and_unknown_dot_command_paths():
    auto = _make_auto(github_available=True)
    handled, msg = asyncio.run(auto.handle("önce dosyaları listele sonra oku"))
    assert handled is False and msg == ""

    handled2, msg2 = asyncio.run(auto._try_dot_command(".unknown", ".unknown"))
    assert handled2 is False and msg2 == ""


def test_auto_handle_git_log_git_branch_and_todo_phrases():
    auto = _make_auto(github_available=True)

    handled, msg = auto._try_github_commits("git log son commitleri göster")
    assert handled is True and "commits" in msg

    handled, msg = auto._try_github_list_files("github repo branch dosya listesini göster")
    assert handled is True and msg == "files"

    handled2, msg2 = asyncio.run(auto.handle("yapılacaklar"))
    assert handled2 is False and msg2 == ""


def test_auto_handle_extra_regex_phrases_do_not_crash():
    auto = _make_auto(github_available=True)

    phrases = [
        "git status",
        "git branch",
        "todo list",
        "yapılacaklar",
        "internette ara python",
        "repo info",
    ]

    for phrase in phrases:
        handled, msg = asyncio.run(auto.handle(phrase))
        assert isinstance(handled, bool)
        assert isinstance(msg, str)

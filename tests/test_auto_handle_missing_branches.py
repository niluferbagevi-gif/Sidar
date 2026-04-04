import asyncio
import sys
import types
from types import SimpleNamespace

for _mod_name, _class_name in [
    ("managers.web_search", "WebSearchManager"),
    ("managers.package_info", "PackageInfoManager"),
    ("core.rag", "DocumentStore"),
    ("core.memory", "ConversationMemory"),
]:
    _mod = types.ModuleType(_mod_name)
    _mod.__dict__[_class_name] = type(_class_name, (), {})
    sys.modules.setdefault(_mod_name, _mod)

from agent.auto_handle import AutoHandle


class CodeStub:
    def __init__(self):
        self.security = SimpleNamespace(status_report=lambda: "security-ok")

    def list_directory(self, path):
        return True, f"list:{path}"

    def read_file(self, path):
        if path == "missing.py":
            return False, "missing"
        if path == "big.py":
            return True, "\n".join([f"line{i}" for i in range(90)])
        return True, '{"a":1}' if path.endswith(".json") else "print('ok')"

    def validate_python_syntax(self, content):
        return True, f"py:{len(content)}"

    def validate_json(self, content):
        return False, f"json:{len(content)}"

    def audit_project(self, _path):
        return "audit-ok"


class GitHubStub:
    def __init__(self, available=True):
        self.available = available

    def is_available(self):
        return self.available

    def list_commits(self, n=10):
        return True, f"commits:{n}"

    def get_repo_info(self):
        return True, "repo-info"

    def list_files(self, _path):
        return True, "repo-files"

    def read_remote_file(self, path):
        return (path != "bad.py"), f"remote:{path}"

    def list_pull_requests(self, state="open", limit=10):
        return True, f"prs:{state}:{limit}"

    def get_pr_files(self, number):
        return True, f"pr-files:{number}"

    def get_pull_request(self, number):
        return True, f"pr:{number}"


class WebStub:
    async def search(self, query):
        return True, f"web:{query}"

    async def fetch_url(self, url):
        return True, f"url:{url}"

    async def search_docs(self, lib, topic):
        return True, f"docs:{lib}:{topic}"

    async def search_stackoverflow(self, query):
        return True, f"so:{query}"


class PkgStub:
    async def pypi_info(self, package):
        return True, f"pypi:{package}"

    async def pypi_compare(self, package, version):
        return True, f"cmp:{package}:{version}"

    async def npm_info(self, package):
        return True, f"npm:{package}"

    async def github_releases(self, repo):
        return True, f"rel:{repo}"


class DocsStub:
    def __init__(self):
        self.last = None

    def search(self, query, _filters, mode):
        return True, f"docs-search:{mode}:{query}"

    def list_documents(self):
        return "docs-list"

    async def add_document_from_url(self, url, title=""):
        self.last = (url, title)
        return True, f"added:{url}:{title}"


def build_handler():
    mem = SimpleNamespace(
        get_last_file=lambda: None,
        set_last_file=lambda _path: None,
        clear=lambda: None,
    )
    return AutoHandle(
        code=CodeStub(),
        health=SimpleNamespace(full_report=lambda: "health-ok", optimize_gpu_memory=lambda: "gpu-ok"),
        github=GitHubStub(),
        memory=mem,
        web=WebStub(),
        pkg=PkgStub(),
        docs=DocsStub(),
        cfg=SimpleNamespace(AUTO_HANDLE_TIMEOUT=1),
    )


def test_run_blocking_returns_function_result():
    h = build_handler()
    assert asyncio.run(h._run_blocking(lambda x: f"ok:{x}", "v")) == "ok:v"


def test_try_read_file_error_and_preview_suffix_paths():
    h = build_handler()
    ok, msg = h._try_read_file("dosyayı oku", "dosyayı oku missing.py")
    assert ok is True and msg.startswith("✗")

    h.memory = SimpleNamespace(get_last_file=lambda: "big.py", set_last_file=lambda _p: None)
    ok, msg = h._try_read_file("dosya içeriğini getir", "dosya içeriğini getir")
    assert ok is True and "satır daha" in msg


def test_health_and_gpu_not_available_paths():
    h = build_handler()
    h.health = None
    assert asyncio.run(h._try_health("sistem sağlık rapor"))[1].startswith("⚠ Sistem sağlık")
    assert asyncio.run(h._try_gpu_optimize("gpu clear"))[1].startswith("⚠ Sistem sağlık")


def test_validate_file_read_error_and_unsupported_extension():
    h = build_handler()
    ok, msg = h._try_validate_file("syntax doğrula", "syntax doğrula missing.py")
    assert ok is True and "Dosya okunamadı" in msg

    ok, msg = h._try_validate_file("dosya doğrula", "dosya doğrula notes.ini")
    assert ok is True and "desteklenmiyor" in msg


def test_github_handlers_negative_and_positive_branches():
    h = build_handler()
    h.github = GitHubStub(available=False)
    assert h._try_github_commits("son commitleri listele")[1].startswith("⚠ GitHub token")
    assert h._try_github_info("github bilgi ver")[1].startswith("⚠ GitHub token")
    assert h._try_github_list_files("repo dosya listele")[1].startswith("⚠ GitHub token")
    assert h._try_github_read("github dosya oku", "github dosya oku x.py")[1].startswith("⚠ GitHub token")
    assert h._try_github_list_prs("pr listele", "pr listele")[1].startswith("⚠ GitHub token")
    assert asyncio.run(h._try_github_get_pr("pr 2", "pr 2"))[1].startswith("⚠ GitHub token")

    h.github = GitHubStub(available=True)
    assert h._try_github_commits("7 commit listele") == (True, "commits:7")
    assert h._try_github_info("repo özet") == (True, "repo-info")
    assert h._try_github_list_files("depo içerik getir") == (True, "repo-files")
    assert h._try_github_read("github file oku", "github file oku bad.py") == (True, "✗ remote:bad.py")
    assert h._try_github_list_prs("tüm pr listele", "tüm pr listele") == (True, "prs:all:10")
    assert h._try_github_list_prs("açık pr listele", "açık pr listele") == (True, "prs:open:10")
    assert asyncio.run(h._try_github_get_pr("3 numaralı pr", "3 numaralı pr")) == (True, "pr:3")


def test_security_and_web_negative_paths():
    h = build_handler()
    assert h._try_security_status("yetki seviyesi nedir") == (True, "security-ok")
    assert h._try_security_status("genel analiz") == (False, "")

    assert asyncio.run(h._try_web_search("google:   ", "google:   ")) == (True, "⚠ Arama sorgusu belirtilmedi.")
    assert asyncio.run(h._try_fetch_url("url getir", "url getir ama link yok")) == (True, "⚠ Geçerli bir URL bulunamadı.")
    assert asyncio.run(h._try_search_docs("resmi docs fastapi", "resmi docs fastapi")) == (True, "docs:fastapi:")
    assert asyncio.run(h._try_search_stackoverflow("so: asyncio wait_for", "so: asyncio wait_for")) == (
        True,
        "so:asyncio wait_for",
    )


def test_package_and_docs_extra_branches():
    h = build_handler()
    assert asyncio.run(h._try_pypi("pip show httpx", "pip show httpx")) == (True, "pypi:httpx")
    assert asyncio.run(h._try_npm("node paketi @types/node", "node paketi @types/node")) == (
        True,
        "npm:@types/node",
    )
    assert asyncio.run(h._try_gh_releases("gh releases org/repo", "gh releases org/repo")) == (
        True,
        "rel:org/repo",
    )

    assert asyncio.run(h._try_docs_search("depoda ara vektör", "depoda ara vektör")) == (
        True,
        "docs-search:auto:vektör",
    )
    assert h._try_docs_list("rag listele", "rag listele") == (True, "docs-list")
    assert asyncio.run(h._try_docs_add("belge ekle", 'belge ekle https://a.b "Başlık"')) == (
        True,
        "added:https://a.b:Başlık",
    )
    assert asyncio.run(h._try_docs_add("belgeye ekle", 'bunu belgeye ekle https://c.d "Alt"')) == (
        True,
        "added:https://c.d:Alt",
    )


def test_extract_dir_path_variants_and_try_defaults():
    h = build_handler()
    assert h._extract_dir_path('klasör listele "src/utils"') == "src/utils"
    assert h._extract_dir_path("dizini göster ./agent/core") == "./agent/core"
    assert h._extract_dir_path("dizini göster /tmp/file.txt") is None

    assert h._try_list_directory("testleri çalıştır", "testleri çalıştır") == (False, "")
    assert h._try_docs_list("belgeleri getir", "belgeleri getir") == (False, "")
    assert asyncio.run(h._try_docs_add("normal komut", "normal komut")) == (False, "")


def test_handle_falls_back_when_nothing_matches():
    h = build_handler()
    assert asyncio.run(h.handle("merhaba nasılsın")) == (False, "")


def test_handle_short_circuit_exits_each_stage(monkeypatch):
    h = build_handler()

    async def _false_async(*_args, **_kwargs):
        return False, ""

    def _false_sync(*_args, **_kwargs):
        return False, ""

    # Multi-step regex by-pass etmek için, tüm alt çağrıları false döndürecek hale getir
    monkeypatch.setattr(h, "_try_dot_command", _false_async)
    monkeypatch.setattr(h, "_try_clear_memory", _false_async)
    monkeypatch.setattr(h, "_try_list_directory", _false_sync)
    monkeypatch.setattr(h, "_try_read_file", _false_sync)
    monkeypatch.setattr(h, "_try_audit", _false_async)
    monkeypatch.setattr(h, "_try_health", _false_async)
    monkeypatch.setattr(h, "_try_gpu_optimize", _false_async)
    monkeypatch.setattr(h, "_try_validate_file", _false_sync)
    monkeypatch.setattr(h, "_try_github_commits", _false_sync)
    monkeypatch.setattr(h, "_try_github_info", _false_sync)
    monkeypatch.setattr(h, "_try_github_list_files", _false_sync)
    monkeypatch.setattr(h, "_try_github_read", _false_sync)
    monkeypatch.setattr(h, "_try_github_list_prs", _false_sync)
    monkeypatch.setattr(h, "_try_github_get_pr", _false_async)
    monkeypatch.setattr(h, "_try_security_status", _false_sync)
    monkeypatch.setattr(h, "_try_web_search", _false_async)
    monkeypatch.setattr(h, "_try_fetch_url", _false_async)
    monkeypatch.setattr(h, "_try_search_docs", _false_async)
    monkeypatch.setattr(h, "_try_search_stackoverflow", _false_async)
    monkeypatch.setattr(h, "_try_pypi", _false_async)
    monkeypatch.setattr(h, "_try_npm", _false_async)
    monkeypatch.setattr(h, "_try_gh_releases", _false_async)
    monkeypatch.setattr(h, "_try_docs_search", _false_async)
    monkeypatch.setattr(h, "_try_docs_add", _false_async)
    monkeypatch.setattr(h, "_try_docs_list", _false_sync)

    stages = [
        ("_try_list_directory", "list"),
        ("_try_read_file", "read"),
        ("_try_audit", "audit"),
        ("_try_health", "health"),
        ("_try_gpu_optimize", "gpu"),
        ("_try_validate_file", "validate"),
        ("_try_github_commits", "commits"),
        ("_try_github_info", "info"),
        ("_try_github_list_files", "files"),
        ("_try_github_read", "gh-read"),
        ("_try_github_list_prs", "prs"),
        ("_try_github_get_pr", "pr"),
        ("_try_security_status", "security"),
        ("_try_web_search", "web"),
        ("_try_fetch_url", "url"),
        ("_try_search_docs", "docs"),
        ("_try_search_stackoverflow", "so"),
        ("_try_pypi", "pypi"),
        ("_try_npm", "npm"),
        ("_try_gh_releases", "rel"),
        ("_try_docs_search", "rag-search"),
        ("_try_docs_add", "rag-add"),
        ("_try_docs_list", "rag-list"),
    ]

    for name, token in stages:
        if name in {
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
        }:
            async def _hit(*_args, _token=token, **_kwargs):
                return True, _token
        else:
            def _hit(*_args, _token=token, **_kwargs):
                return True, _token

        monkeypatch.setattr(h, name, _hit)
        assert asyncio.run(h.handle("tek adım komut")) == (True, token)
        monkeypatch.setattr(h, name, _false_async if name.startswith("_try_") and name in {
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
        } else _false_sync)


def test_additional_specific_missing_paths(monkeypatch):
    h = build_handler()

    # _try_dot_command: regex eşleşse de tanınmayan komut dalı
    original_re = h._DOT_CMD_RE
    h._DOT_CMD_RE = __import__("re").compile(r"^\.(status|unknown)\b", __import__("re").IGNORECASE)
    assert asyncio.run(h._try_dot_command(".unknown", ".unknown")) == (False, "")
    h._DOT_CMD_RE = original_re

    # _try_read_file: path yoksa uyarı
    h.memory = SimpleNamespace(get_last_file=lambda: None, set_last_file=lambda _p: None)
    assert asyncio.run(asyncio.to_thread(h._try_read_file, "dosya içeriğini göster", "dosya içeriğini göster")) == (
        True,
        "⚠ Hangi dosyayı okumamı istiyorsunuz? Lütfen dosya yolunu belirtin.",
    )

    # _try_audit: başarılı yol
    monkeypatch.setattr(h, "_run_blocking", lambda *_args, **_kwargs: asyncio.sleep(0, result="audit-ok"))
    assert asyncio.run(h._try_audit(".audit")) == (True, "audit-ok")

    # _try_health: başarı, timeout, exception
    monkeypatch.setattr(h, "_run_blocking", lambda *_args, **_kwargs: asyncio.sleep(0, result="health-ok"))
    assert asyncio.run(h._try_health(".status")) == (True, "health-ok")

    async def _timeout(*_args, **_kwargs):
        raise asyncio.TimeoutError()

    async def _err(*_args, **_kwargs):
        raise RuntimeError("hf")

    monkeypatch.setattr(h, "_run_blocking", _timeout)
    assert asyncio.run(h._try_health(".health")) == (True, "⚠ Sağlık raporu zaman aşımına uğradı.")
    monkeypatch.setattr(h, "_run_blocking", _err)
    assert asyncio.run(h._try_health("sistem sağlık rapor")) == (True, "⚠ Sağlık raporu alınamadı: hf")

    # _try_gpu_optimize: başarı, timeout, exception
    monkeypatch.setattr(h, "_run_blocking", lambda *_args, **_kwargs: asyncio.sleep(0, result="gpu-ok"))
    assert asyncio.run(h._try_gpu_optimize(".gpu")) == (True, "gpu-ok")
    monkeypatch.setattr(h, "_run_blocking", _timeout)
    assert asyncio.run(h._try_gpu_optimize("gpu clear")) == (True, "⚠ GPU optimizasyonu zaman aşımına uğradı.")
    monkeypatch.setattr(h, "_run_blocking", _err)
    assert asyncio.run(h._try_gpu_optimize("vram temizle")) == (True, "⚠ GPU optimizasyonu başarısız: hf")

    # _try_validate_file: .py başarılı dal
    h.memory = SimpleNamespace(get_last_file=lambda: None, set_last_file=lambda _p: None)
    assert h._try_validate_file("python doğrula", "python doğrula main.py") == (True, "✓ py:11")

    # _try_github_read: path yok dalı
    assert h._try_github_read("github dosya oku", "github dosya oku") == (
        True,
        "⚠ Okunacak GitHub dosya yolunu belirtin.",
    )

    # _try_clear_memory: non-awaitable clear dalı
    sync_mem = SimpleNamespace(called=False)

    def _clear():
        sync_mem.called = True
        return None

    sync_mem.clear = _clear
    h.memory = sync_mem
    assert asyncio.run(h._try_clear_memory(".clear")) == (True, "✓ Konuşma belleği temizlendi.")
    assert sync_mem.called is True

    # _try_docs_search: awaitable result_obj dalı
    async def _search_async(query, _filters, mode):
        return True, f"async:{mode}:{query}"

    h.docs = SimpleNamespace(search=_search_async)
    assert asyncio.run(h._try_docs_search("depoda ara q mode:vector", "depoda ara q mode:vector")) == (
        True,
        "async:vector:q",
    )

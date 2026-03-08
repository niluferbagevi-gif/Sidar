import asyncio
import importlib.util
import json
import sys
import threading
import types
import pytest
from pathlib import Path
from types import SimpleNamespace


def _load_sidar_agent_module():
    stubs = {
        "pydantic": types.ModuleType("pydantic"),
        "config": types.ModuleType("config"),
        "core.memory": types.ModuleType("core.memory"),
        "core.llm_client": types.ModuleType("core.llm_client"),
        "core.rag": types.ModuleType("core.rag"),
        "managers.code_manager": types.ModuleType("managers.code_manager"),
        "managers.system_health": types.ModuleType("managers.system_health"),
        "managers.github_manager": types.ModuleType("managers.github_manager"),
        "managers.security": types.ModuleType("managers.security"),
        "managers.web_search": types.ModuleType("managers.web_search"),
        "managers.package_info": types.ModuleType("managers.package_info"),
        "managers.todo_manager": types.ModuleType("managers.todo_manager"),
        "agent.auto_handle": types.ModuleType("agent.auto_handle"),
        "agent.definitions": types.ModuleType("agent.definitions"),
        "agent.tooling": types.ModuleType("agent.tooling"),
    }

    class ValidationError(Exception):
        pass

    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

        @classmethod
        def model_validate(cls, data):
            for key in ("thought", "tool", "argument"):
                if key not in data:
                    raise ValidationError(key)
            return cls(**data)

        @classmethod
        def model_validate_json(cls, raw):
            data = json.loads(raw)
            for key in ("thought", "tool", "argument"):
                if key not in data:
                    raise ValidationError(key)
            return cls(**data)

    def Field(*args, **kwargs):
        return None

    stubs["pydantic"].BaseModel = BaseModel
    stubs["pydantic"].Field = Field
    stubs["pydantic"].ValidationError = ValidationError

    class _Cfg:
        pass

    stubs["config"].Config = _Cfg

    for mod_name, cls_name in (
        ("core.memory", "ConversationMemory"),
        ("core.llm_client", "LLMClient"),
        ("core.rag", "DocumentStore"),
        ("managers.code_manager", "CodeManager"),
        ("managers.system_health", "SystemHealthManager"),
        ("managers.github_manager", "GitHubManager"),
        ("managers.security", "SecurityManager"),
        ("managers.web_search", "WebSearchManager"),
        ("managers.package_info", "PackageInfoManager"),
        ("managers.todo_manager", "TodoManager"),
        ("agent.auto_handle", "AutoHandle"),
    ):
        setattr(stubs[mod_name], cls_name, object)

    stubs["agent.definitions"].SIDAR_SYSTEM_PROMPT = "sys"

    class _Schema:
        pass

    for n in (
        "GithubCloseIssueSchema",
        "GithubCommentIssueSchema",
        "GithubCreateBranchSchema",
        "GithubCreateIssueSchema",
        "GithubCreatePRSchema",
        "GithubListFilesSchema",
        "GithubListIssuesSchema",
        "GithubListPRsSchema",
        "GithubPRDiffSchema",
        "GithubWriteSchema",
        "PatchFileSchema",
        "WriteFileSchema",
        "ScanProjectTodosSchema",
    ):
        setattr(stubs["agent.tooling"], n, _Schema)

    stubs["agent.tooling"].build_tool_dispatch = lambda _agent: {}
    stubs["agent.tooling"].parse_tool_argument = lambda _tool, arg: arg

    saved = {k: sys.modules.get(k) for k in stubs}
    try:
        for k, v in stubs.items():
            sys.modules[k] = v

        spec = importlib.util.spec_from_file_location("sidar_agent_under_test", Path("agent/sidar_agent.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, old in saved.items():
            if old is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = old


SA_MOD = _load_sidar_agent_module()
SidarAgent = SA_MOD.SidarAgent


async def _collect(aiter):
    return [x async for x in aiter]


def _make_agent_for_runtime():
    a = SidarAgent.__new__(SidarAgent)
    a.cfg = SimpleNamespace(AI_PROVIDER="ollama", CODING_MODEL="m", ACCESS_LEVEL="sandbox")
    a._lock = None
    a.tracer = None
    a._tools = {}

    class _Mem:
        def __init__(self):
            self.items = []

        def add(self, role, text):
            self.items.append((role, text))

        def needs_summarization(self):
            return False

        def __len__(self):
            return len(self.items)

        def clear(self):
            self.items.clear()

    a.memory = _Mem()
    a.auto = SimpleNamespace(handle=None)
    a.github = SimpleNamespace(status=lambda: "gh")
    a.web = SimpleNamespace(status=lambda: "web")
    a.pkg = SimpleNamespace(status=lambda: "pkg")
    a.docs = SimpleNamespace(status=lambda: "docs")
    a.health = SimpleNamespace(full_report=lambda: "health")
    a.security = SimpleNamespace(
        level_name="sandbox",
        set_level=lambda _lvl: False,
    )
    return a


def _make_react_ready_agent(max_steps=2):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(
        MAX_REACT_STEPS=max_steps,
        TEXT_MODEL="tm",
        CODING_MODEL="cm",
        PROJECT_NAME="Sidar",
        VERSION="1.0",
        BASE_DIR=Path("."),
        AI_PROVIDER="ollama",
        OLLAMA_URL="http://localhost",
        ACCESS_LEVEL="sandbox",
        USE_GPU=False,
        GPU_INFO="none",
        CUDA_VERSION="N/A",
        GITHUB_REPO="owner/repo",
        GEMINI_MODEL="g",
    )
    a._tools = {"list_dir": object()}
    a._AUTO_PARALLEL_SAFE = {"list_dir"}
    a._build_context = lambda: "ctx"
    a._build_tool_list = lambda: "tools"

    async def _archive(_q):
        return ""

    a._get_memory_archive_context = _archive
    return a


def test_respond_empty_and_handled_short_path():
    a = _make_agent_for_runtime()

    async def auto_handle(_):
        return True, "quick"

    a.auto.handle = auto_handle

    out = asyncio.run(_collect(a.respond("   ")))
    assert out == ["⚠ Boş girdi."]

    out = asyncio.run(_collect(a.respond("merhaba")))
    assert out == ["quick"]
    assert a.memory.items[0] == ("user", "merhaba")
    assert a.memory.items[1] == ("assistant", "quick")


def test_respond_react_and_summarize_path():
    a = _make_agent_for_runtime()

    async def auto_handle(_):
        return False, ""

    async def direct(_):
        return None

    async def summarize():
        a._summarized = True

    async def react(_):
        yield "c1"
        yield "c2"

    a.auto.handle = auto_handle
    a._try_direct_tool_route = direct
    a._summarize_memory = summarize
    a._react_loop = react
    a.memory.needs_summarization = lambda: True

    out = asyncio.run(_collect(a.respond("istek")))
    assert out[0].startswith("\n[Sistem] Konuşma belleği arşivleniyor")
    assert out[1:] == ["c1", "c2"]
    assert getattr(a, "_summarized", False) is True


def test_execute_tool_success_warning_and_unknown():
    a = _make_agent_for_runtime()
    audit = []

    async def _audit(name, arg, ok):
        audit.append((name, arg, ok))

    a._log_audit = _audit

    async def ok_handler(arg):
        return f"ok:{arg}"

    async def warn_handler(arg):
        return "⚠ hata gibi"

    a._tools = {"ok_tool": ok_handler, "warn_tool": warn_handler}

    assert asyncio.run(a._execute_tool("none", "x")) is None
    assert asyncio.run(a._execute_tool("ok_tool", "a")) == "ok:a"
    assert asyncio.run(a._execute_tool("warn_tool", "b")).startswith("⚠")
    assert audit == [("ok_tool", "a", True), ("warn_tool", "b", False)]


def test_set_access_level_clear_memory_and_status():
    a = _make_agent_for_runtime()

    class _Sec:
        level_name = "sandbox"

        def set_level(self, lvl):
            if lvl == "full":
                self.level_name = "full"
                return True
            return False

    class _Mem:
        def __init__(self):
            self.items = []

        def add(self, role, text):
            self.items.append((role, text))

        def clear(self):
            self.items.clear()

        def __len__(self):
            return 3

    a.security = _Sec()
    a.memory = _Mem()

    changed = a.set_access_level("full")
    assert "güncellendi" in changed
    unchanged = a.set_access_level("restricted")
    assert "zaten" in unchanged

    assert "temizlendi" in a.clear_memory()

    status = a.status()
    assert "SidarAgent" in status
    assert "Sağlayıcı" in status


def test_direct_tool_route_guard_paths(monkeypatch):
    a = _make_agent_for_runtime()

    class _LLM:
        async def chat(self, **kwargs):
            return '{"thought":"t","tool":"none","argument":""}'

    a.llm = _LLM()
    a.cfg.TEXT_MODEL = "tm"
    assert asyncio.run(a._try_direct_tool_route("x")) is None

    class _LLM2:
        async def chat(self, **kwargs):
            return '{"thought":"t","tool":"list_dir","argument":"."}'

    async def _exec(name, arg):
        return f"routed:{name}:{arg}"

    a.llm = _LLM2()
    monkeypatch.setattr(a, "_execute_tool", _exec)
    assert asyncio.run(a._try_direct_tool_route("x")) == "routed:list_dir:."


def test_direct_tool_route_non_string_disallowed_and_exception_paths():
    a = _make_agent_for_runtime()
    a.cfg.TEXT_MODEL = "tm"

    class _LLMNonString:
        async def chat(self, **kwargs):
            return {"tool": "list_dir"}

    a.llm = _LLMNonString()
    assert asyncio.run(a._try_direct_tool_route("x")) is None

    class _LLMBlockedTool:
        async def chat(self, **kwargs):
            return '{"thought":"t","tool":"write_file","argument":"x"}'

    a.llm = _LLMBlockedTool()
    assert asyncio.run(a._try_direct_tool_route("x")) is None

    class _LLMBroken:
        async def chat(self, **kwargs):
            raise RuntimeError("router failed")

    a.llm = _LLMBroken()
    assert asyncio.run(a._try_direct_tool_route("x")) is None


def test_tool_call_validation_errors_are_reachable():
    with pytest.raises(Exception):
        SA_MOD.ToolCall.model_validate({"thought": "t", "tool": "x"})

    with pytest.raises(Exception):
        SA_MOD.ToolCall.model_validate_json('{"thought":"t","tool":"x"}')


def test_build_context_and_instruction_file_cache(tmp_path):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(
        PROJECT_NAME="Sidar",
        VERSION="2.0",
        BASE_DIR=tmp_path,
        AI_PROVIDER="ollama",
        CODING_MODEL="code-m",
        TEXT_MODEL="text-m",
        OLLAMA_URL="http://localhost:11434",
        ACCESS_LEVEL="sandbox",
        USE_GPU=False,
        GPU_INFO="none",
        CUDA_VERSION="N/A",
        GITHUB_REPO="owner/repo",
        GEMINI_MODEL="gemini",
    )
    a._instructions_cache = None
    a._instructions_mtimes = {}
    a._instructions_lock = threading.Lock()
    a.code = SimpleNamespace(get_metrics=lambda: {"files_read": 1, "files_written": 2})
    a.github = SimpleNamespace(is_available=lambda: True)
    a.web = SimpleNamespace(is_available=lambda: True)
    a.docs = SimpleNamespace(status=lambda: "docs-ok")
    class _Todo:
        def __len__(self):
            return 1

        def list_tasks(self):
            return "- t1"

    a.todo = _Todo()
    a.memory = SimpleNamespace(get_last_file=lambda: "README.md")
    a.security = SimpleNamespace(level_name="sandbox")

    (tmp_path / "SIDAR.md").write_text("main rules", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "CLAUDE.md").write_text("sub rules", encoding="utf-8")

    loaded = a._load_instruction_files()
    assert "SIDAR.md" in loaded and "CLAUDE.md" in loaded
    cached = a._load_instruction_files()
    assert cached == loaded

    ctx = a._build_context()
    assert "[Proje Ayarları" in ctx
    assert "[Araç Durumu]" in ctx
    assert "[Proje Talimat Dosyaları" in ctx


def test_load_instruction_files_empty_tree_returns_cached_empty(tmp_path):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(BASE_DIR=tmp_path)
    a._instructions_cache = None
    a._instructions_mtimes = {}
    a._instructions_lock = threading.Lock()

    assert a._load_instruction_files() == ""
    assert a._load_instruction_files() == ""


def test_react_loop_final_answer_and_invalid_json_paths():
    a = _make_react_ready_agent(max_steps=1)

    class _Mem:
        def __init__(self):
            self.added = []

        def get_messages_for_llm(self):
            return []

        def add(self, role, text):
            self.added.append((role, text))

    a.memory = _Mem()

    async def _gen_once(text):
        yield text

    class _LLM:
        def __init__(self, text):
            self.text = text

        async def chat(self, **kwargs):
            return _gen_once(self.text)

    a.llm = _LLM('{"thought":"t","tool":"final_answer","argument":"DONE"}')
    out = asyncio.run(_collect(a._react_loop("x")))
    assert out == ["DONE"]
    assert a.memory.added == [("assistant", "DONE")]

    a2 = _make_react_ready_agent(max_steps=1)
    a2.memory = _Mem()
    a2.llm = _LLM("json değil")
    out2 = asyncio.run(_collect(a2._react_loop("x")))
    assert out2[-1].startswith("Üzgünüm, bu istek için güvenilir")


def test_react_loop_tool_execution_and_loop_break(monkeypatch):
    a = _make_react_ready_agent(max_steps=3)
    a.memory = SimpleNamespace(get_messages_for_llm=lambda: [], add=lambda *_: None)

    responses = [
        '{"thought":"ilk","tool":"list_dir","argument":"."}',
        '{"thought":"tekrar","tool":"list_dir","argument":"."}',
        '{"thought":"bitti","tool":"final_answer","argument":"OK"}',
    ]

    async def _gen_once(text):
        yield text

    class _LLM:
        def __init__(self):
            self.i = 0

        async def chat(self, **kwargs):
            text = responses[self.i]
            self.i += 1
            return _gen_once(text)

    async def _exec(tool, arg):
        return f"res:{tool}:{arg}"

    a.llm = _LLM()
    monkeypatch.setattr(a, "_execute_tool", _exec)

    out = asyncio.run(_collect(a._react_loop("listele")))
    assert any(x.startswith("\x00THOUGHT:") for x in out)
    assert any(x.startswith("\x00TOOL:list_dir") for x in out)
    assert out[-1] == "OK"


def test_execute_tool_parse_fallback_and_raise_path(monkeypatch):
    a = _make_agent_for_runtime()
    seen = []

    async def _audit(name, arg, ok):
        seen.append((name, arg, ok))

    a._log_audit = _audit

    async def _handler(parsed_arg):
        return f"handled:{parsed_arg}"

    a._tools = {"ok": _handler}

    def _raise_parse(_tool, _arg):
        raise ValueError("parse")

    monkeypatch.setattr(SA_MOD, "parse_tool_argument", _raise_parse)
    assert asyncio.run(a._execute_tool("ok", "raw")) == "handled:raw"

    async def _boom(_arg):
        raise RuntimeError("boom")

    a._tools = {"boom": _boom}
    with pytest.raises(RuntimeError):
        asyncio.run(a._execute_tool("boom", "x"))
    assert seen[-1] == ("boom", "x", False)


def test_tool_handlers_runtime_matrix(monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(
        BASE_DIR=".",
        AI_PROVIDER="ollama",
        OLLAMA_URL="http://localhost",
        CODING_MODEL="cm",
        TEXT_MODEL="tm",
        MAX_REACT_STEPS=2,
        REACT_TIMEOUT=10,
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=1000,
        RAG_CHUNK_OVERLAP=100,
        CPU_COUNT=2,
        MAX_MEMORY_TURNS=5,
        ACCESS_LEVEL="sandbox",
        USE_GPU=False,
        GPU_INFO="none",
        CUDA_VERSION="N/A",
        GITHUB_REPO="owner/repo",
        GEMINI_MODEL="g",
        VERSION="1.0",
        PROJECT_NAME="Sidar",
        DEBUG_MODE=False,
    )

    class FakeCode:
        def list_directory(self, d): return True, f"dir:{d}"
        def read_file(self, p): return True, f"read:{p}"
        def write_file(self, p, c): return True, f"write:{p}:{len(c)}"
        def patch_file(self, p, o, n): return True, f"patch:{p}:{o}->{n}"
        def execute_code(self, c): return True, f"exec:{c}"
        def audit_project(self, d): return f"audit:{d}"
        def run_shell(self, c): return True, f"shell:{c}"
        def glob_search(self, pattern, base): return True, f"glob:{pattern}:{base}"
        def grep_files(self, pattern, path, glob, _rx, ctx): return True, f"grep:{pattern}:{path}:{glob}:{ctx}"
        def get_metrics(self): return {"files_read": 1, "files_written": 1}

    class FakeGitHub:
        default_branch = "main"
        def is_available(self): return True
        def list_commits(self, n): return True, f"commits:{n}"
        def get_repo_info(self): return True, "repo-info"
        def read_remote_file(self, p): return True, f"gh-read:{p}"
        def list_files(self, p, b): return True, f"gh-files:{p}:{b}"
        def create_or_update_file(self, p, c, m, b): return True, f"gh-write:{p}:{m}:{b}"
        def create_branch(self, b, f): return True, f"gh-branch:{b}:{f}"
        def create_pull_request(self, t, b, h, base): return True, f"gh-pr:{t}:{h}:{base}"
        def search_code(self, q): return True, f"gh-search:{q}"
        def list_pull_requests(self, state, limit): return True, f"gh-prs:{state}:{limit}"
        def get_pull_request(self, n): return True, f"gh-pr-get:{n}"
        def add_pr_comment(self, n, c): return True, f"gh-pr-comment:{n}:{c}"
        def close_pull_request(self, n): return True, f"gh-pr-close:{n}"
        def get_pr_files(self, n): return True, f"gh-pr-files:{n}"
        def list_issues(self, state, limit):
            return True, [{"number": 1, "user": "u", "title": "t", "created_at": "d"}]
        def create_issue(self, title, body): return True, f"gh-issue-create:{title}:{body}"
        def comment_issue(self, number, body): return True, f"gh-issue-comment:{number}:{body}"
        def close_issue(self, number): return True, f"gh-issue-close:{number}"
        def get_pull_request_diff(self, number): return True, f"gh-pr-diff:{number}"

    class FakeHealth:
        def full_report(self): return "health-ok"
        def optimize_gpu_memory(self): return "gpu-ok"

    class FakeWeb:
        def is_available(self): return True
        def status(self): return "web-ok"
        async def search(self, q): return True, f"web-search:{q}"
        async def fetch_url(self, u): return True, f"web-fetch:{u}"
        async def search_docs(self, lib, topic): return True, f"docs:{lib}:{topic}"
        async def search_stackoverflow(self, q): return True, f"so:{q}"

    class FakePkg:
        def status(self): return "pkg-ok"
        async def pypi_info(self, p): return True, f"pypi:{p}"
        async def pypi_compare(self, p, v): return True, f"pypi-cmp:{p}:{v}"
        async def npm_info(self, p): return True, f"npm:{p}"
        async def github_releases(self, r): return True, f"rel:{r}"
        async def github_latest_release(self, r): return True, f"latest:{r}"

    class FakeDocs:
        def status(self): return "docs-ok"
        def search(self, q, _none, mode, session): return True, f"docs-search:{q}:{mode}:{session}"
        async def add_document_from_url(self, url, title, session_id): return True, f"docs-add:{title}:{url}:{session_id}"
        def add_document_from_file(self, path, title, _tags, session_id): return True, f"docs-add-file:{title}:{path}:{session_id}"
        def list_documents(self, session_id): return f"docs-list:{session_id}"
        def delete_document(self, doc_id, session_id): return f"docs-del:{doc_id}:{session_id}"

    class FakeTodo:
        def set_tasks(self, tasks): return f"todo-set:{len(tasks)}"
        def list_tasks(self): return "todo-list"
        def update_task(self, task_id, state): return f"todo-update:{task_id}:{state}"
        def scan_project_todos(self, directory, extensions): return f"todo-scan:{directory}:{extensions}"

    class FakeMemory:
        active_session_id = "session-1"
        def set_last_file(self, _f):
            return None
        def get_last_file(self):
            return "README.md"

    a.code = FakeCode()
    a.github = FakeGitHub()
    a.health = FakeHealth()
    a.web = FakeWeb()
    a.pkg = FakePkg()
    a.docs = FakeDocs()
    a.todo = FakeTodo()
    a.memory = FakeMemory()
    a.security = SimpleNamespace(level_name="sandbox")

    def _parse(tool_name, raw):
        if tool_name == "scan_project_todos":
            return SimpleNamespace(directory="src", extensions=[".py"])
        if tool_name == "github_list_issues":
            return SimpleNamespace(state="open", limit=10)
        if tool_name == "github_create_issue":
            return SimpleNamespace(title="Bug", body="desc")
        if tool_name == "github_comment_issue":
            return SimpleNamespace(number=7, body="note")
        if tool_name == "github_close_issue":
            return SimpleNamespace(number=7)
        if tool_name == "github_pr_diff":
            return SimpleNamespace(number=3)
        return raw

    monkeypatch.setattr(SA_MOD, "parse_tool_argument", _parse)

    async def _run():
        assert await a._tool_list_dir(".") == "dir:."
        assert await a._tool_read_file("f.py") == "read:f.py"
        assert "belirtilmedi" in await a._tool_read_file("")
        assert await a._tool_write_file("f.py|||print(1)") == "write:f.py:8"
        assert "Hatalı format" in await a._tool_write_file("f.py")
        assert await a._tool_patch_file("f.py|||old|||new") == "patch:f.py:old->new"
        assert "Hatalı patch" in await a._tool_patch_file("f.py|||old")
        assert await a._tool_execute_code("print(1)") == "exec:print(1)"
        assert "belirtilmedi" in await a._tool_execute_code("")
        assert await a._tool_audit(".") == "audit:."
        assert await a._tool_health("") == "health-ok"
        assert await a._tool_gpu_optimize("") == "gpu-ok"

        assert await a._tool_run_shell("ls") == "shell:ls"
        assert "belirtilmedi" in await a._tool_run_shell("")
        assert await a._tool_glob_search("*.py|||.") == "glob:*.py:."
        assert "belirtilmedi" in await a._tool_glob_search("   ")
        assert await a._tool_grep_files("def|||.|||*.py|||2") == "grep:def:.:*.py:2"
        assert "belirtilmedi" in await a._tool_grep_files("")

        assert await a._tool_github_commits("4") == "commits:4"
        assert await a._tool_github_commits("x") == "commits:10"
        assert await a._tool_github_info("") == "repo-info"
        assert await a._tool_github_read("README.md") == "gh-read:README.md"
        assert "belirtilmedi" in await a._tool_github_read("")
        assert await a._tool_github_list_files("src|||main") == "gh-files:src:main"
        assert await a._tool_github_write("f.py|||c|||msg|||dev") == "gh-write:f.py:msg:dev"
        assert "Hatalı format" in await a._tool_github_write("f.py|||c")
        assert await a._tool_github_create_branch("feature|||main") == "gh-branch:feature:main"
        assert "belirtilmedi" in await a._tool_github_create_branch("")
        assert await a._tool_github_create_pr("Title|||Body|||feature|||main") == "gh-pr:Title:feature:main"
        assert "Hatalı format" in await a._tool_github_create_pr("Title|||Body")
        assert await a._tool_github_search_code("query") == "gh-search:query"
        assert "belirtilmedi" in await a._tool_github_search_code("")
        assert await a._tool_github_list_prs("open|||5") == "gh-prs:open:5"
        assert await a._tool_github_get_pr("1") == "gh-pr-get:1"
        assert "belirtilmedi" in await a._tool_github_get_pr("")
        assert "Geçerli bir" in await a._tool_github_get_pr("abc")
        assert await a._tool_github_comment_pr("1|||yorum") == "gh-pr-comment:1:yorum"
        assert "Format:" in await a._tool_github_comment_pr("1")
        assert "Geçerli bir" in await a._tool_github_comment_pr("x|||yorum")
        assert "boş olamaz" in await a._tool_github_comment_pr("1|||   ")
        assert await a._tool_github_close_pr("1") == "gh-pr-close:1"
        assert "belirtilmedi" in await a._tool_github_close_pr("")
        assert "Geçerli bir" in await a._tool_github_close_pr("abc")
        assert await a._tool_github_pr_files("1") == "gh-pr-files:1"
        assert "belirtilmedi" in await a._tool_github_pr_files("")
        assert "Geçerli bir" in await a._tool_github_pr_files("abc")
        assert "#1" in await a._tool_github_list_issues("open|||10")
        assert await a._tool_github_create_issue("title|||body") == "gh-issue-create:Bug:desc"
        assert await a._tool_github_comment_issue("1|||body") == "gh-issue-comment:7:note"
        assert await a._tool_github_close_issue("1") == "gh-issue-close:7"
        assert await a._tool_github_pr_diff("1") == "gh-pr-diff:3"

        assert await a._tool_web_search("q") == "web-search:q"
        assert "belirtilmedi" in await a._tool_web_search("")
        assert await a._tool_fetch_url("http://x") == "web-fetch:http://x"
        assert "belirtilmedi" in await a._tool_fetch_url("")
        assert await a._tool_search_docs("lib topic") == "docs:lib:topic"
        assert await a._tool_search_stackoverflow("error") == "so:error"
        assert await a._tool_pypi("pytest") == "pypi:pytest"
        assert await a._tool_pypi_compare("pytest|7") == "pypi-cmp:pytest:7"
        assert "Kullanım" in await a._tool_pypi_compare("pytest")
        assert await a._tool_npm("react") == "npm:react"
        assert await a._tool_gh_releases("owner/repo") == "rel:owner/repo"
        assert await a._tool_gh_latest("owner/repo") == "latest:owner/repo"

        assert "docs-search:q:vector:session-1" == await a._tool_docs_search("q|vector")
        assert await a._tool_docs_add("title|http://x") == "docs-add:title:http://x:session-1"
        assert "Kullanım" in await a._tool_docs_add("title")
        assert await a._tool_docs_add_file("title|a.py") == "docs-add-file:title:a.py:session-1"
        assert await a._tool_docs_add_file("a.py") == "docs-add-file:a.py:a.py:session-1"
        assert "belirtilmedi" in await a._tool_docs_add_file("")
        assert await a._tool_docs_list("") == "docs-list:session-1"
        assert await a._tool_docs_delete("doc-1") == "docs-del:doc-1:session-1"

        assert await a._tool_todo_write("task:::pending|||task2:::completed") == "todo-set:2"
        assert "belirtilmedi" in await a._tool_todo_write("  ")
        assert await a._tool_todo_read("") == "todo-list"
        assert await a._tool_todo_update("1|||done") == "todo-update:1:done"
        assert "Format" in await a._tool_todo_update("1")
        assert "sayısal" in await a._tool_todo_update("x|||done")
        assert await a._tool_scan_project_todos("src|||.py") == "todo-scan:src:['.py']"

        conf = await a._tool_get_config("")
        assert "[Proje Kök Dizini]" in conf
        assert "AI_PROVIDER" in conf

    asyncio.run(_run())


def test_smart_pr_and_subtask_runtime_paths():
    a = _make_react_ready_agent(max_steps=1)
    a.cfg.SUBTASK_MAX_STEPS = 2

    class FakeGitHub:
        default_branch = "main"
        def is_available(self):
            return True
        def create_pull_request(self, title, body, head, base):
            return True, f"pr:{title}:{head}:{base}:{'## Özet' in body}"

    class FakeCode:
        def run_shell(self, cmd):
            if "show-current" in cmd:
                return True, "feat/test"
            if "status --short" in cmd:
                return True, "M a.py"
            if "diff --stat" in cmd:
                return True, "a.py | 1 +"
            if "diff --no-color" in cmd:
                return True, "+print(1)"
            if "log" in cmd:
                return True, "abc feat"
            return True, ""

    class _LLM:
        async def chat(self, **kwargs):
            if kwargs.get("json_mode") and "Pull Request" in kwargs.get("messages", [{}])[0].get("content", ""):
                return '{"title":"Test PR", "body":"## Özet\\n- x\\n\\n## Test Planı\\n- [ ] y"}'
            return '{"thought":"t", "tool":"final_answer", "argument":"Subtask done"}'

    a.github = FakeGitHub()
    a.code = FakeCode()
    a.llm = _LLM()
    a.memory = SimpleNamespace(active_session_id="s1")
    a._tools = {}

    pr_out = asyncio.run(a._tool_github_smart_pr("feat/test|||main|||notes"))
    assert "Akıllı PR oluşturuldu" in pr_out
    assert "Test PR" in pr_out

    subtask_out = asyncio.run(a._tool_subtask("bir alt görev"))
    assert "[Alt Görev Tamamlandı]" in subtask_out
    assert "Subtask done" in subtask_out
    assert "belirtilmedi" in asyncio.run(a._tool_subtask("  "))

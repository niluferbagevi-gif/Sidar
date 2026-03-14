# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

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

    async def fake_multi(_):
        return "multi"

    a._try_multi_agent = fake_multi

    out = asyncio.run(_collect(a.respond("   ")))
    assert out == ["⚠ Boş girdi."]

    out = asyncio.run(_collect(a.respond("merhaba")))
    assert out == ["multi"]
    assert a.memory.items[0] == ("user", "merhaba")
    assert a.memory.items[1] == ("assistant", "multi")


def test_respond_react_and_summarize_path():
    a = _make_agent_for_runtime()

    async def fake_multi(_):
        return "supervised"

    a._try_multi_agent = fake_multi

    out = asyncio.run(_collect(a.respond("istek")))
    assert out == ["supervised"]


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


def test_react_loop_json_list_and_error_feedback_paths(monkeypatch):
    a = _make_react_ready_agent(max_steps=1)

    class _Mem:
        def get_messages_for_llm(self):
            return []

        def add(self, *_args):
            return None

    a.memory = _Mem()

    async def _gen_once(text):
        yield text

    class _LLM:
        def __init__(self, text):
            self.text = text

        async def chat(self, **kwargs):
            return _gen_once(self.text)

    # Boş JSON liste -> ValueError yakalanır ve döngü max adım nedeniyle sonlanır
    a.llm = _LLM("[]")
    out = asyncio.run(_collect(a._react_loop("x")))
    assert out[-1].startswith("Üzgünüm, bu istek için güvenilir")

    # tool alanı yoksa final_answer özetine normalize edilir
    b = _make_react_ready_agent(max_steps=1)
    b.memory = _Mem()
    b.llm = _LLM('{"thought":"t","argument":"x"}')
    out2 = asyncio.run(_collect(b._react_loop("x")))
    assert out2[-1] == "- **argument:** x"

    # Geçersiz liste elemanı -> ValidationError branch
    b2 = _make_react_ready_agent(max_steps=1)
    b2.memory = _Mem()
    b2.llm = _LLM('[{"thought":"t","argument":"x"}]')
    out2b = asyncio.run(_collect(b2._react_loop("x")))
    assert out2b[-1].startswith("Üzgünüm, bu istek için güvenilir")

    # Paralel liste içinde final_answer olamaz
    c = _make_react_ready_agent(max_steps=1)
    c.memory = _Mem()
    c.llm = _LLM('[{"thought":"t1","tool":"list_dir","argument":"."},{"thought":"t2","tool":"final_answer","argument":"x"}]')
    out3 = asyncio.run(_collect(c._react_loop("x")))
    assert out3[-1].startswith("Üzgünüm, bu istek için güvenilir")

    # Paralel listede unsafe tool
    d = _make_react_ready_agent(max_steps=1)
    d.memory = _Mem()
    d._AUTO_PARALLEL_SAFE = {"list_dir"}
    d.llm = _LLM('[{"thought":"t1","tool":"list_dir","argument":"."},{"thought":"t2","tool":"write_file","argument":"x"}]')
    out4 = asyncio.run(_collect(d._react_loop("x")))
    assert out4[-1].startswith("Üzgünüm, bu istek için güvenilir")

    # Paralel batch içinde exception sonucu had_error=True
    e = _make_react_ready_agent(max_steps=2)
    e.memory = _Mem()

    class _LLMSeq:
        def __init__(self):
            self.i = 0
            self.payloads = [
                '[{"thought":"t1","tool":"list_dir","argument":"."},{"thought":"t2","tool":"list_dir","argument":"boom"}]',
                '{"thought":"done","tool":"final_answer","argument":"OK"}',
            ]

        async def chat(self, **kwargs):
            text = self.payloads[self.i]
            self.i += 1
            return _gen_once(text)

    async def _exec(tool, arg):
        if arg == "boom":
            raise RuntimeError("tool fail")
        return "fine"

    e.llm = _LLMSeq()
    monkeypatch.setattr(e, "_execute_tool", _exec)
    out5 = asyncio.run(_collect(e._react_loop("x")))
    assert "OK" in out5


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


def test_github_tool_early_return_and_subtask_branches(monkeypatch):
    a = _make_agent_for_runtime()
    a.github = SimpleNamespace(
        is_available=lambda: False,
        list_issues=lambda _state, _limit: (False, []),
    )

    assert "token" in asyncio.run(a._tool_github_list_issues("open|||2"))
    assert "title gerekli" in asyncio.run(a._tool_github_create_issue(SimpleNamespace(title="", body="b")))
    assert "token" in asyncio.run(a._tool_github_comment_issue(SimpleNamespace(number=1, body="x")))
    assert "token" in asyncio.run(a._tool_github_close_issue(SimpleNamespace(number=1)))
    assert "token" in asyncio.run(a._tool_github_pr_diff(SimpleNamespace(number=1)))

    a.github = SimpleNamespace(
        is_available=lambda: True,
        list_issues=lambda _state, _limit: (False, []),
    )
    assert "Issue'lar alınamadı" in asyncio.run(a._tool_github_list_issues("open|||2"))
    a.github = SimpleNamespace(
        is_available=lambda: True,
        list_issues=lambda _state, _limit: (True, []),
    )
    assert "issue bulunmuyor" in asyncio.run(a._tool_github_list_issues("open|||2"))

    # _run_subtask: _execute_tool exception -> generic except branch ve fallback dönüş
    a.cfg = SimpleNamespace(TEXT_MODEL="tm", CODING_MODEL="cm")

    class _LLM:
        async def chat(self, **kwargs):
            return '{"thought":"t","tool":"list_dir","argument":"."}'

    async def _boom(_tool, _arg):
        raise RuntimeError("subtask fail")

    a.llm = _LLM()
    a._execute_tool = _boom
    out = asyncio.run(a._tool_subtask("task"))
    assert "Maksimum adım" in out


def test_get_config_gpu_and_archive_context_filters(tmp_path):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(
        BASE_DIR=tmp_path,
        USE_GPU=True,
        GPU_INFO="RTX",
        GPU_COUNT=2,
        CUDA_VERSION="12.1",
        MEMORY_ENCRYPTION_KEY="",
        PROJECT_NAME="Sidar",
        VERSION="1.0",
        ACCESS_LEVEL="sandbox",
        DEBUG_MODE=False,
        AI_PROVIDER="ollama",
        OLLAMA_URL="http://localhost",
        CODING_MODEL="cm",
        TEXT_MODEL="tm",
        REACT_TIMEOUT=10,
        MAX_REACT_STEPS=2,
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=100,
        RAG_CHUNK_OVERLAP=10,
        CPU_COUNT=2,
        MAX_MEMORY_TURNS=5,
        GITHUB_REPO="owner/repo",
        GEMINI_MODEL="g",
    )
    a.security = SimpleNamespace(level_name="sandbox")
    a.code = SimpleNamespace(get_metrics=lambda: {"files_read": 0, "files_written": 0})
    a.github = SimpleNamespace(is_available=lambda: False)
    a.web = SimpleNamespace(is_available=lambda: False)
    a.pkg = SimpleNamespace(status=lambda: "ok")
    a.docs = SimpleNamespace(status=lambda: "ok", collection=None)
    a.todo = SimpleNamespace(__len__=lambda self: 0, list_tasks=lambda: "")
    a.memory = SimpleNamespace(get_last_file=lambda: "")
    a._instructions_cache = ""
    a._instructions_mtimes = {}
    a._instructions_lock = threading.Lock()

    cfg_text = asyncio.run(a._tool_get_config(""))
    assert "RTX (2 GPU, CUDA 12.1)" in cfg_text

    a.docs = SimpleNamespace(
        collection=SimpleNamespace(
            query=lambda **kwargs: {
                "documents": [["good", "skip-low", ""]],
                "metadatas": [[{"source": "memory_archive", "title": "T1"}, {"source": "memory_archive", "title": "T2"}, {"source": "memory_archive", "title": "T3"}]],
                "distances": [[0.1, 0.9, 0.2]],
            }
        )
    )
    a.cfg.MEMORY_ARCHIVE_TOP_K = 1
    a.cfg.MEMORY_ARCHIVE_MIN_SCORE = 0.5
    a.cfg.MEMORY_ARCHIVE_MAX_CHARS = 320
    ctx = asyncio.run(a._get_memory_archive_context("sorgu"))
    assert "Geçmiş Sohbet" in ctx


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


def test_github_tool_schema_argument_paths():
    a = _make_agent_for_runtime()

    class _GH:
        def __init__(self):
            self.repo_name = "owner/repo"

        def is_available(self):
            return True

        def list_files(self, path, branch):
            return True, f"files:{path}:{branch}"

        def create_or_update_file(self, path, content, message, branch):
            return True, f"write:{path}:{message}:{branch}:{len(content)}"

        def create_branch(self, branch_name, from_branch):
            return True, f"branch:{branch_name}:{from_branch}"

        def create_pull_request(self, title, body, head, base):
            return True, f"pr:{title}:{head}:{base}:{bool(body)}"

        def list_issues(self, state, limit):
            return True, [{"number": 2, "user": "u", "title": "issue", "created_at": "d"}]

        def create_issue(self, title, body):
            return True, f"issue-create:{title}:{body}"

        def comment_issue(self, number, body):
            return True, f"issue-comment:{number}:{body}"

        def close_issue(self, number):
            return True, f"issue-close:{number}"

        def get_pull_request_diff(self, number):
            return True, f"diff:{number}"

    a.github = _GH()

    list_arg = SA_MOD.GithubListFilesSchema()
    list_arg.path = "src"
    list_arg.branch = "main"
    assert asyncio.run(a._tool_github_list_files(list_arg)) == "files:src:main"

    write_arg = SA_MOD.GithubWriteSchema()
    write_arg.path = "a.py"
    write_arg.content = "print(1)"
    write_arg.commit_message = "msg"
    write_arg.branch = "dev"
    assert asyncio.run(a._tool_github_write(write_arg)).startswith("write:a.py:msg:dev")

    branch_arg = SA_MOD.GithubCreateBranchSchema()
    branch_arg.branch_name = "feature/x"
    branch_arg.from_branch = "main"
    assert asyncio.run(a._tool_github_create_branch(branch_arg)) == "branch:feature/x:main"

    pr_arg = SA_MOD.GithubCreatePRSchema()
    pr_arg.title = "T"
    pr_arg.body = "B"
    pr_arg.head = "feature/x"
    pr_arg.base = "main"
    assert asyncio.run(a._tool_github_create_pr(pr_arg)) == "pr:T:feature/x:main:True"

    issues_arg = SA_MOD.GithubListIssuesSchema()
    issues_arg.state = "open"
    issues_arg.limit = 5
    assert "#2" in asyncio.run(a._tool_github_list_issues(issues_arg))

    create_issue_arg = SA_MOD.GithubCreateIssueSchema()
    create_issue_arg.title = "Bug"
    create_issue_arg.body = "desc"
    assert asyncio.run(a._tool_github_create_issue(create_issue_arg)) == "issue-create:Bug:desc"

    comment_issue_arg = SA_MOD.GithubCommentIssueSchema()
    comment_issue_arg.number = 11
    comment_issue_arg.body = "note"
    assert asyncio.run(a._tool_github_comment_issue(comment_issue_arg)) == "issue-comment:11:note"

    close_issue_arg = SA_MOD.GithubCloseIssueSchema()
    close_issue_arg.number = 11
    assert asyncio.run(a._tool_github_close_issue(close_issue_arg)) == "issue-close:11"

    diff_arg = SA_MOD.GithubPRDiffSchema()
    diff_arg.number = 7
    assert asyncio.run(a._tool_github_pr_diff(diff_arg)) == "diff:7"


def test_execute_tool_tracing_span_attributes(monkeypatch):
    a = _make_agent_for_runtime()
    audit = []

    async def _audit(name, arg, ok):
        audit.append((name, arg, ok))

    class _Span:
        def __init__(self):
            self.attrs = {}

        def set_attribute(self, key, value):
            self.attrs[key] = value

    span = _Span()

    class _Trace:
        @staticmethod
        def get_current_span():
            return span

    class _Cm:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Tracer:
        def start_as_current_span(self, _name):
            return _Cm()

    a._log_audit = _audit
    a.tracer = _Tracer()
    monkeypatch.setattr(SA_MOD, "trace", _Trace)

    async def _handler(_arg):
        return "ok"

    a._tools = {"x": _handler}
    out = asyncio.run(a._execute_tool("x", "arg"))
    assert out == "ok"
    assert audit == [("x", "arg", True)]
    assert span.attrs["sidar.tool.name"] == "x"
    assert span.attrs["sidar.tool.success"] is True
    assert "sidar.tool.duration_ms" in span.attrs


def test_react_loop_parallel_json_array_tools_path(monkeypatch):
    a = _make_react_ready_agent(max_steps=1)
    a.memory = SimpleNamespace(get_messages_for_llm=lambda: [], add=lambda *_: None)
    a._AUTO_PARALLEL_SAFE = {"list_dir", "health"}

    async def _gen_once(text):
        yield text

    class _LLM:
        async def chat(self, **kwargs):
            return _gen_once('[{"thought":"t1","tool":"list_dir","argument":"."},{"thought":"t2","tool":"health","argument":""}]')

    async def _exec(tool, arg):
        return f"{tool}:{arg or 'ok'}"

    a.llm = _LLM()
    monkeypatch.setattr(a, "_execute_tool", _exec)

    out = asyncio.run(_collect(a._react_loop("paralel")))
    assert any(x.startswith("\x00THOUGHT:") for x in out)
    assert any(x == "\x00TOOL:list_dir\x00" for x in out)
    assert any(x == "\x00TOOL:health\x00" for x in out)
    assert out[-1].startswith("Üzgünüm")


def test_memory_archive_context_truncation_and_error_fallback():
    a = _make_agent_for_runtime()

    class _Collection:
        def query(self, **kwargs):
            return {
                "documents": [["x" * 900, "short note"]],
                "metadatas": [[{"source": "memory_archive", "title": "A"}, {"source": "memory_archive", "title": "B"}]],
                "distances": [[0.1, 0.2]],
            }

    a.docs = SimpleNamespace(collection=_Collection())
    text = a._get_memory_archive_context_sync("q", top_k=3, min_score=0.1, max_chars=800)
    assert "[Geçmiş Sohbet Arşivinden İlgili Notlar]" in text
    assert "..." in text

    class _BrokenCollection:
        def query(self, **kwargs):
            raise RuntimeError("db down")

    a.docs = SimpleNamespace(collection=_BrokenCollection())
    assert a._get_memory_archive_context_sync("q", top_k=1, min_score=0.1, max_chars=300) == ""


def test_summarize_memory_success_and_exception_paths(monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(TEXT_MODEL="tm", CODING_MODEL="cm")

    class _Mem:
        def __init__(self):
            self.summary = None

        def get_history(self):
            return [
                {"role": "user", "content": "u1", "timestamp": 1},
                {"role": "assistant", "content": "a1", "timestamp": 2},
                {"role": "user", "content": "u2", "timestamp": 3},
                {"role": "assistant", "content": "a2", "timestamp": 4},
            ]

        def apply_summary(self, s):
            self.summary = s

    a.memory = _Mem()

    class _Docs:
        def __init__(self):
            self.called = 0

        def add_document(self, **kwargs):
            self.called += 1

    docs = _Docs()
    a.docs = docs

    class _LLM:
        async def chat(self, **kwargs):
            return "özet"

    a.llm = _LLM()
    asyncio.run(a._summarize_memory())
    assert docs.called == 1
    assert a.memory.summary == "özet"

    class _BrokenDocs:
        def add_document(self, **kwargs):
            raise RuntimeError("docs fail")

    class _BrokenLLM:
        async def chat(self, **kwargs):
            raise RuntimeError("llm fail")

    a.docs = _BrokenDocs()
    a.llm = _BrokenLLM()
    # sadece exception path'leri çalışsın, raise etmesin
    asyncio.run(a._summarize_memory())


def test_subtask_non_string_empty_tool_and_validation_paths(monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(TEXT_MODEL="tm", CODING_MODEL="cm", SUBTASK_MAX_STEPS=4)

    responses = [
        123,
        "metin ama json yok",
        '{"thought":"t","tool":"","argument":"x"}',
        '{"thought":"tamam","tool":"final_answer","argument":"bitti"}',
    ]

    class _LLM:
        def __init__(self):
            self.i = 0

        async def chat(self, **kwargs):
            out = responses[self.i]
            self.i += 1
            return out

    a.llm = _LLM()
    a._execute_tool = lambda *_: None
    out = asyncio.run(a._tool_subtask("alt görev"))
    assert out.endswith("bitti")

    class _LLMValidation:
        async def chat(self, **kwargs):
            return '{"thought":"eksik"}'

    a2 = _make_agent_for_runtime()
    a2.cfg = SimpleNamespace(TEXT_MODEL="tm", CODING_MODEL="cm", SUBTASK_MAX_STEPS=1)
    a2.llm = _LLMValidation()
    assert "tamamlanamadı" in asyncio.run(a2._tool_subtask("x"))


def test_subtask_tool_missing_runtime_exception_and_fallback_message(monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(TEXT_MODEL="tm", CODING_MODEL="cm", SUBTASK_MAX_STEPS=3)

    class _LLM:
        def __init__(self):
            self.i = 0

        async def chat(self, **kwargs):
            seq = [
                '{"thought":"t","tool":"bilinmeyen","argument":"x"}',
                '{"thought":"t","tool":"list_dir","argument":"."}',
                '{"thought":"t","tool":"final_answer","argument":"ok"}',
            ]
            out = seq[self.i]
            self.i += 1
            return out

    async def _exec(tool, _arg):
        if tool == "bilinmeyen":
            return None
        raise RuntimeError("tool crash")

    a.llm = _LLM()
    monkeypatch.setattr(a, "_execute_tool", _exec)
    assert "tamamlanamadı" in asyncio.run(a._tool_subtask("işle"))


def test_github_guard_branches_and_smart_pr_paths(monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(TEXT_MODEL="tm", CODING_MODEL="cm")

    class _GitHubOff:
        def is_available(self):
            return False

    a.github = _GitHubOff()
    assert "token" in asyncio.run(a._tool_github_write("a|||b|||c"))
    assert "token" in asyncio.run(a._tool_github_create_branch("x"))
    assert "token" in asyncio.run(a._tool_github_create_pr("t|||b|||h"))
    assert "token" in asyncio.run(a._tool_github_search_code("q"))
    assert "token" in asyncio.run(a._tool_github_list_prs("open|||x"))
    assert "token" in asyncio.run(a._tool_github_get_pr("1"))
    assert "token" in asyncio.run(a._tool_github_comment_pr("1|||x"))
    assert "token" in asyncio.run(a._tool_github_close_pr("1"))
    assert "token" in asyncio.run(a._tool_github_pr_files("1"))
    assert "token" in asyncio.run(a._tool_github_list_issues("open|||2"))
    assert "token" in asyncio.run(a._tool_github_create_issue("x"))
    assert "number gerekli" in asyncio.run(a._tool_github_comment_issue("x"))
    assert "number gerekli" in asyncio.run(a._tool_github_close_issue("x"))
    assert "number gerekli" in asyncio.run(a._tool_github_pr_diff("x"))
    assert "token" in asyncio.run(a._tool_github_smart_pr(""))

    class _GitHubOn:
        default_branch = property(lambda _self: (_ for _ in ()).throw(RuntimeError("no default")))

        def is_available(self):
            return True

        def create_pull_request(self, title, body, head, base):
            return False, f"fail:{title}:{head}:{base}:{len(body)}"

    class _Code:
        def __init__(self):
            self.calls = 0

        def run_shell(self, cmd):
            self.calls += 1
            if "show-current" in cmd:
                return True, "feat/x\n"
            if "status" in cmd:
                return True, "M a.py"
            if "diff --stat" in cmd:
                return True, "a.py | 1 +"
            if "diff --no-color" in cmd:
                return True, "x" * 12050
            return True, "c1"

    class _LLM:
        async def chat(self, **kwargs):
            raise RuntimeError("llm down")

    a2 = _make_agent_for_runtime()
    a2.cfg = SimpleNamespace(TEXT_MODEL="tm", CODING_MODEL="cm")
    a2.github = _GitHubOn()
    a2.code = _Code()
    a2.llm = _LLM()
    out = asyncio.run(a2._tool_github_smart_pr(""))
    assert out.startswith("fail:feat")


def test_instruction_file_loader_stat_and_read_failures_and_summarize_short_history(tmp_path, monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(BASE_DIR=tmp_path)
    a._instructions_cache = None
    a._instructions_mtimes = {}
    a._instructions_lock = threading.Lock()

    good = tmp_path / "SIDAR.md"
    good.write_text("ok", encoding="utf-8")
    bad = tmp_path / "CLAUDE.md"
    bad.write_text("", encoding="utf-8")

    real_read = Path.read_text

    def _read(self, *args, **kwargs):
        if self.name == "SIDAR.md":
            raise OSError("read fail")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _read)
    assert a._load_instruction_files() == ""

    b = _make_agent_for_runtime()
    b.memory = SimpleNamespace(get_history=lambda: [{"role": "u", "content": "x"}] * 3)
    asyncio.run(b._summarize_memory())


def test_build_tool_list_deduplicates_handlers_and_uses_doc_fallback():
    a = _make_agent_for_runtime()

    async def shared(_arg):
        """Paylaşılan araç."""
        return "ok"

    async def no_doc(_arg):
        return "ok"

    no_doc.__doc__ = None
    a._tools = {"t1": shared, "t2": shared, "t3": no_doc}

    tool_list = a._build_tool_list()
    assert "MEVCUT ARAÇLAR" in tool_list
    assert tool_list.count("Paylaşılan araç") == 1
    assert "Açıklama belirtilmemiş" in tool_list


def test_execute_tool_tracer_exception_sets_span_attributes(monkeypatch):
    a = _make_agent_for_runtime()
    calls = []

    class _Span:
        def set_attribute(self, key, value):
            calls.append((key, value))

    class _SpanCM:
        def __enter__(self):
            return _Span()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Tracer:
        def start_as_current_span(self, _name):
            return _SpanCM()

    async def _boom(_arg):
        raise RuntimeError("boom")

    async def _audit(_name, _arg, ok):
        calls.append(("audit", ok))

    monkeypatch.setattr(SA_MOD, "trace", SimpleNamespace(get_current_span=lambda: _Span()))
    a.tracer = _Tracer()
    a._log_audit = _audit
    a._tools = {"x": _boom}

    with pytest.raises(RuntimeError):
        asyncio.run(a._execute_tool("x", "arg"))

    assert ("sidar.tool.name", "x") in calls
    assert ("sidar.tool.success", False) in calls
    assert ("audit", False) in calls


def test_get_memory_archive_context_sync_filters_and_limits():
    a = _make_agent_for_runtime()

    class _Collection:
        def query(self, **kwargs):
            return {
                "documents": [["", "uygun metin", "atla"]],
                "metadatas": [[{"source": "memory_archive", "title": "boş"}, {"source": "memory_archive", "title": "başlık"}, {"source": "other"}]],
                "distances": [[0.1, 0.2, 0.1]],
            }

    a.docs = SimpleNamespace(collection=_Collection())
    txt = a._get_memory_archive_context_sync("q", top_k=2, min_score=0.5, max_chars=1000)
    assert "Geçmiş Sohbet Arşivinden" in txt
    assert "başlık" in txt
    assert "atla" not in txt


def test_get_memory_archive_context_sync_empty_and_query_error():
    a = _make_agent_for_runtime()
    a.docs = SimpleNamespace(collection=None)
    assert a._get_memory_archive_context_sync("q", 1, 0.1, 300) == ""

    class _BadCollection:
        def query(self, **kwargs):
            raise RuntimeError("db err")

    a.docs = SimpleNamespace(collection=_BadCollection())
    assert a._get_memory_archive_context_sync("q", 1, 0.1, 300) == ""



def test_react_loop_json_alias_output_and_summary_fallback(monkeypatch):
    a = _make_react_ready_agent(max_steps=1)
    a.memory = SimpleNamespace(get_messages_for_llm=lambda: [], add=lambda *_: None)

    async def _gen_once(text):
        yield text

    class _LLMOutputAlias:
        async def chat(self, **kwargs):
            return _gen_once('{"output":"benim_ozel_cevabim"}')

    a.llm = _LLMOutputAlias()
    out = asyncio.run(_collect(a._react_loop("x")))
    assert out == ["benim_ozel_cevabim"]

    a2 = _make_react_ready_agent(max_steps=1)
    a2.memory = SimpleNamespace(get_messages_for_llm=lambda: [], add=lambda *_: None)

    class _LLMUnknownKey:
        async def chat(self, **kwargs):
            return _gen_once('{"rastgele_anahtar":"bilinmeyen_deger"}')

    a2.llm = _LLMUnknownKey()
    out2 = asyncio.run(_collect(a2._react_loop("x")))
    assert any("bilinmeyen_deger" in x for x in out2)


def test_react_loop_parallel_had_error_warning_path(monkeypatch):
    a = _make_react_ready_agent(max_steps=2)
    a.memory = SimpleNamespace(get_messages_for_llm=lambda: [], add=lambda *_: None)
    a._AUTO_PARALLEL_SAFE = {"list_dir", "health"}

    responses = [
        '[{"thought":"t1","tool":"list_dir","argument":"."},{"thought":"t2","tool":"health","argument":""}]',
        '{"thought":"done","tool":"final_answer","argument":"OK"}',
    ]

    async def _gen_once(text):
        yield text

    class _LLM:
        def __init__(self):
            self.i = 0

        async def chat(self, **kwargs):
            t = responses[self.i]
            self.i += 1
            return _gen_once(t)

    async def _exec(tool, arg):
        if tool == "list_dir":
            return "ok-list"
        raise RuntimeError("parallel boom")

    a.llm = _LLM()
    monkeypatch.setattr(a, "_execute_tool", _exec)
    out = asyncio.run(_collect(a._react_loop("x")))
    assert out[-1] == "OK"


def test_tool_read_file_large_content_and_get_config_listdir_oserror(monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(
        RAG_FILE_THRESHOLD=5,
        BASE_DIR=Path('.'),
        PROJECT_NAME='Sidar', VERSION='1.0', ACCESS_LEVEL='sandbox', DEBUG_MODE=False,
        AI_PROVIDER='ollama', USE_GPU=False, GPU_INFO='none', OLLAMA_URL='http://localhost',
        CODING_MODEL='cm', TEXT_MODEL='tm', MAX_REACT_STEPS=2, MAX_MEMORY_TURNS=5,
        CUDA_VERSION='N/A', CPU_COUNT=2, GITHUB_REPO='',
    )

    a.memory = SimpleNamespace(active_session_id='s', set_last_file=lambda *_: None)
    a.security = SimpleNamespace(level_name='sandbox')

    def _read_file(_path):
        return True, 'x' * 20

    a.code = SimpleNamespace(
        read_file=_read_file,
        get_metrics=lambda: {'files_read': 1, 'files_written': 0},
    )

    out = asyncio.run(a._tool_read_file('big.txt'))
    assert 'docs_add_file|big.txt' in out

    import os
    monkeypatch.setattr(os, 'listdir', lambda *_: (_ for _ in ()).throw(OSError('denied')))
    cfg_out = asyncio.run(a._tool_get_config(''))
    assert '[Proje Kök Dizini]' in cfg_out


def test_smart_pr_branch_not_found_and_no_changes_paths():
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(TEXT_MODEL='tm', CODING_MODEL='cm')

    class _GitHubOn:
        default_branch = 'main'
        def is_available(self):
            return True
        def create_pull_request(self, *args, **kwargs):
            return True, 'pr'

    a.github = _GitHubOn()

    class _CodeNoBranch:
        def run_shell(self, cmd):
            if 'show-current' in cmd:
                return True, ''
            return True, ''

    a.code = _CodeNoBranch()
    out1 = asyncio.run(a._tool_github_smart_pr(''))
    assert 'belirlenemedi' in out1

    class _CodeNoChanges:
        def run_shell(self, cmd):
            if 'show-current' in cmd:
                return True, 'feat/x\n'
            return True, ''

    a.code = _CodeNoChanges()
    out2 = asyncio.run(a._tool_github_smart_pr(''))
    assert 'commit edilmiş değişiklik bulunamadı' in out2



def test_react_loop_tracer_branch_and_malformed_json_scan_continue(monkeypatch):
    a = _make_react_ready_agent(max_steps=2)
    a.memory = SimpleNamespace(get_messages_for_llm=lambda: [], add=lambda *_: None)

    class _Span:
        def __init__(self):
            self.attrs = {}

        def set_attribute(self, k, v):
            self.attrs[k] = v

    class _CM:
        def __init__(self, span):
            self.span = span

        def __enter__(self):
            return self.span

        def __exit__(self, *args):
            return False

    class _Tracer:
        def __init__(self):
            self.spans = []

        def start_as_current_span(self, _name):
            s = _Span()
            self.spans.append(s)
            return _CM(s)

    async def _gen_once(text):
        yield text

    class _LLM:
        def __init__(self):
            self.i = 0
            self.payloads = [
                'prefix { bozuk JSON',
                '{"thought":"done","tool":"final_answer","argument":"ok"}',
            ]

        async def chat(self, **kwargs):
            t = self.payloads[self.i]
            self.i += 1
            return _gen_once(t)

    tr = _Tracer()
    a.tracer = tr
    a.llm = _LLM()
    out = asyncio.run(_collect(a._react_loop('x')))
    assert out[-1] == 'ok'
    assert tr.spans and 'sidar.react.llm.total_ms' in tr.spans[0].attrs


def test_github_smart_pr_default_branch_exception_falls_back_main(monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(TEXT_MODEL='tm', CODING_MODEL='cm')

    class _GH:
        def is_available(self):
            return True

        @property
        def default_branch(self):
            raise RuntimeError('boom')

        def create_pull_request(self, title, body, head, base):
            return True, f'PR:{head}->{base}'

    class _Code:
        def run_shell(self, cmd):
            if 'show-current' in cmd:
                return True, 'feat/fallback\n'
            if 'git status --short' in cmd:
                return True, ' M file.py'
            if 'git diff --stat HEAD' in cmd:
                return True, 'file.py | 1 +'
            if 'git diff --no-color HEAD' in cmd:
                return True, 'diff --git a/file.py b/file.py'
            if 'git log ' in cmd:
                assert 'main..HEAD' in cmd
                return True, 'abc test'
            return True, ''

    class _LLM:
        async def chat(self, **kwargs):
            return '{"title":"T","body":"B"}'

    a.github = _GH()
    a.code = _Code()
    a.llm = _LLM()
    out = asyncio.run(a._tool_github_smart_pr(''))
    assert 'PR oluşturuldu' in out and 'main' in out


def test_subtask_non_string_and_validationerror_feedback_then_success():
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(TEXT_MODEL='tm', CODING_MODEL='cm', SUBTASK_MAX_STEPS=4)

    class _LLM:
        def __init__(self):
            self.i = 0
            self.payloads = [
                123,
                'json yok',
                '{"thought":"t","argument":"x"}',
                '{"thought":"done","tool":"final_answer","argument":"bitti"}',
            ]

        async def chat(self, **kwargs):
            t = self.payloads[self.i]
            self.i += 1
            return t

    a.llm = _LLM()
    a._execute_tool = lambda *_: None
    out = asyncio.run(a._tool_subtask('alt görev'))
    assert 'Alt Görev Tamamlandı' in out and 'bitti' in out


def test_react_loop_plain_parse_error_valueerror_branch():
    a = _make_react_ready_agent(max_steps=1)
    a.memory = SimpleNamespace(get_messages_for_llm=lambda: [], add=lambda *_: None)

    async def _gen_once(text):
        yield text

    class _LLM:
        async def chat(self, **kwargs):
            return _gen_once('tamamen anlamsiz metin')

    a.llm = _LLM()
    out = asyncio.run(_collect(a._react_loop('x')))
    assert out[-1].startswith('Üzgünüm, bu istek için güvenilir')


def test_react_loop_malformed_json_feeds_back_parse_error_then_recovers():
    a = _make_react_ready_agent(max_steps=2)
    a.memory = SimpleNamespace(get_messages_for_llm=lambda: [], add=lambda *_: None)

    async def _gen_once(text):
        yield text

    class _LLM:
        def __init__(self):
            self.calls = []
            self.i = 0
            self.payloads = [
                'duz metin json degil',
                '{"thought":"tamam","tool":"final_answer","argument":"ok"}',
            ]

        async def chat(self, **kwargs):
            self.calls.append(kwargs)
            out = self.payloads[self.i]
            self.i += 1
            return _gen_once(out)

    llm = _LLM()
    a.llm = llm

    out = asyncio.run(_collect(a._react_loop('x')))

    assert out[-1] == 'ok'
    assert len(llm.calls) == 2
    second_messages = llm.calls[1]["messages"]
    assert any(
        "Yanıtın geçerli bir JSON formatında değil veya bozuk" in m["content"]
        for m in second_messages
        if m["role"] == "user"
    )



def test_subtask_tool_result_message_path_is_reached(monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(TEXT_MODEL='tm', CODING_MODEL='cm', SUBTASK_MAX_STEPS=2)

    class _LLM:
        def __init__(self):
            self.i = 0
            self.payloads = [
                '{"thought":"t","tool":"list_dir","argument":"."}',
                '{"thought":"d","tool":"final_answer","argument":"tamam"}',
            ]

        async def chat(self, **kwargs):
            t = self.payloads[self.i]
            self.i += 1
            return t

    async def _ok_tool(_tool, _arg):
        return 'sonuc'

    a.llm = _LLM()
    monkeypatch.setattr(a, '_execute_tool', _ok_tool)
    out = asyncio.run(a._tool_subtask('gorev'))
    assert 'Alt Görev Tamamlandı' in out


def test_archive_context_min_score_max_chars_and_empty_selected():
    a = _make_agent_for_runtime()

    class _ColLow:
        def query(self, **kwargs):
            return {
                'documents': [['d1']],
                'metadatas': [[{'source': 'memory_archive', 'title': 'T'}]],
                'distances': [[0.95]],
            }

    a.docs = SimpleNamespace(collection=_ColLow())
    out_low = a._get_memory_archive_context_sync('q', top_k=3, min_score=0.2, max_chars=1000)
    assert out_low == ''

    class _ColChars:
        def query(self, **kwargs):
            return {
                'documents': [['x' * 300, 'ikinci not']],
                'metadatas': [[
                    {'source': 'memory_archive', 'title': 'A'},
                    {'source': 'memory_archive', 'title': 'B'},
                ]],
                'distances': [[0.1, 0.1]],
            }

    a.docs = SimpleNamespace(collection=_ColChars())
    out_chars = a._get_memory_archive_context_sync('q', top_k=3, min_score=0.1, max_chars=40)
    assert out_chars == '' or 'Geçmiş Sohbet' in out_chars


def test_load_instruction_files_stat_error_is_swallowed(tmp_path, monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(BASE_DIR=tmp_path)
    a._instructions_cache = None
    a._instructions_mtimes = {}
    a._instructions_lock = threading.Lock()

    f = tmp_path / 'SIDAR.md'
    f.write_text('kural', encoding='utf-8')

    import pathlib
    real_stat = pathlib.Path.stat
    real_rglob = pathlib.Path.rglob

    def _fake_rglob(self, pattern):
        if self == tmp_path and pattern == 'SIDAR.md':
            return [f]
        if self == tmp_path and pattern == 'CLAUDE.md':
            return []
        return list(real_rglob(self, pattern))

    def _fake_is_file(self):
        if self == f:
            return True
        return pathlib.Path.exists(self)

    def _boom_stat(self):
        if self.name == 'SIDAR.md':
            raise OSError('stat fail')
        return real_stat(self)

    monkeypatch.setattr(pathlib.Path, 'rglob', _fake_rglob)
    monkeypatch.setattr(pathlib.Path, 'is_file', _fake_is_file)
    monkeypatch.setattr(pathlib.Path, 'stat', _boom_stat)
    out = a._load_instruction_files()
    assert 'SIDAR.md' in out and 'kural' in out


def test_react_loop_tool_result_none_feeds_error_and_continues(monkeypatch):
    """_execute_tool None döndürdüğünde (bilinmeyen araç) hata mesajı
    konuşmaya eklenmeli ve döngü devam etmelidir (satır 450-457)."""
    a = _make_react_ready_agent(max_steps=3)

    class _Mem:
        def get_messages_for_llm(self):
            return []

        def add(self, *_):
            pass

    a.memory = _Mem()

    async def _gen_once(text):
        yield text

    class _LLM:
        def __init__(self):
            self.i = 0
            self.payloads = [
                '{"thought":"deneme","tool":"bilinmeyen_arac","argument":"x"}',
                '{"thought":"bitti","tool":"final_answer","argument":"tamam"}',
            ]

        async def chat(self, **kwargs):
            text = self.payloads[self.i % len(self.payloads)]
            self.i += 1
            return _gen_once(text)

    a.llm = _LLM()

    async def _exec_none(tool, arg):
        return None

    monkeypatch.setattr(a, "_execute_tool", _exec_none)

    out = asyncio.run(_collect(a._react_loop("test")))
    assert out[-1] == "tamam"

def test_try_multi_agent_always_uses_supervisor(monkeypatch):
    mod = _load_sidar_agent_module()

    class _Sup:
        async def run_task(self, prompt: str) -> str:
            return f"ok:{prompt}"

    a = SimpleNamespace(
        cfg=SimpleNamespace(),
        _supervisor=_Sup(),
    )

    out1 = asyncio.run(mod.SidarAgent._try_multi_agent(a, "gorev1"))
    out2 = asyncio.run(mod.SidarAgent._try_multi_agent(a, "gorev2"))

    assert out1 == "ok:gorev1"
    assert out2 == "ok:gorev2"


def test_try_multi_agent_uses_supervisor_when_enabled(monkeypatch):
    mod = _load_sidar_agent_module()

    class _Sup:
        async def run_task(self, prompt: str) -> str:
            return f"ok:{prompt}"

    a = SimpleNamespace(
        cfg=SimpleNamespace(),
        _supervisor=_Sup(),
    )

    out = asyncio.run(mod.SidarAgent._try_multi_agent(a, "gorev"))
    assert out == "ok:gorev"

def test_respond_supervisor_single_path_ignores_legacy_react(monkeypatch):
    a = _make_agent_for_runtime()

    async def fake_multi(_):
        return "only-supervisor"

    a._try_multi_agent = fake_multi

    async def _legacy_fail(*args, **kwargs):
        raise AssertionError("legacy react path should not be called")

    monkeypatch.setattr(a, "_react_loop", _legacy_fail, raising=False)

    out = asyncio.run(_collect(a.respond("test")))
    assert out == ["only-supervisor"]
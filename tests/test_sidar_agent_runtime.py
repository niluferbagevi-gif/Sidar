import asyncio
import importlib.util
import json
import sys
import types
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
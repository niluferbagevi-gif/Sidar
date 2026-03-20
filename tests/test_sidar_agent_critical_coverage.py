import asyncio
import builtins
import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def _load_sidar_agent_module(force_otel_import_error=False):
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
        "agent.definitions": types.ModuleType("agent.definitions"),
        "agent.core.contracts": types.ModuleType("agent.core.contracts"),
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

    stubs["pydantic"].BaseModel = BaseModel
    stubs["pydantic"].Field = lambda *a, **k: None
    stubs["pydantic"].ValidationError = ValidationError
    stubs["config"].Config = type("Config", (), {})

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
    ):
        setattr(stubs[mod_name], cls_name, object)

    stubs["agent.definitions"].SIDAR_SYSTEM_PROMPT = "sys"

    class ExternalTrigger:
        def __init__(self, trigger_id="", source="", event_name="", payload=None, meta=None):
            self.trigger_id = trigger_id
            self.source = source
            self.event_name = event_name
            self.payload = payload or {}
            self.meta = meta or {}

        def to_prompt(self):
            return f"[TRIGGER]\nsource={self.source}\nevent={self.event_name}"

    stubs["agent.core.contracts"].ExternalTrigger = ExternalTrigger

    saved = {k: sys.modules.get(k) for k in stubs}
    saved_import = builtins.__import__

    def _patched_import(name, *args, **kwargs):
        if force_otel_import_error and name == "opentelemetry":
            raise ImportError("boom")
        return saved_import(name, *args, **kwargs)

    try:
        for k, v in stubs.items():
            sys.modules[k] = v
        if force_otel_import_error:
            builtins.__import__ = _patched_import

        spec = importlib.util.spec_from_file_location("sidar_agent_cov", Path("agent/sidar_agent.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        builtins.__import__ = saved_import
        for k, old in saved.items():
            if old is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = old


MOD = _load_sidar_agent_module()
SidarAgent = MOD.SidarAgent


def test_module_import_sets_trace_none_when_opentelemetry_missing():
    mod = _load_sidar_agent_module(force_otel_import_error=True)
    assert mod.trace is None


def test_sidar_agent_module_fallback_contract_helpers_build_prompts():
    mod = _load_sidar_agent_module()

    assert mod._default_derive_correlation_id(None, "  ", "corr-1", "corr-2") == "corr-1"
    assert mod._default_derive_correlation_id(None, "  ") == ""

    envelope = mod._FallbackFederationTaskEnvelope(
        task_id="fed-1",
        source_system="crewai",
        source_agent="planner",
        target_system="sidar",
        target_agent="supervisor",
        goal="Plan üret",
        context={"repo": "Sidar"},
        inputs=["issue #1"],
        meta={"correlation_id": "meta-corr"},
    )
    feedback = mod._FallbackActionFeedback(
        feedback_id="fb-1",
        source_system="crewai",
        source_agent="planner",
        action_name="open_pr",
        status="success",
        summary="PR açıldı",
        details={"number": 7},
        meta={"correlation_id": "fb-corr"},
    )

    assert envelope.correlation_id == "meta-corr"
    assert "protocol=federation.v1" in envelope.to_prompt()
    assert '"repo": "Sidar"' in envelope.to_prompt()
    assert feedback.correlation_id == "fb-corr"
    assert "action_name=open_pr" in feedback.to_prompt()
    assert '"number": 7' in feedback.to_prompt()


def test_initialize_lock_and_idempotent_memory_init():
    agent = SidarAgent.__new__(SidarAgent)
    agent._initialized = False
    agent._init_lock = None

    class _Mem:
        def __init__(self):
            self.calls = 0

        async def initialize(self):
            self.calls += 1
            await asyncio.sleep(0)

    agent.memory = _Mem()

    async def _run():
        await asyncio.gather(agent.initialize(), agent.initialize())

    asyncio.run(_run())
    assert agent._initialized is True
    assert agent._init_lock is not None
    assert agent.memory.calls == 1


def test_get_memory_archive_context_defaults_are_applied(monkeypatch):
    agent = SidarAgent.__new__(SidarAgent)
    agent.cfg = SimpleNamespace()
    got = {}

    async def fake_to_thread(func, *args):
        got["func"] = func
        got["args"] = args
        return "ctx"

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    agent._get_memory_archive_context_sync = lambda *a: "unused"

    out = asyncio.run(agent._get_memory_archive_context("sorgu"))
    assert out == "ctx"
    assert got["args"] == ("sorgu", 3, 0.35, 1500)


def test_tool_docs_search_handles_pipe_mode_and_coroutine_result(monkeypatch):
    agent = SidarAgent.__new__(SidarAgent)

    async def _result():
        return True, "found"

    class _Docs:
        def search(self, query, _none, mode, session_id):
            assert query == "needle"
            assert mode == "semantic"
            assert session_id == "global"
            return _result()

    async def passthrough(func, *args):
        return func(*args)

    agent.docs = _Docs()
    monkeypatch.setattr(asyncio, "to_thread", passthrough)

    assert "belirtilmedi" in asyncio.run(agent._tool_docs_search("  "))
    assert asyncio.run(agent._tool_docs_search("needle|semantic")) == "found"


def test_tool_subtask_covers_validation_exception_and_max_steps():
    agent = SidarAgent.__new__(SidarAgent)
    agent.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=3, TEXT_MODEL="tm", CODING_MODEL="cm")

    replies = iter([
        123,
        '{"thought":"t","tool":"x"}',
        RuntimeError("llm down"),
    ])

    class _Llm:
        async def chat(self, **kwargs):
            v = next(replies)
            if isinstance(v, Exception):
                raise v
            return v

    async def _exec(_tool, _arg):
        return "ok"

    agent.llm = _Llm()
    agent._execute_tool = _exec

    out = asyncio.run(agent._tool_subtask("görev"))
    assert "Maksimum adım" in out


def test_tool_github_smart_pr_covers_fallbacks_and_failures():
    agent = SidarAgent.__new__(SidarAgent)

    class _Code:
        def __init__(self):
            self.calls = []

        def run_shell(self, cmd):
            self.calls.append(cmd)
            mapping = {
                "git branch --show-current": (True, "feat-x\n"),
                "git status --short": (True, " M a.py"),
                "git diff --stat HEAD": (True, "stat"),
                "git diff --no-color HEAD": (True, "x" * 11000),
                "git log --oneline main..HEAD": (True, "abc msg"),
            }
            return mapping.get(cmd, (False, ""))

    class _Github:
        def is_available(self):
            return True

        @property
        def default_branch(self):
            raise RuntimeError("no default")

        def create_pull_request(self, title, body, head, base):
            assert title == "Başlık"
            assert head == "feat-x"
            assert base == "main"
            assert "kırpıldı" in body
            return False, "api error"

    agent.code = _Code()
    agent.github = _Github()
    out = asyncio.run(agent._tool_github_smart_pr("Başlık||| |||not"))
    assert "oluşturulamadı" in out


def test_tool_github_smart_pr_token_branch_and_clean_status_paths():
    agent = SidarAgent.__new__(SidarAgent)

    class _Github:
        def __init__(self, available):
            self.available = available

        def is_available(self):
            return self.available

        default_branch = "main"

    class _Code:
        def __init__(self, branch_ok=True, status=""):
            self.branch_ok = branch_ok
            self.status = status

        def run_shell(self, cmd):
            if cmd == "git branch --show-current":
                return (self.branch_ok, "main" if self.branch_ok else "")
            if cmd == "git status --short":
                return True, self.status
            return True, ""

    agent.github = _Github(False)
    agent.code = _Code()
    assert "token" in asyncio.run(agent._tool_github_smart_pr(""))

    agent.github = _Github(True)
    agent.code = _Code(branch_ok=False)
    assert "Aktif branch" in asyncio.run(agent._tool_github_smart_pr(""))

    agent.code = _Code(branch_ok=True, status="")
    assert "Değişiklik bulunamadı" in asyncio.run(agent._tool_github_smart_pr(""))


def test_summarize_memory_handles_both_exception_blocks(monkeypatch):
    agent = SidarAgent.__new__(SidarAgent)
    agent.cfg = SimpleNamespace(TEXT_MODEL="tm", CODING_MODEL="cm")

    class _Mem:
        async def get_history(self):
            return [
                {"role": "user", "content": "a", "timestamp": 1},
                {"role": "assistant", "content": "b", "timestamp": 1},
                {"role": "user", "content": "c", "timestamp": 1},
                {"role": "assistant", "content": "d", "timestamp": 1},
            ]

        async def apply_summary(self, _summary):
            raise AssertionError("should not be called")

    class _Docs:
        def add_document(self, **kwargs):
            raise RuntimeError("db fail")

    class _Llm:
        async def chat(self, **kwargs):
            raise RuntimeError("llm fail")

    async def passthrough(func, *args, **kwargs):
        return func(*args, **kwargs)

    agent.memory = _Mem()
    agent.docs = _Docs()
    agent.llm = _Llm()
    monkeypatch.setattr(asyncio, "to_thread", passthrough)

    asyncio.run(agent._summarize_memory())


def test_build_context_uses_gemini_line_for_non_ollama_provider(tmp_path):
    agent = SidarAgent.__new__(SidarAgent)
    agent.cfg = SimpleNamespace(
        PROJECT_NAME="P",
        VERSION="1",
        BASE_DIR=tmp_path,
        AI_PROVIDER="gemini",
        GEMINI_MODEL="g-1.5",
        ACCESS_LEVEL="sandbox",
        USE_GPU=False,
        GPU_INFO="cpu",
        CUDA_VERSION="N/A",
        GITHUB_REPO="o/r",
    )
    agent.security = SimpleNamespace(level_name="sandbox")
    agent.github = SimpleNamespace(is_available=lambda: False)
    agent.web = SimpleNamespace(is_available=lambda: False)
    agent.docs = SimpleNamespace(status=lambda: "ok")
    agent.code = SimpleNamespace(get_metrics=lambda: {"files_read": 0, "files_written": 0})
    agent.memory = SimpleNamespace(get_last_file=lambda: "")

    class _Todo:
        def __len__(self):
            return 0

    agent.todo = _Todo()
    agent._instructions_cache = ""
    agent._instructions_mtimes = {}
    import threading

    agent._instructions_lock = threading.Lock()

    ctx = asyncio.run(agent._build_context())
    assert "Gemini Modeli: g-1.5" in ctx

def test_build_context_truncates_for_local_provider(tmp_path):
    agent = SidarAgent.__new__(SidarAgent)
    agent.cfg = SimpleNamespace(
        PROJECT_NAME="P",
        VERSION="1",
        BASE_DIR=tmp_path,
        AI_PROVIDER="ollama",
        CODING_MODEL="qwen",
        TEXT_MODEL="qwen",
        OLLAMA_URL="http://localhost:11434/api",
        ACCESS_LEVEL="sandbox",
        USE_GPU=False,
        GPU_INFO="cpu",
        CUDA_VERSION="N/A",
        GITHUB_REPO="o/r",
        LOCAL_INSTRUCTION_MAX_CHARS=100,
        LOCAL_AGENT_CONTEXT_MAX_CHARS=350,
    )
    agent.security = SimpleNamespace(level_name="sandbox")
    agent.github = SimpleNamespace(is_available=lambda: False)
    agent.web = SimpleNamespace(is_available=lambda: False)
    agent.docs = SimpleNamespace(status=lambda: "ok")
    agent.code = SimpleNamespace(get_metrics=lambda: {"files_read": 10, "files_written": 2})
    agent.memory = SimpleNamespace(get_last_file=lambda: "very/long/path.py")

    class _Todo:
        def __len__(self):
            return 0

    agent.todo = _Todo()
    agent._instructions_cache = ""
    agent._instructions_mtimes = {}
    import threading

    agent._instructions_lock = threading.Lock()
    agent._load_instruction_files = lambda: "X" * 1000

    ctx = asyncio.run(agent._build_context())
    assert "[Not]" in ctx
    assert "Dizin" not in ctx
    assert "Ollama URL" not in ctx
    assert "Okunan" not in ctx
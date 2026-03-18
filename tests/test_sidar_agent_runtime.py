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
    a._initialized = True
    a._init_lock = None
    a.tracer = None
    a._tools = {}

    class _Mem:
        def __init__(self):
            self.items = []

        async def add(self, role, text):
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

        async def add(self, role, text):
            self.items.append((role, text))

        async def clear(self):
            self.items.clear()

        def __len__(self):
            return 3

    a.security = _Sec()
    a.memory = _Mem()

    changed = asyncio.run(a.set_access_level("full"))
    assert "güncellendi" in changed
    unchanged = asyncio.run(a.set_access_level("restricted"))
    assert "zaten" in unchanged

    assert "temizlendi" in asyncio.run(a.clear_memory())

    status = a.status()
    assert "SidarAgent" in status
    assert "Sağlayıcı" in status
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

    ctx = asyncio.run(a._build_context())
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

        async def get_history(self):
            return [
                {"role": "user", "content": "u1", "timestamp": 1},
                {"role": "assistant", "content": "a1", "timestamp": 2},
                {"role": "user", "content": "u2", "timestamp": 3},
                {"role": "assistant", "content": "a2", "timestamp": 4},
            ]

        async def apply_summary(self, s):
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


def test_summarize_memory_logs_vector_archive_success(monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(TEXT_MODEL="tm", CODING_MODEL="cm")

    class _Mem:
        def __init__(self):
            self.summary = None

        async def get_history(self):
            return [
                {"role": "user", "content": "u1", "timestamp": 1},
                {"role": "assistant", "content": "a1", "timestamp": 2},
                {"role": "user", "content": "u2", "timestamp": 3},
                {"role": "assistant", "content": "a2", "timestamp": 4},
            ]

        async def apply_summary(self, s):
            self.summary = s

    class _Docs:
        def __init__(self):
            self.calls = []

        async def add_document(self, **kwargs):
            self.calls.append(kwargs)
            return "doc-1"

    class _LLM:
        async def chat(self, **kwargs):
            return "özet"

    infos = []
    monkeypatch.setattr(SA_MOD.logger, "info", lambda msg, *args: infos.append(msg % args if args else msg))

    a.memory = _Mem()
    a.docs = _Docs()
    a.llm = _LLM()

    asyncio.run(a._summarize_memory())

    assert a.docs.calls and a.docs.calls[0]["source"] == "memory_archive"
    assert a.memory.summary == "özet"
    assert any("RAG (Vektör) belleğine arşivlendi" in msg for msg in infos)


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

    async def _short_history():
        return [{"role": "u", "content": "x"}] * 3

    b.memory = SimpleNamespace(get_history=_short_history)
    asyncio.run(b._summarize_memory())
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


def test_load_instruction_files_permission_error_on_one_file_is_ignored(tmp_path, monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(BASE_DIR=tmp_path)
    a._instructions_cache = None
    a._instructions_mtimes = {}
    a._instructions_lock = threading.Lock()

    readable = tmp_path / "SIDAR.md"
    readable.write_text("root rules", encoding="utf-8")
    denied = tmp_path / "CLAUDE.md"
    denied.write_text("secret", encoding="utf-8")

    real_read_text = Path.read_text

    def _read_text(self, *args, **kwargs):
        if self.name == "CLAUDE.md":
            raise PermissionError("permission denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _read_text)

    out = a._load_instruction_files()
    assert "SIDAR.md" in out
    assert "root rules" in out
    assert "secret" not in out

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
def test_memory_archive_context_stops_at_top_k_break():
    a = _make_agent_for_runtime()

    class _Collection:
        def query(self, **kwargs):
            return {
                "documents": [["ilk belge", "ikinci belge"]],
                "metadatas": [[
                    {"source": "memory_archive", "title": "T1"},
                    {"source": "memory_archive", "title": "T2"},
                ]],
                "distances": [[0.1, 0.2]],
            }

    a.docs = SimpleNamespace(collection=_Collection())

    out = a._get_memory_archive_context_sync("q", top_k=1, min_score=0.1, max_chars=2000)
    assert "Geçmiş Sohbet Arşivinden İlgili Notlar" in out
    assert "T1" in out
    assert "T2" not in out


def test_tool_subtask_validation_error_and_tool_exception_paths():
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=2, TEXT_MODEL="tm", CODING_MODEL="cm")

    replies = iter([
        '{"thought":"eksik","tool":"list_dir"}',
        '{"thought":"done","tool":"final_answer","argument":"kurtarıldı"}',
    ])

    class _LLMValidation:
        async def chat(self, **kwargs):
            return next(replies)

    async def _should_not_run(_tool, _arg):
        raise AssertionError("tool should not execute on schema failure")

    a.llm = _LLMValidation()
    a._execute_tool = _should_not_run

    out = asyncio.run(a._tool_subtask("şema testi"))
    assert out == "✓ Alt Görev Tamamlandı: kurtarıldı"

    a2 = _make_agent_for_runtime()
    a2.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=2, TEXT_MODEL="tm", CODING_MODEL="cm")
    replies2 = iter([
        '{"thought":"t","tool":"dangerous","argument":"bad-param"}',
        '{"thought":"done","tool":"final_answer","argument":"tamam"}',
    ])

    class _LLMToolError:
        async def chat(self, **kwargs):
            return next(replies2)

    calls = []

    async def _boom(tool, arg):
        calls.append((tool, arg))
        raise RuntimeError("unexpected db response")

    a2.llm = _LLMToolError()
    a2._execute_tool = _boom

    out2 = asyncio.run(a2._tool_subtask("araç hatası"))
    assert out2 == "✓ Alt Görev Tamamlandı: tamam"
    assert calls == [("dangerous", "bad-param")]


def test_tool_subtask_returns_max_steps_after_non_string_llm_output():
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=1, TEXT_MODEL="tm", CODING_MODEL="cm")

    class _LLM:
        async def chat(self, **kwargs):
            return {"tool": "list_dir"}

    a.llm = _LLM()
    a._execute_tool = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not run"))

    out = asyncio.run(a._tool_subtask("ham çıktı"))
    assert "Maksimum adım sınırına ulaşıldı" in out


def test_tool_subtask_empty_and_execute_tool_then_final_answer():
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=4, TEXT_MODEL="tm", CODING_MODEL="cm")

    assert "Alt görev belirtilmedi" in asyncio.run(a._tool_subtask("   "))

    replies = iter([
        '{"thought":"t","tool":"list_dir","argument":"."}',
        '{"thought":"done","tool":"final_answer","argument":"tamam"}',
    ])

    class _LLM:
        async def chat(self, **kwargs):
            return next(replies)

    calls = {"n": 0}

    async def _exec(tool, arg):
        calls["n"] += 1
        return f"ok:{tool}:{arg}"

    a.llm = _LLM()
    a._execute_tool = _exec

    out = asyncio.run(a._tool_subtask("alt görev"))
    assert out == "✓ Alt Görev Tamamlandı: tamam"
    assert calls["n"] == 1


def test_tool_github_smart_pr_success_branch_returns_created_message():
    a = _make_agent_for_runtime()

    class _Code:
        def run_shell(self, cmd):
            mapping = {
                "git branch --show-current": (True, "feat-1\n"),
                "git status --short": (True, " M a.py"),
                "git diff --stat HEAD": (True, "stat"),
                "git diff --no-color HEAD": (True, "diff"),
                "git log --oneline main..HEAD": (True, "abc msg"),
            }
            return mapping.get(cmd, (False, ""))

    class _Github:
        def is_available(self):
            return True

        default_branch = "main"

        def create_pull_request(self, title, body, head, base):
            return True, "https://example/pr/1"

    a.code = _Code()
    a.github = _Github()

    out = asyncio.run(a._tool_github_smart_pr("Başlık|||main|||not"))
    assert out == "✓ PR oluşturuldu: https://example/pr/1"

def test_initialize_applies_active_system_prompt_from_memory_db():
    a = _make_agent_for_runtime()
    a._initialized = False
    a._init_lock = asyncio.Lock()
    a.system_prompt = "default"

    class _Prompt:
        prompt_text = "  özel prompt  "

    class _DB:
        async def get_active_prompt(self, _name):
            return _Prompt()

    class _Mem:
        db = _DB()

        async def initialize(self):
            return None

    a.memory = _Mem()
    asyncio.run(a.initialize())
    assert a.system_prompt == "  özel prompt  "


def test_build_context_includes_last_file_for_remote_provider(tmp_path):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(
        PROJECT_NAME="Sidar",
        VERSION="3.0",
        BASE_DIR=tmp_path,
        AI_PROVIDER="openai",
        CODING_MODEL="code",
        TEXT_MODEL="text",
        OLLAMA_URL="http://localhost:11434",
        ACCESS_LEVEL="full",
        USE_GPU=True,
        GPU_INFO="RTX",
        CUDA_VERSION="12.0",
        GITHUB_REPO="org/repo",
        GEMINI_MODEL="gemini",
    )
    a.code = SimpleNamespace(get_metrics=lambda: {"files_read": 1, "files_written": 1})
    a.github = SimpleNamespace(is_available=lambda: True)
    a.web = SimpleNamespace(is_available=lambda: True)
    a.docs = SimpleNamespace(status=lambda: "ok")
    a.security = SimpleNamespace(level_name="full")
    a.todo = []
    a.memory = SimpleNamespace(get_last_file=lambda: "demo.py")
    a._instructions_lock = threading.Lock()
    a._instructions_cache = None
    a._instructions_mtimes = {}
    a._load_instruction_files = lambda: ""

    txt = asyncio.run(a._build_context())
    assert "Son dosya  : demo.py" in txt


def test_build_context_treats_mixed_case_ollama_as_local_provider(tmp_path):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(
        PROJECT_NAME="Sidar",
        VERSION="3.0",
        BASE_DIR=tmp_path,
        AI_PROVIDER="Ollama",
        CODING_MODEL="code",
        TEXT_MODEL="text",
        OLLAMA_URL="http://localhost:11434",
        ACCESS_LEVEL="full",
        USE_GPU=True,
        GPU_INFO="RTX",
        CUDA_VERSION="12.0",
        GITHUB_REPO="org/repo",
        GEMINI_MODEL="gemini",
        LOCAL_AGENT_CONTEXT_MAX_CHARS=5000,
        LOCAL_INSTRUCTION_MAX_CHARS=5000,
    )
    a.code = SimpleNamespace(get_metrics=lambda: {"files_read": 1, "files_written": 1})
    a.github = SimpleNamespace(is_available=lambda: True)
    a.web = SimpleNamespace(is_available=lambda: True)
    a.docs = SimpleNamespace(status=lambda: "ok")
    a.security = SimpleNamespace(level_name="full")
    a.todo = []
    a.memory = SimpleNamespace(get_last_file=lambda: "demo.py")
    a._instructions_lock = threading.Lock()
    a._instructions_cache = None
    a._instructions_mtimes = {}
    a._load_instruction_files = lambda: ""

    txt = asyncio.run(a._build_context())
    assert "Coding Modeli: code" in txt
    assert "Text Modeli  : text" in txt
    assert "Gemini Modeli:" not in txt
    assert "Ollama URL" not in txt
    assert "Son dosya  : demo.py" not in txt


def test_build_context_truncates_for_local_provider(tmp_path):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(
        PROJECT_NAME="Sidar",
        VERSION="3.0",
        BASE_DIR=tmp_path,
        AI_PROVIDER="ollama",
        CODING_MODEL="code",
        TEXT_MODEL="text",
        OLLAMA_URL="http://localhost:11434",
        ACCESS_LEVEL="full",
        USE_GPU=True,
        GPU_INFO="RTX",
        CUDA_VERSION="12.0",
        GITHUB_REPO="org/repo",
        GEMINI_MODEL="gemini",
        LOCAL_AGENT_CONTEXT_MAX_CHARS=300,
        LOCAL_INSTRUCTION_MAX_CHARS=5000,
    )
    a.code = SimpleNamespace(get_metrics=lambda: {"files_read": 1, "files_written": 1})
    a.github = SimpleNamespace(is_available=lambda: True)
    a.web = SimpleNamespace(is_available=lambda: True)
    a.docs = SimpleNamespace(status=lambda: "ok")
    a.security = SimpleNamespace(level_name="full")
    a.todo = []
    a.memory = SimpleNamespace(get_last_file=lambda: "demo.py")
    a._instructions_lock = threading.Lock()
    a._instructions_cache = None
    a._instructions_mtimes = {}
    a._load_instruction_files = lambda: "X" * 6000

    txt = asyncio.run(a._build_context())
    assert txt.endswith("[Not] Bağlam yerel model için kırpıldı.")
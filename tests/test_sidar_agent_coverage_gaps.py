import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace


from tests.test_sidar_agent_runtime import (
    SA_MOD,
    _collect,
    _load_sidar_agent_module,
    _make_agent_for_runtime,
    _make_react_ready_agent,
)


def test_module_import_falls_back_when_opentelemetry_trace_unavailable(monkeypatch):
    fake_otel = types.ModuleType("opentelemetry")
    saved = sys.modules.get("opentelemetry")
    sys.modules["opentelemetry"] = fake_otel
    try:
        mod = _load_sidar_agent_module()
        assert mod.trace is None
    finally:
        if saved is None:
            sys.modules.pop("opentelemetry", None)
        else:
            sys.modules["opentelemetry"] = saved


def test_react_loop_tracer_and_exception_paths(monkeypatch):
    a = _make_react_ready_agent(max_steps=1)
    a.memory = SimpleNamespace(get_messages_for_llm=lambda: [], add=lambda *_: None)

    class _Span:
        def __init__(self):
            self.attrs = {}

        def set_attribute(self, k, v):
            self.attrs[k] = v

    span = _Span()

    class _CM:
        def __enter__(self):
            return span

        def __exit__(self, *_):
            return False

    class _Tracer:
        def start_as_current_span(self, _name):
            return _CM()

    async def _gen_once(txt):
        yield txt

    class _LLM:
        async def chat(self, **kwargs):
            return _gen_once('prefix {"thought":"t","tool":"boom","argument":"x"}')

    async def _boom(_tool, _arg):
        raise RuntimeError("tool failed")

    a.tracer = _Tracer()
    a.llm = _LLM()
    monkeypatch.setattr(a, "_execute_tool", _boom)

    out = asyncio.run(_collect(a._react_loop("x")))
    assert out == ["\x00THOUGHT:t\x00", "\x00TOOL:boom\x00", "Üzgünüm, yanıt üretirken beklenmeyen bir hata oluştu."]
    assert "sidar.react.llm.total_ms" in span.attrs


def test_react_loop_alias_and_parallel_validation_feedback():
    a = _make_react_ready_agent(max_steps=3)
    mem_msgs = []

    class _Mem:
        def get_messages_for_llm(self):
            return mem_msgs

        def add(self, *_):
            return None

    a.memory = _Mem()

    async def _gen_once(txt):
        yield txt

    class _LLM:
        def __init__(self):
            self.i = 0
            self.payloads = [
                '[{"thought":"x","tool":"final_answer","argument":"a"},{"thought":"y","tool":"list_dir","argument":"."}]',
                '[{"thought":"x","tool":"write_file","argument":"a"},{"thought":"y","tool":"list_dir","argument":"."}]',
                '{"response":"tamam"}',
            ]

        async def chat(self, **kwargs):
            p = self.payloads[self.i]
            self.i += 1
            return _gen_once(p)

    a.llm = _LLM()

    out = asyncio.run(_collect(a._react_loop("x")))
    assert out[-1] == "tamam"


def test_specific_tool_guard_paths_and_build_tool_list_dedup(tmp_path):
    a = _make_agent_for_runtime()

    # write/patch schema branches
    wf = SA_MOD.WriteFileSchema()
    wf.path = " a.py "
    wf.content = "print(1)"
    a.code = SimpleNamespace(
        write_file=lambda p, c: (True, f"write:{p}:{c}"),
        patch_file=lambda p, o, n: (True, f"patch:{p}:{o}:{n}"),
    )
    assert asyncio.run(a._tool_write_file(wf)) == "write:a.py:print(1)"

    pf = SA_MOD.PatchFileSchema()
    pf.path = " f.py "
    pf.old_text = "old"
    pf.new_text = "new"
    assert asyncio.run(a._tool_patch_file(pf)) == "patch:f.py:old:new"

    # github unavailable branches
    a.github = SimpleNamespace(
        is_available=lambda: False,
        list_issues=lambda *_: (False, []),
    )
    c_arg = SA_MOD.GithubCommentIssueSchema(); c_arg.number = 1; c_arg.body = "a"
    cl_arg = SA_MOD.GithubCloseIssueSchema(); cl_arg.number = 1
    d_arg = SA_MOD.GithubPRDiffSchema(); d_arg.number = 1
    assert "token" in asyncio.run(a._tool_github_comment_issue(c_arg))
    assert "token" in asyncio.run(a._tool_github_close_issue(cl_arg))
    assert "token" in asyncio.run(a._tool_github_pr_diff(d_arg))

    # list issues fail/empty branches
    a.github = SimpleNamespace(
        is_available=lambda: True,
        list_issues=lambda *_: (False, ["boom"]),
    )
    assert asyncio.run(a._tool_github_list_issues("open|||10")) == "boom"
    a.github = SimpleNamespace(
        is_available=lambda: True,
        list_issues=lambda *_: (True, []),
    )
    assert "bulunmuyor" in asyncio.run(a._tool_github_list_issues("open|||10"))

    # build tool list and dedupe
    async def _h(_):
        """Deneme doc satırı\nalt satır"""
        return "ok"

    a._tools = {"x": _h, "y": _h}
    tl = a._build_tool_list()
    assert tl.count("Deneme doc satırı") == 1


def test_memory_archive_filters_and_async_wrapper_and_context_gemini(tmp_path):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(
        MEMORY_ARCHIVE_TOP_K=2,
        MEMORY_ARCHIVE_MIN_SCORE=0.5,
        MEMORY_ARCHIVE_MAX_CHARS=320,
        PROJECT_NAME="P",
        VERSION="1",
        BASE_DIR=tmp_path,
        AI_PROVIDER="gemini",
        CODING_MODEL="cm",
        TEXT_MODEL="tm",
        OLLAMA_URL="http://x",
        ACCESS_LEVEL="sandbox",
        USE_GPU=False,
        GPU_INFO="none",
        CUDA_VERSION="N/A",
        GITHUB_REPO="r",
        GEMINI_MODEL="g-1",
    )

    class _Collection:
        def query(self, **kwargs):
            return {
                "documents": [["x", "", "keep this"]],
                "metadatas": [[
                    {"source": "other", "title": "skip"},
                    {"source": "memory_archive", "title": "empty"},
                    {"source": "memory_archive", "title": "good"},
                ]],
                "distances": [[0.1, 0.2, 0.4]],
            }

    a.docs = SimpleNamespace(collection=_Collection(), status=lambda: "ok")
    text = asyncio.run(a._get_memory_archive_context("q"))
    assert "good" in text and "skip" not in text

    a.code = SimpleNamespace(get_metrics=lambda: {"files_read": 0, "files_written": 0})
    a.github = SimpleNamespace(is_available=lambda: False)
    a.web = SimpleNamespace(is_available=lambda: False)
    a.todo = []
    a.memory = SimpleNamespace(get_last_file=lambda: "")
    a.security = SimpleNamespace(level_name="sandbox")
    a._load_instruction_files = lambda: ""
    ctx = a._build_context()
    assert "Gemini Modeli" in ctx


def test_get_config_oserror_gpu_true_and_instruction_file_exceptions(monkeypatch, tmp_path):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(
        BASE_DIR=tmp_path,
        USE_GPU=True,
        GPU_INFO="RTX",
        GPU_COUNT=2,
        CUDA_VERSION="12",
        MEMORY_ENCRYPTION_KEY="k",
        PROJECT_NAME="P",
        VERSION="1",
        ACCESS_LEVEL="sandbox",
        DEBUG_MODE=False,
        AI_PROVIDER="ollama",
        OLLAMA_URL="http://x",
        CODING_MODEL="cm",
        TEXT_MODEL="tm",
        MAX_REACT_STEPS=2,
        MAX_MEMORY_TURNS=5,
    )

    import os
    monkeypatch.setattr(os, "listdir", lambda *_: (_ for _ in ()).throw(OSError("denied")))
    cfg_txt = asyncio.run(a._tool_get_config(""))
    assert "RTX" in cfg_txt

    # load_instruction stat/read exceptions + cache path
    a._instructions_cache = None
    a._instructions_mtimes = {}
    import threading
    a._instructions_lock = threading.Lock()

    good = tmp_path / "SIDAR.md"
    good.write_text("ok", encoding="utf-8")
    bad = tmp_path / "CLAUDE.md"
    bad.write_text("bad", encoding="utf-8")
    bad.unlink()  # rglob sonrası stat döngüsünde hata üretmesi için

    real_read = Path.read_text

    def _read(self, *args, **kwargs):
        if self.name == "SIDAR.md":
            raise OSError("read")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _read)
    assert a._load_instruction_files() == ""

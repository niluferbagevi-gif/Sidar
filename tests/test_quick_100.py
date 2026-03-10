import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch


def _load_module(module_name: str, file_path: str, stubs: dict[str, object] | None = None):
    stubs = stubs or {}
    saved = {k: sys.modules.get(k) for k in stubs}
    try:
        for k, v in stubs.items():
            sys.modules[k] = v
        spec = importlib.util.spec_from_file_location(module_name, Path(file_path))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k in stubs:
            if saved[k] is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = saved[k]


def test_config_vram_fraction_exception(monkeypatch):
    dotenv_mod = types.ModuleType("dotenv")
    dotenv_mod.load_dotenv = lambda *a, **k: None
    cfg = _load_module("config_quick100_vram", "config.py", {"dotenv": dotenv_mod})

    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(
        is_available=lambda: True,
        device_count=lambda: 1,
        get_device_name=lambda _i: "Test GPU",
        set_per_process_memory_fraction=lambda *_a, **_k: (_ for _ in ()).throw(Exception("Simulated VRAM Error")),
    )
    fake_torch.version = types.SimpleNamespace(cuda="12.x")

    torch_saved = sys.modules.get("torch")
    sys.modules["torch"] = fake_torch
    try:
        with patch.object(cfg, "get_bool_env", return_value=True):
            info = cfg.check_hardware()
            assert info.has_cuda is True
            assert info.gpu_name == "Test GPU"
    finally:
        if torch_saved is None:
            sys.modules.pop("torch", None)
        else:
            sys.modules["torch"] = torch_saved


def test_tooling_missing_branches():
    fake_pydantic = types.ModuleType("pydantic")

    class _BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

        @classmethod
        def model_validate(cls, payload):
            return cls(**payload)

        @classmethod
        def model_rebuild(cls):
            return None

    fake_pydantic.BaseModel = _BaseModel
    fake_pydantic.Field = lambda default=None, **kwargs: default

    tooling = _load_module("agent_tooling_quick100_missing", "agent/tooling.py", {"pydantic": fake_pydantic})

    with __import__("pytest").raises(ValueError):
        tooling.parse_tool_argument("github_create_branch", " ||| main")
    with __import__("pytest").raises(ValueError):
        tooling.parse_tool_argument("github_close_issue", "|||1")


def test_auto_handle_validate_unsupported():
    code_mgr = types.ModuleType("managers.code_manager")
    code_mgr.CodeManager = type("CodeManager", (), {})
    sys_health = types.ModuleType("managers.system_health")
    sys_health.SystemHealthManager = type("SystemHealthManager", (), {})
    gh_mgr = types.ModuleType("managers.github_manager")
    gh_mgr.GitHubManager = type("GitHubManager", (), {})
    web_mgr = types.ModuleType("managers.web_search")
    web_mgr.WebSearchManager = type("WebSearchManager", (), {})
    pkg_mgr = types.ModuleType("managers.package_info")
    pkg_mgr.PackageInfoManager = type("PackageInfoManager", (), {})
    memory_mod = types.ModuleType("core.memory")
    memory_mod.ConversationMemory = type("ConversationMemory", (), {})
    rag_mod = types.ModuleType("core.rag")
    rag_mod.DocumentStore = type("DocumentStore", (), {})

    auto_mod = _load_module(
        "agent_auto_quick100_unsupported",
        "agent/auto_handle.py",
        {
            "managers.code_manager": code_mgr,
            "managers.system_health": sys_health,
            "managers.github_manager": gh_mgr,
            "managers.web_search": web_mgr,
            "managers.package_info": pkg_mgr,
            "core.memory": memory_mod,
            "core.rag": rag_mod,
        },
    )

    mock_memory = MagicMock()
    mock_memory.get_last_file.return_value = "test.txt"
    mock_code = MagicMock()
    mock_code.read_file.return_value = (True, "dummy")

    ah = auto_mod.AutoHandle(
        code=mock_code,
        health=MagicMock(),
        github=MagicMock(),
        memory=mock_memory,
        web=MagicMock(),
        pkg=MagicMock(),
        docs=MagicMock(),
    )
    is_handled, msg = ah._try_validate_file("sözdizimi doğrula", "sözdizimi doğrula test.txt")
    assert is_handled is True
    assert "desteklenmiyor" in msg


def test_package_info_npm_string_author():
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.Timeout = lambda *a, **k: None
    fake_httpx.AsyncClient = object
    fake_httpx.HTTPError = Exception

    pkg_mod = _load_module("pkg_quick100_string_author", "managers/package_info.py", {"httpx": fake_httpx})
    pkg = pkg_mod.PackageInfoManager()

    async def mock_get_json(*args, **kwargs):
        return True, {"version": "1.0.0", "author": "String Author", "description": "x"}, ""

    pkg._get_json = mock_get_json
    ok, msg = asyncio.run(pkg.npm_info("test-pkg"))
    assert ok is True
    assert "String Author" in msg

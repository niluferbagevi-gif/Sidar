import asyncio
import builtins
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


def _load_module(module_name: str, file_path: str, stub_modules: dict[str, object] | None = None):
    saved = {}
    stub_modules = stub_modules or {}
    try:
        for key, value in stub_modules.items():
            saved[key] = sys.modules.get(key)
            sys.modules[key] = value
        spec = importlib.util.spec_from_file_location(module_name, Path(file_path))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        for key in stub_modules:
            if saved[key] is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = saved[key]


def test_config_env_fallback_and_hardware(monkeypatch):
    dotenv_mod = types.ModuleType("dotenv")
    dotenv_mod.load_dotenv = lambda *a, **k: None

    printed = []
    original_exists = Path.exists

    def mock_exists(self):
        if self.name.startswith(".env"):
            return False
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", mock_exists)
    monkeypatch.setattr(builtins, "print", lambda *a, **k: printed.append(" ".join(map(str, a))))
    monkeypatch.delenv("SIDAR_ENV", raising=False)

    cfg_missing = _load_module("config_quick100_missing", "config.py", {"dotenv": dotenv_mod})
    assert cfg_missing is not None
    assert any("'.env' dosyası bulunamadı" in p for p in printed)

    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(
        is_available=lambda: False,
        device_count=lambda: 0,
        get_device_name=lambda _i: "",
        set_per_process_memory_fraction=lambda *_a, **_k: None,
    )
    fake_torch.version = types.SimpleNamespace(cuda=None)

    fake_pynvml = types.ModuleType("pynvml")
    fake_pynvml.nvmlInit = lambda: None
    fake_pynvml.nvmlSystemGetDriverVersion = lambda: "550.0"
    fake_pynvml.nvmlShutdown = lambda: None

    cfg_hw = _load_module("config_quick100_hw", "config.py", {"dotenv": dotenv_mod})
    monkeypatch.setattr(cfg_hw, "get_bool_env", lambda *_a, **_k: True)

    mp_saved = sys.modules.get("multiprocessing")
    torch_saved = sys.modules.get("torch")
    nvml_saved = sys.modules.get("pynvml")
    sys.modules["multiprocessing"] = types.SimpleNamespace(cpu_count=lambda: 16)
    sys.modules["torch"] = fake_torch
    sys.modules["pynvml"] = fake_pynvml
    try:
        hw = cfg_hw.check_hardware()
        assert hw.driver_version == "550.0"
        assert hw.cpu_count == 16
        assert hw.gpu_name == "CUDA Bulunamadı"
    finally:
        if mp_saved is None:
            sys.modules.pop("multiprocessing", None)
        else:
            sys.modules["multiprocessing"] = mp_saved
        if torch_saved is None:
            sys.modules.pop("torch", None)
        else:
            sys.modules["torch"] = torch_saved
        if nvml_saved is None:
            sys.modules.pop("pynvml", None)
        else:
            sys.modules["pynvml"] = nvml_saved


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

    def _field(default=None, **kwargs):
        return default

    fake_pydantic.BaseModel = _BaseModel
    fake_pydantic.Field = _field

    tooling = _load_module("agent_tooling_quick100", "agent/tooling.py", {"pydantic": fake_pydantic})

    res_pr = tooling.parse_tool_argument("github_list_prs", "closed ||| 25")
    assert res_pr.state == "closed"
    assert res_pr.limit == 25

    res_todo = tooling.parse_tool_argument("scan_project_todos", "src ||| .py, .js")
    assert res_todo.directory == "src"
    assert res_todo.extensions == [".py", ".js"]


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
        "agent_auto_handle_quick100",
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

    mock_code = MagicMock()
    mock_code.read_file.return_value = (True, "dummy content")

    ah = auto_mod.AutoHandle(
        code=mock_code,
        health=MagicMock(),
        github=MagicMock(),
        memory=MagicMock(get_last_file=lambda: None),
        web=MagicMock(),
        pkg=MagicMock(),
        docs=MagicMock(),
    )

    is_handled, msg = ah._try_validate_file("sözdizimi doğrula", "validate test.txt")
    assert is_handled is True
    assert "desteklenmiyor" in msg


def test_package_info_npm_dict_author():
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.Timeout = lambda *a, **k: None
    fake_httpx.AsyncClient = object
    fake_httpx.HTTPError = Exception

    pkg_mod = _load_module(
        "package_info_quick100",
        "managers/package_info.py",
        {"httpx": fake_httpx},
    )
    pkg = pkg_mod.PackageInfoManager()

    async def mock_get_json(*args, **kwargs):
        return (
            True,
            {
                "version": "1.0.0",
                "author": {"name": "Test Author", "email": "test@test.com"},
                "description": "test package",
            },
            "",
        )

    pkg._get_json = mock_get_json
    ok, msg = asyncio.run(pkg.npm_info("test-pkg"))

    assert ok is True
    assert "Test Author" in msg


def test_config_validate_critical_settings_importerror_for_cryptography(monkeypatch):
    dotenv_mod = types.ModuleType("dotenv")
    dotenv_mod.load_dotenv = lambda *a, **k: None
    cfg_mod = _load_module("config_quick100_crypto", "config.py", {"dotenv": dotenv_mod})

    cfg_mod.Config.MEMORY_ENCRYPTION_KEY = "invalid-key"
    monkeypatch.setattr(cfg_mod.Config, "_ensure_hardware_info_loaded", lambda: None)
    monkeypatch.setattr(cfg_mod.Config, "initialize_directories", lambda: True)
    monkeypatch.setattr(cfg_mod.Config, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(cfg_mod.Config, "GEMINI_API_KEY", "set")

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name.startswith("cryptography"):
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    assert cfg_mod.Config.validate_critical_settings() is False


def test_auto_handle_validate_py_and_json_paths():
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
        "agent_auto_handle_quick100_validate",
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

    mock_code = MagicMock()
    mock_code.read_file.side_effect = [(True, "print('x')"), (True, "{}")]
    mock_code.validate_python_syntax.return_value = (True, "py ok")
    mock_code.validate_json.return_value = (False, "json fail")
    memory = MagicMock(get_last_file=lambda: "fallback.py")

    ah = auto_mod.AutoHandle(
        code=mock_code,
        health=MagicMock(),
        github=MagicMock(),
        memory=memory,
        web=MagicMock(),
        pkg=MagicMock(),
        docs=MagicMock(),
    )

    handled_py, msg_py = ah._try_validate_file("sözdizimi doğrula", "app.py sözdizimi doğrula")
    handled_json, msg_json = ah._try_validate_file("sözdizimi doğrula", "data.json sözdizimi doğrula")

    assert handled_py is True and "✓" in msg_py
    assert handled_json is True and "✗" in msg_json


def test_package_info_npm_peer_dependencies_branch():
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.Timeout = lambda *a, **k: None
    fake_httpx.AsyncClient = object
    fake_httpx.HTTPError = Exception

    pkg_mod = _load_module(
        "package_info_quick100_peer_deps",
        "managers/package_info.py",
        {"httpx": fake_httpx},
    )
    pkg = pkg_mod.PackageInfoManager()

    async def _mock_get_json(*args, **kwargs):
        return (
            True,
            {
                "version": "1.2.3",
                "author": "Author",
                "peerDependencies": {"react": "^18", "next": "^15"},
            },
            "",
        )

    pkg._get_json = _mock_get_json
    ok, msg = asyncio.run(pkg.npm_info("ui-pkg"))
    assert ok is True
    assert "Peer deps" in msg


def test_tooling_build_dispatch_maps_tools_to_agent_methods():
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
    tooling = _load_module("agent_tooling_quick100_dispatch", "agent/tooling.py", {"pydantic": fake_pydantic})

    class _Agent:
        def __getattr__(self, _name):
            return lambda *_a, **_k: "ok"

    dispatch = tooling.build_tool_dispatch(_Agent())
    assert "github_close_issue" in dispatch
    assert callable(dispatch["github_close_issue"])

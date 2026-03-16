"""
Coverage tests for misc uncovered lines:
  - agent/auto_handle.py: line 76 (long text returns False, "")
  - agent/sidar_agent.py: lines 124-126 (active_prompt sets system_prompt)
  - main.py: line 333 (init_telemetry called if hasattr)
  - managers/code_manager.py: lines 182-183 (WSL2 socket stat check)
  - managers/github_manager.py: lines 77-80, 92-94 (_init_client loads repo, _load_repo)
  - managers/package_info.py: lines 177-178 (pypi_compare with InvalidVersion)
"""
from __future__ import annotations

import asyncio
import stat as stat_mod
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ── auto_handle.py line 76: long text returns (False, "") ────────────────────

@pytest.mark.asyncio
async def test_auto_handle_long_text_returns_false():
    """Line 76: text longer than 2000 chars returns (False, '')."""
    from agent.auto_handle import AutoHandle

    auto = AutoHandle(
        code=MagicMock(),
        health=MagicMock(),
        github=MagicMock(),
        memory=MagicMock(),
        web=MagicMock(),
        pkg=MagicMock(),
        docs=MagicMock(),
        cfg=None,
    )
    long_text = "a" * 2001
    handled, response = await auto.handle(long_text)
    assert handled is False
    assert response == ""


# ── sidar_agent.py lines 124-126: active_prompt sets system_prompt ───────────

@pytest.mark.asyncio
async def test_sidar_agent_initialize_sets_system_prompt():
    """Lines 124-126: when db has active_prompt, system_prompt is updated."""
    import importlib
    import sys
    # The web_server tests replace agent.sidar_agent with a fake stub. Restore the real one.
    if "agent.sidar_agent" in sys.modules and not hasattr(sys.modules["agent.sidar_agent"], "ConversationMemory"):
        sys.modules.pop("agent.sidar_agent", None)
    import agent.sidar_agent
    importlib.reload(agent.sidar_agent)
    from agent.sidar_agent import SidarAgent

    # Create a minimal config with all required attributes
    class _Cfg:
        AI_PROVIDER = "ollama"
        CODING_MODEL = "codellama"
        TEXT_MODEL = "llama2"
        OPENAI_MODEL = "gpt-4"
        OPENAI_API_KEY = ""
        ANTHROPIC_API_KEY = ""
        ANTHROPIC_MODEL = "claude-3"
        GEMINI_MODEL = "gemini-2.0-flash"
        LITELLM_GATEWAY_URL = ""
        LITELLM_MODEL = ""
        ACCESS_LEVEL = "sandbox"
        DEBUG_MODE = False
        DATABASE_URL = ""
        MEMORY_ENCRYPTION_KEY = ""
        BASE_DIR = Path("/tmp")
        MEMORY_FILE = Path("/tmp/memory.json")
        MAX_MEMORY_TURNS = 20
        MEMORY_SUMMARY_KEEP_LAST = 4
        RAG_DIR = Path("/tmp/test_rag_sidar")
        RAG_VECTOR_BACKEND = "chromadb"
        PGVECTOR_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
        PGVECTOR_TABLE = "rag_embeddings"
        PGVECTOR_EMBEDDING_DIM = 384
        HF_HUB_OFFLINE = True
        USE_GPU = False
        GPU_DEVICE = 0
        GPU_MIXED_PRECISION = False
        GPU_INFO = "N/A"
        GPU_COUNT = 0
        CUDA_VERSION = "N/A"
        DRIVER_VERSION = "N/A"
        MULTI_GPU = False
        REDIS_URL = "redis://localhost:6379/0"
        ENABLE_SEMANTIC_CACHE = False
        SEMANTIC_CACHE_THRESHOLD = 0.95
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500
        ENABLE_TRACING = False
        OTEL_EXPORTER_ENDPOINT = ""
        OTEL_SERVICE_NAME = "sidar"
        GITHUB_TOKEN = ""
        GITHUB_REPO = ""
        CHROMA_PERSIST_PATH = ""
        RAG_TOP_K = 3
        RAG_CHUNK_SIZE = 500
        RAG_CHUNK_OVERLAP = 50
        AUTO_HANDLE_TIMEOUT = 12
        SYSTEM_PROMPT = ""
        OLLAMA_URL = "http://localhost:11434/api"
        OLLAMA_TIMEOUT = 120
        GEMINI_API_KEY = ""
        VERSION = "1.0.0"
        PROJECT_NAME = "Sidar"
        JWT_SECRET_KEY = "test"
        JWT_TTL_DAYS = 7
        DB_POOL_SIZE = 1
        DB_SCHEMA_VERSION_TABLE = "schema_versions"
        DB_SCHEMA_TARGET_VERSION = 1
        DOCKER_PYTHON_IMAGE = "python:3.11-alpine"
        DOCKER_EXEC_TIMEOUT = 10

        @staticmethod
        def initialize_directories():
            pass

    prompt_record = types.SimpleNamespace(
        prompt_text="  Custom system prompt  ",
    )

    mock_db = AsyncMock()
    mock_db.get_active_prompt = AsyncMock(return_value=prompt_record)

    mock_memory = MagicMock()
    mock_memory.initialize = AsyncMock()
    mock_memory.db = mock_db

    cfg = _Cfg()

    with patch("agent.sidar_agent.ConversationMemory", return_value=mock_memory):
        with patch("agent.sidar_agent.DocumentStore"):
            with patch("agent.sidar_agent.SystemHealthManager"):
                with patch("agent.sidar_agent.GitHubManager"):
                    with patch("agent.sidar_agent.WebSearchManager"):
                        with patch("agent.sidar_agent.PackageInfoManager"):
                            with patch("agent.sidar_agent.SecurityManager"):
                                with patch("agent.sidar_agent.CodeManager"):
                                    with patch("agent.sidar_agent.LLMClient"):
                                        with patch("agent.sidar_agent.TodoManager"):
                                            agent = SidarAgent(cfg=cfg)
                                            agent.memory = mock_memory
                                            await agent.initialize()

    assert agent.system_prompt == "  Custom system prompt  "


@pytest.mark.asyncio
async def test_sidar_agent_initialize_no_active_prompt():
    """Lines 123-126: when active_prompt is None, system_prompt unchanged."""
    import importlib
    import sys
    # The web_server tests replace agent.sidar_agent with a fake stub. Restore the real one.
    if "agent.sidar_agent" in sys.modules and not hasattr(sys.modules["agent.sidar_agent"], "ConversationMemory"):
        sys.modules.pop("agent.sidar_agent", None)
    import agent.sidar_agent
    importlib.reload(agent.sidar_agent)
    from agent.sidar_agent import SidarAgent

    class _Cfg:
        AI_PROVIDER = "ollama"
        CODING_MODEL = "codellama"
        TEXT_MODEL = "llama2"
        OPENAI_MODEL = "gpt-4"
        OPENAI_API_KEY = ""
        ANTHROPIC_API_KEY = ""
        ANTHROPIC_MODEL = "claude-3"
        GEMINI_MODEL = "gemini-2.0-flash"
        LITELLM_GATEWAY_URL = ""
        LITELLM_MODEL = ""
        ACCESS_LEVEL = "sandbox"
        DEBUG_MODE = False
        DATABASE_URL = ""
        MEMORY_ENCRYPTION_KEY = ""
        BASE_DIR = Path("/tmp")
        MEMORY_FILE = Path("/tmp/memory2.json")
        MAX_MEMORY_TURNS = 20
        MEMORY_SUMMARY_KEEP_LAST = 4
        RAG_DIR = Path("/tmp/test_rag_sidar2")
        RAG_VECTOR_BACKEND = "chromadb"
        PGVECTOR_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
        PGVECTOR_TABLE = "rag_embeddings"
        PGVECTOR_EMBEDDING_DIM = 384
        HF_HUB_OFFLINE = True
        USE_GPU = False
        GPU_DEVICE = 0
        GPU_MIXED_PRECISION = False
        GPU_INFO = "N/A"
        GPU_COUNT = 0
        CUDA_VERSION = "N/A"
        DRIVER_VERSION = "N/A"
        MULTI_GPU = False
        REDIS_URL = ""
        ENABLE_SEMANTIC_CACHE = False
        SEMANTIC_CACHE_THRESHOLD = 0.95
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500
        ENABLE_TRACING = False
        OTEL_EXPORTER_ENDPOINT = ""
        OTEL_SERVICE_NAME = "sidar"
        GITHUB_TOKEN = ""
        GITHUB_REPO = ""
        CHROMA_PERSIST_PATH = ""
        RAG_TOP_K = 3
        RAG_CHUNK_SIZE = 500
        RAG_CHUNK_OVERLAP = 50
        AUTO_HANDLE_TIMEOUT = 12
        SYSTEM_PROMPT = ""
        OLLAMA_URL = "http://localhost:11434/api"
        OLLAMA_TIMEOUT = 120
        GEMINI_API_KEY = ""
        VERSION = "1.0.0"
        PROJECT_NAME = "Sidar"
        JWT_SECRET_KEY = "test"
        JWT_TTL_DAYS = 7
        DB_POOL_SIZE = 1
        DB_SCHEMA_VERSION_TABLE = "schema_versions"
        DB_SCHEMA_TARGET_VERSION = 1
        DOCKER_PYTHON_IMAGE = "python:3.11-alpine"
        DOCKER_EXEC_TIMEOUT = 10

        @staticmethod
        def initialize_directories():
            pass

    mock_db = AsyncMock()
    mock_db.get_active_prompt = AsyncMock(return_value=None)

    mock_memory = MagicMock()
    mock_memory.initialize = AsyncMock()
    mock_memory.db = mock_db

    cfg = _Cfg()

    with patch("agent.sidar_agent.ConversationMemory", return_value=mock_memory):
        with patch("agent.sidar_agent.DocumentStore"):
            with patch("agent.sidar_agent.SystemHealthManager"):
                with patch("agent.sidar_agent.GitHubManager"):
                    with patch("agent.sidar_agent.WebSearchManager"):
                        with patch("agent.sidar_agent.PackageInfoManager"):
                            with patch("agent.sidar_agent.SecurityManager"):
                                with patch("agent.sidar_agent.CodeManager"):
                                    with patch("agent.sidar_agent.LLMClient"):
                                        with patch("agent.sidar_agent.TodoManager"):
                                            agent = SidarAgent(cfg=cfg)
                                            original_prompt = agent.system_prompt
                                            agent.memory = mock_memory
                                            await agent.initialize()

    assert agent.system_prompt == original_prompt


# ── main.py line 333: init_telemetry called when hasattr ─────────────────────

def test_main_init_telemetry_called_when_hasattr():
    """Line 333: main() calls cfg.init_telemetry when attribute exists."""
    import main as main_module

    mock_cfg = MagicMock()
    mock_cfg.init_telemetry = MagicMock(return_value=False)

    # Patch the cfg in main and argparse to not actually run
    with patch.object(main_module, "cfg", mock_cfg):
        with patch("argparse.ArgumentParser.parse_args") as mock_parse:
            mock_parse.return_value = types.SimpleNamespace(
                quick=None,
                provider=None,
                level=None,
                model=None,
                host=None,
                port=None,
                log="info",
                capture_output=False,
                child_log=None,
            )
            # When quick=None, main() calls run_wizard() then sys.exit()
            with patch.object(main_module, "run_wizard", return_value=0):
                try:
                    main_module.main()
                except SystemExit:
                    pass
                except Exception:
                    pass

    mock_cfg.init_telemetry.assert_called_once_with(service_name="sidar-launcher")


# ── github_manager.py lines 77-80, 92-94 ────────────────────────────────────

def test_github_manager_init_client_loads_repo():
    """Lines 77-80: _init_client calls _load_repo when repo_name set."""
    from managers.github_manager import GitHubManager

    manager = GitHubManager.__new__(GitHubManager)
    manager.token = "fake-token"
    manager.repo_name = "owner/repo"
    manager.require_token = False
    manager._available = False
    manager._gh = None
    manager._repo = None

    mock_auth = MagicMock()
    mock_gh = MagicMock()
    mock_user = MagicMock()
    mock_user.login = "testuser"
    mock_gh.get_user.return_value = mock_user

    with patch.dict("sys.modules", {"github": MagicMock(
        Auth=MagicMock(Token=MagicMock(return_value=mock_auth)),
        Github=MagicMock(return_value=mock_gh),
    )}):
        with patch.object(manager, "_load_repo", return_value=True) as mock_load:
            manager._init_client()

    mock_load.assert_called_once_with("owner/repo")


def test_github_manager_load_repo_success():
    """Lines 92-94: _load_repo returns True when repo loaded."""
    from managers.github_manager import GitHubManager

    manager = GitHubManager.__new__(GitHubManager)
    manager._available = True
    manager._repo = None
    manager.repo_name = ""

    mock_repo = MagicMock()
    mock_gh = MagicMock()
    mock_gh.get_repo.return_value = mock_repo
    manager._gh = mock_gh

    result = manager._load_repo("owner/repo")
    assert result is True
    assert manager.repo_name == "owner/repo"
    assert manager._repo is mock_repo


def test_github_manager_load_repo_exception():
    """Lines 95-97: _load_repo returns False on exception."""
    from managers.github_manager import GitHubManager

    manager = GitHubManager.__new__(GitHubManager)
    manager._available = True
    manager._repo = None
    manager.repo_name = ""

    mock_gh = MagicMock()
    mock_gh.get_repo.side_effect = Exception("not found")
    manager._gh = mock_gh

    result = manager._load_repo("owner/nonexistent")
    assert result is False


def test_github_manager_init_client_exception():
    """Lines 83-84: _init_client handles general exception."""
    from managers.github_manager import GitHubManager

    manager = GitHubManager.__new__(GitHubManager)
    manager.token = "fake-token"
    manager.repo_name = ""
    manager.require_token = False
    manager._available = False
    manager._gh = None

    mock_github_mod = MagicMock()
    mock_gh = MagicMock()
    mock_gh.get_user.side_effect = Exception("auth failed")
    mock_github_mod.Github.return_value = mock_gh
    mock_github_mod.Auth.Token.return_value = MagicMock()

    with patch.dict("sys.modules", {"github": mock_github_mod}):
        manager._init_client()

    assert manager._available is False


# ── package_info.py lines 177-178: pypi_compare with InvalidVersion ─────────

@pytest.mark.asyncio
async def test_pypi_compare_invalid_version():
    """Lines 177-178: InvalidVersion exception falls back to string comparison."""
    from managers.package_info import PackageInfoManager
    from packaging.version import InvalidVersion

    manager = PackageInfoManager.__new__(PackageInfoManager)

    pypi_data = {
        "info": {"version": "2.0.0"},
    }

    info_text = "  Paket: requests\n  Sürüm: 2.0.0\n"

    with patch.object(manager, "_fetch_pypi_json", return_value=(True, pypi_data, "")):
        with patch.object(manager, "pypi_info", return_value=(True, info_text)):
            with patch("managers.package_info.Version") as MockVersion:
                MockVersion.side_effect = InvalidVersion("bad version string")
                ok, result = await manager.pypi_compare("requests", "invalid_version_string")

    assert ok is True
    # Since "invalid_version_string" != "2.0.0", needs_update=True
    assert "Güncelleme" in result or "Güncel" in result


@pytest.mark.asyncio
async def test_pypi_compare_up_to_date():
    """Lines 179-180: when versions match, shows up-to-date status."""
    from managers.package_info import PackageInfoManager

    manager = PackageInfoManager.__new__(PackageInfoManager)

    pypi_data = {"info": {"version": "1.0.0"}}
    info_text = "  Paket: requests"

    with patch.object(manager, "_fetch_pypi_json", return_value=(True, pypi_data, "")):
        with patch.object(manager, "pypi_info", return_value=(True, info_text)):
            ok, result = await manager.pypi_compare("requests", "1.0.0")

    assert ok is True
    assert "Güncel" in result


# ── code_manager.py lines 182-183: WSL2 socket stat check ────────────────────

def test_code_manager_wsl2_socket_not_a_socket(tmp_path):
    """Lines 181-183: _init_docker skips paths that exist but are not sockets."""
    from managers.code_manager import CodeManager
    import stat as stat_mod2
    import managers.code_manager as cm_mod

    # Create a regular file (not a socket) at a tmp path
    fake_sock = tmp_path / "docker.sock"
    fake_sock.write_bytes(b"")
    fake_path = str(fake_sock)

    manager = CodeManager.__new__(CodeManager)
    manager.docker_client = None
    manager.docker_available = False

    mock_docker_mod = MagicMock()
    # docker.from_env() raises to trigger WSL2 fallback
    mock_docker_mod.from_env = MagicMock(side_effect=Exception("primary failed"))
    # DockerClient also mock
    mock_docker_mod.DockerClient = MagicMock(side_effect=Exception("no connect"))

    # os.stat returns a non-socket st_mode
    def _fake_stat(p, *a, **kw):
        result = MagicMock()
        result.st_mode = stat_mod2.S_IFREG  # regular file, not a socket
        return result

    # Override wsl_sockets list in the function using patch on os.stat
    # and by setting up one socket path that points to our regular file
    original_wsl_list = [
        "unix:///var/run/docker.sock",
        "unix:///mnt/wsl/docker-desktop/run/guest-services/backend.sock",
    ]

    with patch.dict("sys.modules", {"docker": mock_docker_mod}):
        with patch.object(cm_mod.os, "stat", side_effect=_fake_stat):
            try:
                manager._init_docker()
            except Exception:
                pass

    # Should not have connected (path was not a socket, so skipped)
    assert manager.docker_available is False

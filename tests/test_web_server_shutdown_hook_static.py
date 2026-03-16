from pathlib import Path


def test_web_server_has_atexit_and_async_shutdown_cleanup_hooks():
    src = Path("web_server.py").read_text(encoding="utf-8")
    assert "atexit.register(_force_shutdown_local_llm_processes)" in src
    assert "async def _async_force_shutdown_local_llm_processes" in src
    assert "await _async_force_shutdown_local_llm_processes()" in src


def test_web_server_shutdown_cleanup_targets_ollama_children():
    src = Path("web_server.py").read_text(encoding="utf-8")
    assert "def _list_child_ollama_pids" in src
    assert '"ollama serve" in args' in src
    assert "os.kill(pid, signal.SIGTERM)" in src
    assert "os.kill(pid, signal.SIGKILL)" in src


def test_config_exposes_ollama_force_kill_flag():
    src = Path("config.py").read_text(encoding="utf-8")
    assert "OLLAMA_FORCE_KILL_ON_SHUTDOWN" in src

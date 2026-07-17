"""Unit tests for web runtime helper modules split out of web_server."""

from __future__ import annotations

from types import SimpleNamespace

from web import autonomy_bridge, collaboration_service, process_lifecycle


def test_autonomy_bridge_preserves_service_actor_fallbacks() -> None:
    config = SimpleNamespace(AUTONOMY_SERVICE_USER_ID="", SYSTEM_USER_ID="system:ops")

    assert autonomy_bridge.autonomy_service_actor(config, "webhook:github") == (
        "system:ops",
        "autonomy:webhook:github",
    )


def test_autonomy_bridge_trim_uses_existing_truncated_suffix() -> None:
    assert autonomy_bridge.trim_autonomy_text(" abc ", limit=10) == "abc"
    assert autonomy_bridge.trim_autonomy_text("abcdefghijk", limit=5) == "abcde …[truncated]"


def test_collaboration_service_chunks_stream_text() -> None:
    assert collaboration_service.iter_stream_chunks("", size=2) == []
    assert collaboration_service.iter_stream_chunks("abcde", size=2) == ["ab", "cd", "e"]


def test_process_lifecycle_terminates_with_term_then_kill() -> None:
    calls: list[tuple[int, int] | tuple[str, float]] = []

    process_lifecycle.terminate_process_pids(
        [7, 8],
        sigterm=15,
        sigkill=9,
        kill_func=lambda pid, sig: calls.append((pid, sig)),
        sleep_func=lambda seconds: calls.append(("sleep", seconds)),
        grace_seconds=0.01,
    )

    assert calls == [(7, 15), (8, 15), ("sleep", 0.01), (7, 9), (8, 9)]


def test_process_lifecycle_psutil_path_detects_ollama_children() -> None:
    class Child:
        pid = 42

        def name(self) -> str:
            return "ollama"

        def cmdline(self) -> list[str]:
            return ["ollama", "serve"]

    class Process:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def children(self, recursive: bool = False) -> list[Child]:
            assert recursive is False
            return [Child()]

    fake_psutil = SimpleNamespace(Process=Process)

    assert process_lifecycle.list_child_ollama_pids(
        resolve_psutil_module=lambda: fake_psutil,
        current_pid=1,
        safe_ps_binary=None,
    ) == [42]

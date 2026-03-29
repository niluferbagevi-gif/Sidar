"""
cli.py için birim testleri.
_setup_logging, _make_banner, HELP_TEXT, _interactive_loop_async,
interactive_loop ve main() argparse akışını kapsar.

NOT: cli.py, import anında agent.sidar_agent → pydantic bağımlılığı gerektirir.
Bu bağımlılıklar test ortamında bulunmadığından, ilgili modüller
sys.modules üzerinden stub olarak enjekte edilir.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────
# Ağır bağımlılıkların stub'ları  (cli import öncesi enjekte edilir)
# ──────────────────────────────────────────────────────────────

def _inject_stubs():
    """pydantic ve agent.sidar_agent için minimal stub'lar."""
    # pydantic
    if "pydantic" not in sys.modules:
        _pyd = types.ModuleType("pydantic")
        class _BaseModel:
            def __init__(self, **data):
                for k, v in data.items():
                    setattr(self, k, v)
        _pyd.BaseModel = _BaseModel
        _pyd.Field = lambda *a, **k: None
        _pyd.ValidationError = Exception
        sys.modules["pydantic"] = _pyd

    # agent.sidar_agent  — gerçek sınıfı import etmek yerine mock sınıf kullanıyoruz
    if "agent.sidar_agent" not in sys.modules or not hasattr(
        sys.modules.get("agent.sidar_agent"), "_IS_STUB"
    ):
        _mod = types.ModuleType("agent.sidar_agent")

        class SidarAgentStub:
            VERSION = "5.2.0"
            def __init__(self, cfg=None):
                self.cfg = cfg
        _mod.SidarAgent = SidarAgentStub
        _mod._IS_STUB = True
        sys.modules["agent.sidar_agent"] = _mod

    # opentelemetry (opsiyonel, yoksa hata)
    for _otel in ("opentelemetry", "opentelemetry.trace"):
        if _otel not in sys.modules:
            sys.modules[_otel] = types.ModuleType(_otel)


_inject_stubs()


# ──────────────────────────────────────────────────────────────
# cli modülünü temiz import
# ──────────────────────────────────────────────────────────────

def _get_cli():
    _inject_stubs()
    # cli daha önce yüklendiyse eski halini kullan
    if "cli" in sys.modules:
        return sys.modules["cli"]
    import cli
    return cli


# ──────────────────────────────────────────────────────────────
# Agent mock factory
# ──────────────────────────────────────────────────────────────

def _make_agent(
    provider="ollama",
    access_level="full",
    coding_model="qwen2.5-coder:7b",
    use_gpu=False,
    gpu_info="CPU Modu",
    cuda_version="N/A",
    gpu_count=1,
    gemini_model="gemini-2.0-flash",
    version="5.2.0",
):
    cfg = SimpleNamespace(
        AI_PROVIDER=provider,
        ACCESS_LEVEL=access_level,
        CODING_MODEL=coding_model,
        USE_GPU=use_gpu,
        GPU_INFO=gpu_info,
        CUDA_VERSION=cuda_version,
        GPU_COUNT=gpu_count,
        GEMINI_MODEL=gemini_model,
    )
    agent = MagicMock()
    agent.cfg = cfg
    agent.VERSION = version
    agent.github.is_available.return_value = True
    agent.web.is_available.return_value = True
    agent.pkg.status.return_value = "OK"
    agent.docs.status.return_value = "OK"
    agent.status.return_value = "sistem durumu"
    agent.clear_memory = AsyncMock(return_value="bellek temizlendi")
    agent.set_access_level = AsyncMock(return_value="seviye ayarlandı")
    agent.code.audit_project.return_value = "denetim raporu"
    agent.health.full_report.return_value = "sağlık raporu"
    agent.health.optimize_gpu_memory.return_value = "GPU optimize edildi"
    agent.github.status.return_value = "github durumu"
    agent.web.status.return_value = "web durumu"
    agent.docs.list_documents.return_value = "belgeler listesi"
    agent.security.status_report.return_value = "güvenlik raporu"

    async def _respond_gen(text):
        yield "cevap parçası"

    agent.respond = _respond_gen
    return agent


# ══════════════════════════════════════════════════════════════
# _setup_logging
# ══════════════════════════════════════════════════════════════

class TestSetupLogging:
    def test_debug_level(self):
        _get_cli()._setup_logging("debug")
        assert logging.getLogger().level == logging.DEBUG

    def test_info_level(self):
        _get_cli()._setup_logging("info")
        assert logging.getLogger().level == logging.INFO

    def test_warning_level(self):
        _get_cli()._setup_logging("warning")
        assert logging.getLogger().level == logging.WARNING

    def test_error_level(self):
        _get_cli()._setup_logging("error")
        assert logging.getLogger().level == logging.ERROR

    def test_uppercase_input(self):
        _get_cli()._setup_logging("DEBUG")
        assert logging.getLogger().level == logging.DEBUG

    def test_mixed_case(self):
        _get_cli()._setup_logging("Warning")
        assert logging.getLogger().level == logging.WARNING

    def test_unknown_level_falls_back_to_info(self):
        _get_cli()._setup_logging("unknown_level")
        assert logging.getLogger().level == logging.INFO


# ══════════════════════════════════════════════════════════════
# _make_banner
# ══════════════════════════════════════════════════════════════

class TestMakeBanner:
    def test_contains_version(self):
        result = _get_cli()._make_banner("5.2.0")
        assert "v5.2.0" in result

    def test_empty_version_shows_placeholder(self):
        result = _get_cli()._make_banner("")
        assert "v?" in result

    def test_contains_box_borders(self):
        result = _get_cli()._make_banner("1.0.0")
        assert "╔" in result
        assert "╝" in result

    def test_long_version_truncated(self):
        result = _get_cli()._make_banner("1.2.3.4.5.6.7.8.9")
        assert "…" in result

    def test_short_version_padded(self):
        result = _get_cli()._make_banner("1.0")
        assert "v1.0" in result

    def test_returns_string(self):
        assert isinstance(_get_cli()._make_banner("5.0"), str)

    def test_ends_with_newline(self):
        assert _get_cli()._make_banner("1.0").endswith("\n")

    def test_exactly_over_max_truncated(self):
        # _VER_AREA=11: "v" + 11 karakter = 12 > 11 → kırpılır
        result = _get_cli()._make_banner("1.2.3.4.5.6")
        assert "…" in result

    def test_contains_ascii_art(self):
        result = _get_cli()._make_banner("1.0")
        assert "███" in result


# ══════════════════════════════════════════════════════════════
# HELP_TEXT
# ══════════════════════════════════════════════════════════════

class TestHelpText:
    def test_contains_status_command(self):
        assert ".status" in _get_cli().HELP_TEXT

    def test_contains_clear_command(self):
        assert ".clear" in _get_cli().HELP_TEXT

    def test_contains_exit_command(self):
        assert ".exit" in _get_cli().HELP_TEXT

    def test_contains_help_command(self):
        assert ".help" in _get_cli().HELP_TEXT

    def test_contains_level_command(self):
        assert ".level" in _get_cli().HELP_TEXT

    def test_contains_audit_command(self):
        assert ".audit" in _get_cli().HELP_TEXT

    def test_contains_health_command(self):
        assert ".health" in _get_cli().HELP_TEXT

    def test_contains_gpu_command(self):
        assert ".gpu" in _get_cli().HELP_TEXT

    def test_is_nonempty_string(self):
        ht = _get_cli().HELP_TEXT
        assert isinstance(ht, str) and len(ht) > 0


# ══════════════════════════════════════════════════════════════
# _interactive_loop_async  — komut dalları
# ══════════════════════════════════════════════════════════════

class TestInteractiveLoopAsync:
    """asyncio.to_thread(input, ...) patch'leyerek her komutu test eder."""

    def _run(self, inputs: list, agent=None):
        cli = _get_cli()
        agent = agent or _make_agent()
        input_iter = iter(inputs)

        async def fake_to_thread(fn, *args, **kwargs):
            try:
                return next(input_iter)
            except StopIteration:
                raise EOFError

        async def run():
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch("builtins.print"):
                    await cli._interactive_loop_async(agent)

        asyncio.run(run())
        return agent

    def test_exit_command_breaks_loop(self):
        self._run([".exit"])

    def test_q_command_breaks_loop(self):
        self._run([".q"])

    def test_help_command_prints_help(self):
        cli = _get_cli()
        agent = _make_agent()
        input_iter = iter([".help", ".exit"])
        printed = []

        async def fake_to_thread(fn, *a, **k):
            try:
                return next(input_iter)
            except StopIteration:
                raise EOFError

        async def run():
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch("builtins.print", side_effect=lambda *a, **k: printed.append(str(a))):
                    await cli._interactive_loop_async(agent)

        asyncio.run(run())
        combined = " ".join(printed)
        assert "Komutlar" in combined or ".status" in combined

    def test_status_command(self):
        agent = _make_agent()
        self._run([".status", ".exit"], agent)
        agent.status.assert_called()

    def test_clear_command(self):
        agent = _make_agent()
        self._run([".clear", ".exit"], agent)
        agent.clear_memory.assert_called()

    def test_clear_alias_slash_clear(self):
        agent = _make_agent()
        self._run(["/clear", ".exit"], agent)
        agent.clear_memory.assert_called()

    def test_clear_alias_slash_reset(self):
        agent = _make_agent()
        self._run(["/reset", ".exit"], agent)
        agent.clear_memory.assert_called()

    def test_audit_command(self):
        agent = _make_agent()
        self._run([".audit", ".exit"], agent)
        agent.code.audit_project.assert_called_with(".")

    def test_health_command(self):
        agent = _make_agent()
        self._run([".health", ".exit"], agent)
        agent.health.full_report.assert_called()

    def test_gpu_command(self):
        agent = _make_agent()
        self._run([".gpu", ".exit"], agent)
        agent.health.optimize_gpu_memory.assert_called()

    def test_github_command(self):
        agent = _make_agent()
        self._run([".github", ".exit"], agent)
        agent.github.status.assert_called()

    def test_web_command(self):
        agent = _make_agent()
        self._run([".web", ".exit"], agent)
        agent.web.status.assert_called()

    def test_docs_command(self):
        agent = _make_agent()
        self._run([".docs", ".exit"], agent)
        agent.docs.list_documents.assert_called()

    def test_level_without_arg_shows_security_report(self):
        agent = _make_agent()
        self._run([".level", ".exit"], agent)
        agent.security.status_report.assert_called()

    def test_level_with_arg_sets_level(self):
        agent = _make_agent()
        self._run([".level full", ".exit"], agent)
        agent.set_access_level.assert_called_with("full")

    def test_level_with_restricted_arg(self):
        agent = _make_agent()
        self._run([".level restricted", ".exit"], agent)
        agent.set_access_level.assert_called_with("restricted")

    def test_empty_input_ignored(self):
        agent = _make_agent()
        self._run(["", ".exit"], agent)
        agent.status.assert_not_called()

    def test_eof_error_breaks_loop(self):
        cli = _get_cli()
        agent = _make_agent()

        async def fake_to_thread(fn, *a, **k):
            raise EOFError

        async def run():
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch("builtins.print"):
                    await cli._interactive_loop_async(agent)

        asyncio.run(run())

    def test_keyboard_interrupt_breaks_loop(self):
        cli = _get_cli()
        agent = _make_agent()

        async def fake_to_thread(fn, *a, **k):
            raise KeyboardInterrupt

        async def run():
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch("builtins.print"):
                    await cli._interactive_loop_async(agent)

        asyncio.run(run())

    def test_cancelled_error_from_input_breaks_loop(self):
        cli = _get_cli()
        agent = _make_agent()

        async def fake_to_thread(fn, *a, **k):
            raise asyncio.CancelledError

        async def run():
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch("builtins.print"):
                    await cli._interactive_loop_async(agent)

        asyncio.run(run())

    def test_agent_respond_called_for_freetext(self):
        cli = _get_cli()
        agent = _make_agent()
        responded = []

        async def fake_respond(text):
            responded.append(text)
            yield "cevap"

        agent.respond = fake_respond
        self._run(["Merhaba", ".exit"], agent)
        assert "Merhaba" in responded

    def test_agent_exception_does_not_crash_loop(self):
        cli = _get_cli()
        agent = _make_agent()

        async def bad_respond(text):
            raise RuntimeError("LLM hatası")
            yield  # generator için

        agent.respond = bad_respond
        self._run(["hatalı sorgu", ".exit"], agent)

    def test_agent_cancelled_error_stops_loop(self):
        cli = _get_cli()
        agent = _make_agent()
        input_iter = iter(["merhaba"])

        async def fake_to_thread(fn, *a, **k):
            return next(input_iter)

        async def cancelled_respond(text):
            raise asyncio.CancelledError
            yield

        agent.respond = cancelled_respond

        async def run():
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch("builtins.print"):
                    await cli._interactive_loop_async(agent)

        asyncio.run(run())

    def test_gpu_info_displayed_when_use_gpu_true(self):
        cli = _get_cli()
        agent = _make_agent(use_gpu=True, gpu_info="RTX 4090", cuda_version="12.1", gpu_count=1)
        printed = []

        async def fake_to_thread(fn, *a, **k):
            raise EOFError

        async def run():
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch("builtins.print", side_effect=lambda *a, **k: printed.append(str(a))):
                    await cli._interactive_loop_async(agent)

        asyncio.run(run())
        assert "RTX 4090" in " ".join(printed)

    def test_multi_gpu_count_displayed(self):
        cli = _get_cli()
        agent = _make_agent(use_gpu=True, gpu_info="A100", cuda_version="12.0", gpu_count=4)
        printed = []

        async def fake_to_thread(fn, *a, **k):
            raise EOFError

        async def run():
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch("builtins.print", side_effect=lambda *a, **k: printed.append(str(a))):
                    await cli._interactive_loop_async(agent)

        asyncio.run(run())
        combined = " ".join(printed)
        assert "4 GPU" in combined or "A100" in combined

    def test_cpu_mode_displayed_when_gpu_false(self):
        cli = _get_cli()
        agent = _make_agent(use_gpu=False, gpu_info="CPU Modu")
        printed = []

        async def fake_to_thread(fn, *a, **k):
            raise EOFError

        async def run():
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch("builtins.print", side_effect=lambda *a, **k: printed.append(str(a))):
                    await cli._interactive_loop_async(agent)

        asyncio.run(run())
        assert "CPU" in " ".join(printed)

    def test_gemini_provider_shows_gemini_model(self):
        cli = _get_cli()
        agent = _make_agent(provider="gemini", gemini_model="gemini-1.5-pro")
        printed = []

        async def fake_to_thread(fn, *a, **k):
            raise EOFError

        async def run():
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch("builtins.print", side_effect=lambda *a, **k: printed.append(str(a))):
                    await cli._interactive_loop_async(agent)

        asyncio.run(run())
        assert "gemini-1.5-pro" in " ".join(printed)

    def test_exit_aliases(self):
        for cmd in ("exit", "quit", "çıkış"):
            self._run([cmd])

    def test_github_unavailable_shown(self):
        cli = _get_cli()
        agent = _make_agent()
        agent.github.is_available.return_value = False
        printed = []

        async def fake_to_thread(fn, *a, **k):
            raise EOFError

        async def run():
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch("builtins.print", side_effect=lambda *a, **k: printed.append(str(a))):
                    await cli._interactive_loop_async(agent)

        asyncio.run(run())
        assert "Bağlı değil" in " ".join(printed)


# ══════════════════════════════════════════════════════════════
# interactive_loop  (sync wrapper)
# ══════════════════════════════════════════════════════════════

class TestInteractiveLoop:
    def test_calls_asyncio_run(self):
        cli = _get_cli()
        agent = _make_agent()
        # Coroutine'i hemen kapat, "never awaited" uyarısını önle
        with patch("asyncio.run", side_effect=lambda coro: coro.close()) as mock_run:
            cli.interactive_loop(agent)
        mock_run.assert_called_once()

    def test_passes_coroutine_to_asyncio_run(self):
        import inspect
        cli = _get_cli()
        agent = _make_agent()
        captured = []

        def _capture_and_close(coro):
            captured.append(coro)
            coro.close()

        with patch("asyncio.run", side_effect=_capture_and_close):
            cli.interactive_loop(agent)
        assert len(captured) == 1
        assert inspect.iscoroutine(captured[0])


# ══════════════════════════════════════════════════════════════
# main()  — argparse akışı
# ══════════════════════════════════════════════════════════════

def _safe_asyncio_run(coro):
    """asyncio.run yerine kullanılır: coroutine'i çalıştırır veya sadece kapatır."""
    import inspect
    if inspect.iscoroutine(coro):
        coro.close()


class TestMain:
    def _make_mocks(self):
        mock_cfg = MagicMock()
        mock_cfg.ACCESS_LEVEL = "full"
        mock_cfg.AI_PROVIDER = "ollama"
        mock_cfg.CODING_MODEL = "qwen2.5-coder:7b"
        mock_cfg.LOG_LEVEL = "INFO"
        mock_agent = MagicMock()
        mock_agent.status.return_value = "sistem OK"
        mock_agent.memory.initialize = AsyncMock()

        async def fake_respond(text):
            yield "cevap"

        mock_agent.respond = fake_respond
        return mock_cfg, mock_agent

    def test_status_flag_calls_agent_status(self):
        cli = _get_cli()
        mock_cfg, mock_agent = self._make_mocks()
        with patch.object(sys, "argv", ["cli.py", "--status"]):
            with patch("cli.Config", return_value=mock_cfg):
                with patch("cli.SidarAgent", return_value=mock_agent):
                    with patch("asyncio.run", side_effect=_safe_asyncio_run):
                        with patch("builtins.print"):
                            cli.main()
        mock_agent.status.assert_called_once()

    def test_command_flag_calls_asyncio_run_twice(self):
        cli = _get_cli()
        mock_cfg, mock_agent = self._make_mocks()
        run_count = []
        def _count_run(coro):
            run_count.append(1)
            import inspect
            if inspect.iscoroutine(coro):
                coro.close()
        with patch.object(sys, "argv", ["cli.py", "-c", "merhaba"]):
            with patch("cli.Config", return_value=mock_cfg):
                with patch("cli.SidarAgent", return_value=mock_agent):
                    with patch("asyncio.run", side_effect=_count_run):
                        with patch("builtins.print"):
                            cli.main()
        # memory.initialize + _run_command = 2 çağrı
        assert len(run_count) == 2

    def test_no_flags_calls_interactive_loop(self):
        cli = _get_cli()
        mock_cfg, mock_agent = self._make_mocks()
        with patch.object(sys, "argv", ["cli.py"]):
            with patch("cli.Config", return_value=mock_cfg):
                with patch("cli.SidarAgent", return_value=mock_agent):
                    with patch("asyncio.run", side_effect=_safe_asyncio_run):
                        with patch("cli.interactive_loop") as mock_loop:
                            with patch("builtins.print"):
                                cli.main()
        mock_loop.assert_called_once_with(mock_agent)

    def test_level_arg_overrides_config(self):
        cli = _get_cli()
        mock_cfg, mock_agent = self._make_mocks()
        with patch.object(sys, "argv", ["cli.py", "--level", "restricted", "--status"]):
            with patch("cli.Config", return_value=mock_cfg):
                with patch("cli.SidarAgent", return_value=mock_agent):
                    with patch("asyncio.run", side_effect=_safe_asyncio_run):
                        with patch("builtins.print"):
                            cli.main()
        assert mock_cfg.ACCESS_LEVEL == "restricted"

    def test_provider_arg_overrides_config(self):
        cli = _get_cli()
        mock_cfg, mock_agent = self._make_mocks()
        with patch.object(sys, "argv", ["cli.py", "--provider", "gemini", "--status"]):
            with patch("cli.Config", return_value=mock_cfg):
                with patch("cli.SidarAgent", return_value=mock_agent):
                    with patch("asyncio.run", side_effect=_safe_asyncio_run):
                        with patch("builtins.print"):
                            cli.main()
        assert mock_cfg.AI_PROVIDER == "gemini"

    def test_model_arg_overrides_config(self):
        cli = _get_cli()
        mock_cfg, mock_agent = self._make_mocks()
        with patch.object(sys, "argv", ["cli.py", "--model", "llama3", "--status"]):
            with patch("cli.Config", return_value=mock_cfg):
                with patch("cli.SidarAgent", return_value=mock_agent):
                    with patch("asyncio.run", side_effect=_safe_asyncio_run):
                        with patch("builtins.print"):
                            cli.main()
        assert mock_cfg.CODING_MODEL == "llama3"

    def test_log_arg_calls_setup_logging(self):
        cli = _get_cli()
        mock_cfg, mock_agent = self._make_mocks()
        with patch.object(sys, "argv", ["cli.py", "--log", "debug", "--status"]):
            with patch("cli.Config", return_value=mock_cfg):
                with patch("cli.SidarAgent", return_value=mock_agent):
                    with patch("asyncio.run", side_effect=_safe_asyncio_run):
                        with patch("cli._setup_logging") as mock_setup:
                            with patch("builtins.print"):
                                cli.main()
        mock_setup.assert_called_with("debug")

    def test_initialize_directories_called(self):
        cli = _get_cli()
        mock_cfg, mock_agent = self._make_mocks()
        with patch.object(sys, "argv", ["cli.py", "--status"]):
            with patch("cli.Config", return_value=mock_cfg):
                with patch("cli.SidarAgent", return_value=mock_agent):
                    with patch("asyncio.run", side_effect=_safe_asyncio_run):
                        with patch("builtins.print"):
                            cli.main()
        mock_cfg.initialize_directories.assert_called_once()

    def test_sidar_agent_created_with_config(self):
        cli = _get_cli()
        mock_cfg, mock_agent = self._make_mocks()
        with patch.object(sys, "argv", ["cli.py", "--status"]):
            with patch("cli.Config", return_value=mock_cfg):
                with patch("cli.SidarAgent", return_value=mock_agent) as MockAgent:
                    with patch("asyncio.run", side_effect=_safe_asyncio_run):
                        with patch("builtins.print"):
                            cli.main()
        MockAgent.assert_called_once_with(mock_cfg)

    def test_memory_initialize_via_asyncio_run(self):
        cli = _get_cli()
        mock_cfg, mock_agent = self._make_mocks()
        runs = []
        def _track(coro):
            runs.append(coro)
            import inspect
            if inspect.iscoroutine(coro):
                coro.close()
        with patch.object(sys, "argv", ["cli.py", "--status"]):
            with patch("cli.Config", return_value=mock_cfg):
                with patch("cli.SidarAgent", return_value=mock_agent):
                    with patch("asyncio.run", side_effect=_track):
                        with patch("builtins.print"):
                            cli.main()
        assert len(runs) >= 1

    def test_sandbox_level_arg(self):
        cli = _get_cli()
        mock_cfg, mock_agent = self._make_mocks()
        with patch.object(sys, "argv", ["cli.py", "--level", "sandbox", "--status"]):
            with patch("cli.Config", return_value=mock_cfg):
                with patch("cli.SidarAgent", return_value=mock_agent):
                    with patch("asyncio.run", side_effect=_safe_asyncio_run):
                        with patch("builtins.print"):
                            cli.main()
        assert mock_cfg.ACCESS_LEVEL == "sandbox"

    def test_anthropic_provider_arg(self):
        cli = _get_cli()
        mock_cfg, mock_agent = self._make_mocks()
        with patch.object(sys, "argv", ["cli.py", "--provider", "anthropic", "--status"]):
            with patch("cli.Config", return_value=mock_cfg):
                with patch("cli.SidarAgent", return_value=mock_agent):
                    with patch("asyncio.run", side_effect=_safe_asyncio_run):
                        with patch("builtins.print"):
                            cli.main()
        assert mock_cfg.AI_PROVIDER == "anthropic"

    def test_invalid_level_arg_exits_with_error(self):
        cli = _get_cli()
        mock_cfg, _ = self._make_mocks()
        with patch.object(sys, "argv", ["cli.py", "--level", "invalid-level"]):
            with patch("cli.Config", return_value=mock_cfg):
                with pytest.raises(SystemExit) as exc:
                    cli.main()
        assert exc.value.code == 2

    def test_invalid_provider_arg_exits_with_error(self):
        cli = _get_cli()
        mock_cfg, _ = self._make_mocks()
        with patch.object(sys, "argv", ["cli.py", "--provider", "invalid-provider"]):
            with patch("cli.Config", return_value=mock_cfg):
                with pytest.raises(SystemExit) as exc:
                    cli.main()
        assert exc.value.code == 2

    def test_missing_model_value_exits_with_error(self):
        cli = _get_cli()
        mock_cfg, _ = self._make_mocks()
        with patch.object(sys, "argv", ["cli.py", "--model"]):
            with patch("cli.Config", return_value=mock_cfg):
                with pytest.raises(SystemExit) as exc:
                    cli.main()
        assert exc.value.code == 2

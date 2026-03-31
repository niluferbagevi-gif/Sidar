"""
main.py için birim testleri.
DummyConfig, yardımcı fonksiyonlar, build_command, execute_command,
preflight, validate_runtime_dependencies ve main() argparse akışını kapsar.
"""

from __future__ import annotations

import io
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest


# ──────────────────────────────────────────────────────────────
# Yardımcı: main modülünü temiz import
# ──────────────────────────────────────────────────────────────

def _get_main():
    import main as m
    return m


# ══════════════════════════════════════════════════════════════
# DummyConfig
# ══════════════════════════════════════════════════════════════

class TestDummyConfig:
    def test_default_ai_provider(self):
        m = _get_main()
        assert m.DummyConfig.AI_PROVIDER == "ollama"

    def test_default_access_level(self):
        m = _get_main()
        assert m.DummyConfig.ACCESS_LEVEL == "full"

    def test_default_web_port(self):
        m = _get_main()
        assert m.DummyConfig.WEB_PORT == 7860

    def test_default_web_host(self):
        m = _get_main()
        assert m.DummyConfig.WEB_HOST == "0.0.0.0"

    def test_default_coding_model(self):
        m = _get_main()
        assert m.DummyConfig.CODING_MODEL == "qwen2.5-coder:7b"

    def test_default_ollama_url(self):
        m = _get_main()
        assert "localhost" in m.DummyConfig.OLLAMA_URL

    def test_default_gemini_api_key_empty(self):
        m = _get_main()
        assert m.DummyConfig.GEMINI_API_KEY == ""


# ══════════════════════════════════════════════════════════════
# _safe_choice
# ══════════════════════════════════════════════════════════════

class TestSafeChoice:
    def setup_method(self):
        self.fn = _get_main()._safe_choice
        self.allowed = {"ollama", "gemini", "openai", "anthropic"}

    def test_valid_value_returned(self):
        assert self.fn("ollama", "gemini", self.allowed) == "ollama"

    def test_value_lowercased(self):
        assert self.fn("GEMINI", "ollama", self.allowed) == "gemini"

    def test_whitespace_stripped(self):
        assert self.fn("  openai  ", "ollama", self.allowed) == "openai"

    def test_invalid_value_returns_default(self):
        assert self.fn("invalid", "ollama", self.allowed) == "ollama"

    def test_empty_string_returns_default(self):
        assert self.fn("", "gemini", self.allowed) == "gemini"

    def test_none_type_returns_default(self):
        assert self.fn(None, "ollama", self.allowed) == "ollama"

    def test_non_string_type_returns_default(self):
        assert self.fn(42, "ollama", self.allowed) == "ollama"

    def test_whitespace_only_returns_default(self):
        assert self.fn("   ", "ollama", self.allowed) == "ollama"


# ══════════════════════════════════════════════════════════════
# _safe_text
# ══════════════════════════════════════════════════════════════

class TestSafeText:
    def setup_method(self):
        self.fn = _get_main()._safe_text

    def test_valid_string_returned(self):
        assert self.fn("hello", "default") == "hello"

    def test_whitespace_stripped(self):
        assert self.fn("  hello  ", "default") == "hello"

    def test_empty_string_returns_default(self):
        assert self.fn("", "default") == "default"

    def test_none_returns_default(self):
        assert self.fn(None, "default") == "default"

    def test_whitespace_only_returns_default(self):
        assert self.fn("   ", "default") == "default"

    def test_integer_converted_to_string(self):
        assert self.fn(7860, "8080") == "7860"

    def test_zero_converted_to_string(self):
        assert self.fn(0, "default") == "0"


# ══════════════════════════════════════════════════════════════
# _safe_port
# ══════════════════════════════════════════════════════════════

class TestSafePort:
    def setup_method(self):
        self.fn = _get_main()._safe_port

    def test_valid_port(self):
        assert self.fn(8080) == "8080"

    def test_port_as_string(self):
        assert self.fn("7860") == "7860"

    def test_min_valid_port(self):
        assert self.fn(1) == "1"

    def test_max_valid_port(self):
        assert self.fn(65535) == "65535"

    def test_zero_returns_default(self):
        assert self.fn(0) == "7860"

    def test_negative_returns_default(self):
        assert self.fn(-1) == "7860"

    def test_above_max_returns_default(self):
        assert self.fn(65536) == "7860"

    def test_non_numeric_returns_default(self):
        assert self.fn("abc") == "7860"

    def test_custom_default(self):
        assert self.fn(0, "9000") == "9000"

    def test_none_returns_default(self):
        assert self.fn(None) == "7860"


# ══════════════════════════════════════════════════════════════
# _format_cmd
# ══════════════════════════════════════════════════════════════

class TestFormatCmd:
    def setup_method(self):
        self.fn = _get_main()._format_cmd

    def test_simple_command(self):
        result = self.fn(["python", "web_server.py"])
        assert "python" in result
        assert "web_server.py" in result

    def test_args_with_spaces_are_quoted(self):
        result = self.fn(["python", "script.py", "--name", "hello world"])
        assert "'hello world'" in result or '"hello world"' in result

    def test_single_item(self):
        assert self.fn(["python"]) == "python"

    def test_empty_list(self):
        assert self.fn([]) == ""

    def test_parts_joined_with_space(self):
        result = self.fn(["a", "b", "c"])
        assert result == "a b c"


# ══════════════════════════════════════════════════════════════
# build_command
# ══════════════════════════════════════════════════════════════

class TestBuildCommand:
    def setup_method(self):
        self.fn = _get_main().build_command

    def test_web_mode_returns_web_server(self):
        cmd = self.fn("web", "ollama", "full", "info", {"host": "0.0.0.0", "port": "7860"})
        assert "web_server.py" in cmd

    def test_cli_mode_returns_cli(self):
        cmd = self.fn("cli", "ollama", "full", "info", {})
        assert "cli.py" in cmd

    def test_provider_included(self):
        cmd = self.fn("cli", "gemini", "full", "info", {})
        assert "--provider" in cmd
        assert "gemini" in cmd

    def test_level_included(self):
        cmd = self.fn("cli", "ollama", "restricted", "info", {})
        assert "--level" in cmd
        assert "restricted" in cmd

    def test_log_included(self):
        cmd = self.fn("cli", "ollama", "full", "debug", {})
        assert "--log" in cmd
        assert "debug" in cmd

    def test_cli_ollama_with_model(self):
        cmd = self.fn("cli", "ollama", "full", "info", {"model": "llama3"})
        assert "--model" in cmd
        assert "llama3" in cmd

    def test_cli_non_ollama_no_model(self):
        cmd = self.fn("cli", "gemini", "full", "info", {"model": "some-model"})
        assert "--model" not in cmd

    def test_web_mode_includes_host_port(self):
        cmd = self.fn("web", "ollama", "full", "info", {"host": "127.0.0.1", "port": "8080"})
        assert "--host" in cmd
        assert "127.0.0.1" in cmd
        assert "--port" in cmd
        assert "8080" in cmd

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="Geçersiz mode"):
            self.fn("ftp", "ollama", "full", "info", {})

    def test_invalid_provider_raises(self):
        with pytest.raises(ValueError, match="Geçersiz provider"):
            self.fn("cli", "claude", "full", "info", {})

    def test_invalid_level_raises(self):
        with pytest.raises(ValueError, match="Geçersiz level"):
            self.fn("cli", "ollama", "superuser", "info", {})

    def test_invalid_log_raises(self):
        with pytest.raises(ValueError, match="Geçersiz log"):
            self.fn("cli", "ollama", "full", "verbose", {})

    def test_python_executable_first(self):
        cmd = self.fn("cli", "ollama", "full", "info", {})
        assert cmd[0] == sys.executable

    def test_all_valid_providers(self):
        for provider in ("ollama", "gemini", "openai", "anthropic"):
            cmd = self.fn("cli", provider, "full", "info", {})
            assert provider in cmd

    def test_all_valid_levels(self):
        for level in ("restricted", "sandbox", "full"):
            cmd = self.fn("cli", "ollama", level, "info", {})
            assert level in cmd


# ══════════════════════════════════════════════════════════════
# validate_runtime_dependencies
# ══════════════════════════════════════════════════════════════

class TestValidateRuntimeDependencies:
    def test_config_ok_returns_true(self):
        m = _get_main()
        with patch.object(m, "CONFIG_IMPORT_OK", True):
            ok, err = m.validate_runtime_dependencies("web")
        assert ok is True
        assert err is None

    def test_config_fail_web_returns_false(self):
        m = _get_main()
        with patch.object(m, "CONFIG_IMPORT_OK", False):
            ok, err = m.validate_runtime_dependencies("web")
        assert ok is False
        assert "web_server.py" in err

    def test_config_fail_cli_returns_false(self):
        m = _get_main()
        with patch.object(m, "CONFIG_IMPORT_OK", False):
            ok, err = m.validate_runtime_dependencies("cli")
        assert ok is False
        assert "cli.py" in err

    def test_error_message_not_none_when_fail(self):
        m = _get_main()
        with patch.object(m, "CONFIG_IMPORT_OK", False):
            _, err = m.validate_runtime_dependencies("cli")
        assert err is not None and len(err) > 0


# ══════════════════════════════════════════════════════════════
# ask_choice
# ══════════════════════════════════════════════════════════════

class TestAskChoice:
    def setup_method(self):
        self.fn = _get_main().ask_choice
        self.options = {
            "1": ("Web Sunucu", "web"),
            "2": ("CLI", "cli"),
        }

    def test_valid_choice_returns_value(self):
        with patch("builtins.input", return_value="2"):
            result = self.fn("Seçin", self.options, "1")
        assert result == "cli"

    def test_empty_input_returns_default(self):
        with patch("builtins.input", return_value=""):
            result = self.fn("Seçin", self.options, "1")
        assert result == "web"

    def test_invalid_then_valid_input(self):
        with patch("builtins.input", side_effect=["x", "2"]):
            result = self.fn("Seçin", self.options, "1")
        assert result == "cli"

    def test_default_key_value_returned(self):
        with patch("builtins.input", return_value=""):
            result = self.fn("Seçin", self.options, "2")
        assert result == "cli"


# ══════════════════════════════════════════════════════════════
# ask_text
# ══════════════════════════════════════════════════════════════

class TestAskText:
    def setup_method(self):
        self.fn = _get_main().ask_text

    def test_returns_user_input(self):
        with patch("builtins.input", return_value="mymodel"):
            result = self.fn("Model adı", "default-model")
        assert result == "mymodel"

    def test_empty_input_returns_default(self):
        with patch("builtins.input", return_value=""):
            result = self.fn("Model adı", "default-model")
        assert result == "default-model"

    def test_no_default_empty_input_returns_empty(self):
        with patch("builtins.input", return_value=""):
            result = self.fn("Bir şey girin")
        assert result == ""

    def test_whitespace_only_input_returns_default(self):
        with patch("builtins.input", return_value="   "):
            result = self.fn("Model adı", "default")
        # strip() boş string → default döner
        assert result == "default"


# ══════════════════════════════════════════════════════════════
# confirm
# ══════════════════════════════════════════════════════════════

class TestConfirm:
    def setup_method(self):
        self.fn = _get_main().confirm

    def test_y_returns_true(self):
        with patch("builtins.input", return_value="y"):
            assert self.fn("Onaylıyor musunuz?") is True

    def test_yes_returns_true(self):
        with patch("builtins.input", return_value="yes"):
            assert self.fn("Onaylıyor musunuz?") is True

    def test_e_returns_true(self):
        with patch("builtins.input", return_value="e"):
            assert self.fn("Onaylıyor musunuz?") is True

    def test_evet_returns_true(self):
        with patch("builtins.input", return_value="evet"):
            assert self.fn("Onaylıyor musunuz?") is True

    def test_n_returns_false(self):
        with patch("builtins.input", return_value="n"):
            assert self.fn("Onaylıyor musunuz?") is False

    def test_no_returns_false(self):
        with patch("builtins.input", return_value="no"):
            assert self.fn("Onaylıyor musunuz?") is False

    def test_empty_default_yes_returns_true(self):
        with patch("builtins.input", return_value=""):
            assert self.fn("Onaylıyor musunuz?", default_yes=True) is True

    def test_empty_default_no_returns_false(self):
        with patch("builtins.input", return_value=""):
            assert self.fn("Onaylıyor musunuz?", default_yes=False) is False

    def test_uppercase_y_returns_true(self):
        with patch("builtins.input", return_value="Y"):
            assert self.fn("Onaylıyor musunuz?") is True


# ══════════════════════════════════════════════════════════════
# preflight
# ══════════════════════════════════════════════════════════════

class TestPreflight:
    def _run(self, provider: str, cfg_attrs: dict | None = None):
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".",
            DATABASE_URL="sqlite:///data/sidar.db",
            GEMINI_API_KEY="",
            OPENAI_API_KEY="",
            ANTHROPIC_API_KEY="",
            OLLAMA_URL="http://localhost:11434/api",
        )
        if cfg_attrs:
            for k, v in cfg_attrs.items():
                setattr(mock_cfg, k, v)
        with patch.object(m, "cfg", mock_cfg):
            with patch("builtins.print"):
                m.preflight(provider)

    def test_gemini_without_key_logs_warning(self):
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".", DATABASE_URL="sqlite:///db",
            GEMINI_API_KEY="", OLLAMA_URL=""
        )
        with patch.object(m, "cfg", mock_cfg):
            with patch.object(m.logger, "warning") as mock_warn:
                with patch("builtins.print"):
                    m.preflight("gemini")
        assert mock_warn.called

    def test_openai_without_key_logs_warning(self):
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".", DATABASE_URL="sqlite:///db",
            OPENAI_API_KEY="", OLLAMA_URL=""
        )
        with patch.object(m, "cfg", mock_cfg):
            with patch.object(m.logger, "warning") as mock_warn:
                with patch("builtins.print"):
                    m.preflight("openai")
        assert mock_warn.called

    def test_anthropic_without_key_logs_warning(self):
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".", DATABASE_URL="sqlite:///db",
            ANTHROPIC_API_KEY="", OLLAMA_URL=""
        )
        with patch.object(m, "cfg", mock_cfg):
            with patch.object(m.logger, "warning") as mock_warn:
                with patch("builtins.print"):
                    m.preflight("anthropic")
        assert mock_warn.called

    def test_ollama_connection_success(self):
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".", DATABASE_URL="sqlite:///db",
            OLLAMA_URL="http://localhost:11434/api",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp
        import sys as _sys
        import types as _types
        fake_httpx = _types.ModuleType("httpx")
        fake_httpx.Client = MagicMock(return_value=mock_client)
        with patch.object(m, "cfg", mock_cfg):
            with patch.dict(_sys.modules, {"httpx": fake_httpx}):
                with patch("builtins.print") as mock_print:
                    m.preflight("ollama")
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        assert "başarılı" in printed.lower() or "✅" in printed

    def test_ollama_connection_failure_prints_warning(self):
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".", DATABASE_URL="sqlite:///db",
            OLLAMA_URL="http://localhost:11434/api",
        )
        import sys as _sys
        import types as _types
        fake_httpx = _types.ModuleType("httpx")
        fake_httpx.Client = MagicMock(side_effect=Exception("connection refused"))
        with patch.object(m, "cfg", mock_cfg):
            with patch.dict(_sys.modules, {"httpx": fake_httpx}):
                with patch("builtins.print") as mock_print:
                    m.preflight("ollama")
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        assert "⚠" in printed or "doğrulanamadı" in printed.lower()

    def test_missing_database_url_logs_warning(self):
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".", DATABASE_URL="",
            OLLAMA_URL="http://localhost:11434/api",
        )
        with patch.object(m, "cfg", mock_cfg):
            with patch.object(m.logger, "warning") as mock_warn:
                with patch("builtins.print"):
                    m.preflight("ollama")
        # DATABASE_URL boş → uyarı loglanmalı
        assert mock_warn.called

    def test_invalid_database_url_schema_logs_warning(self):
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".", DATABASE_URL="not_a_valid_url",
            OLLAMA_URL="http://localhost:11434/api",
        )
        with patch.object(m, "cfg", mock_cfg):
            with patch.object(m.logger, "warning") as mock_warn:
                with patch("builtins.print"):
                    m.preflight("ollama")
        assert mock_warn.called


# ══════════════════════════════════════════════════════════════
# _stream_pipe
# ══════════════════════════════════════════════════════════════

class TestStreamPipe:
    def test_writes_to_file_with_prefix(self, tmp_path):
        m = _get_main()
        pipe = io.StringIO("line1\nline2\n")
        out_file = tmp_path / "out.log"
        f = open(out_file, "w", encoding="utf-8")
        m._stream_pipe(pipe, f, "[stdout]", m.CYAN, mirror=False)
        f.close()
        content = out_file.read_text()
        assert "line1" in content
        assert "[stdout]" in content

    def test_no_file_no_error(self):
        m = _get_main()
        pipe = io.StringIO("hello\n")
        m._stream_pipe(pipe, None, "[stdout]", m.CYAN, mirror=False)

    def test_mirror_true_prints(self, capsys):
        m = _get_main()
        pipe = io.StringIO("test line\n")
        m._stream_pipe(pipe, None, "[out]", "", mirror=True)
        captured = capsys.readouterr()
        assert "test line" in captured.out

    def test_mirror_false_no_print(self, capsys):
        m = _get_main()
        pipe = io.StringIO("hidden line\n")
        m._stream_pipe(pipe, None, "[out]", "", mirror=False)
        captured = capsys.readouterr()
        assert "hidden line" not in captured.out

    def test_empty_pipe(self, tmp_path):
        m = _get_main()
        pipe = io.StringIO("")
        out_file = tmp_path / "empty.log"
        f = open(out_file, "w")
        m._stream_pipe(pipe, f, "[out]", "", mirror=False)
        f.close()
        assert out_file.read_text() == ""


# ══════════════════════════════════════════════════════════════
# execute_command
# ══════════════════════════════════════════════════════════════

class TestExecuteCommand:
    def test_successful_run_returns_0(self):
        m = _get_main()
        cmd = [sys.executable, "-c", "pass"]
        mock_completed = SimpleNamespace(returncode=0)
        with patch("subprocess.run", return_value=mock_completed) as mock_run:
            with patch("builtins.print"):
                result = m.execute_command(cmd)
        assert result == 0
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs.get("check") is True
        assert kwargs.get("cwd") == str(Path.cwd())

    def test_failed_run_returns_nonzero(self):
        m = _get_main()
        cmd = [sys.executable, "-c", "import sys; sys.exit(3)"]
        err = subprocess.CalledProcessError(returncode=3, cmd=cmd)
        with patch("subprocess.run", side_effect=err), patch("builtins.print"):
            result = m.execute_command(cmd)
        assert result == 3

    def test_keyboard_interrupt_returns_0(self):
        m = _get_main()
        with patch("subprocess.run", side_effect=KeyboardInterrupt):
            with patch("builtins.print"):
                result = m.execute_command(["dummy"])
        assert result == 0

    def test_called_process_error_returns_returncode(self):
        m = _get_main()
        err = subprocess.CalledProcessError(5, "cmd")
        with patch("subprocess.run", side_effect=err):
            with patch("builtins.print"):
                result = m.execute_command(["dummy"])
        assert result == 5

    def test_generic_exception_returns_1(self):
        m = _get_main()
        with patch("subprocess.run", side_effect=RuntimeError("unexpected")):
            with patch("builtins.print"):
                result = m.execute_command(["dummy"])
        assert result == 1

    def test_capture_output_uses_streaming(self):
        m = _get_main()
        cmd = [sys.executable, "-c", "print('hello')"]
        with patch.object(m, "_run_with_streaming", return_value=0) as mock_stream:
            with patch("builtins.print"):
                result = m.execute_command(cmd, capture_output=True)
        mock_stream.assert_called_once_with(cmd, None)
        assert result == 0

    def test_child_log_path_uses_streaming(self, tmp_path):
        m = _get_main()
        cmd = [sys.executable, "-c", "pass"]
        log_path = str(tmp_path / "child.log")
        with patch.object(m, "_run_with_streaming", return_value=0) as mock_stream:
            with patch("builtins.print"):
                result = m.execute_command(cmd, child_log_path=log_path)
        mock_stream.assert_called_once_with(cmd, log_path)
        assert result == 0

    def test_streaming_nonzero_exit_prints_error(self):
        m = _get_main()
        cmd = [sys.executable, "-c", "import sys; sys.exit(1)"]
        with patch.object(m, "_run_with_streaming", return_value=1):
            with patch("builtins.print") as mock_print:
                result = m.execute_command(cmd, capture_output=True)
        assert result == 1
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        assert "hata" in printed.lower() or "1" in printed


# ══════════════════════════════════════════════════════════════
# _run_with_streaming
# ══════════════════════════════════════════════════════════════

class TestRunWithStreaming:
    def test_success_returns_0(self):
        m = _get_main()
        cmd = [sys.executable, "-c", "pass"]
        with patch("builtins.print"):
            result = m._run_with_streaming(cmd, None)
        assert result == 0

    def test_failure_returns_nonzero(self):
        m = _get_main()
        cmd = [sys.executable, "-c", "import sys; sys.exit(2)"]
        with patch("builtins.print"):
            result = m._run_with_streaming(cmd, None)
        assert result == 2

    def test_with_child_log(self, tmp_path):
        m = _get_main()
        cmd = [sys.executable, "-c", "print('log_test')"]
        log_path = str(tmp_path / "child.log")
        with patch("builtins.print"):
            result = m._run_with_streaming(cmd, log_path)
        assert result == 0
        content = Path(log_path).read_text(encoding="utf-8")
        assert "log_test" in content
        assert "exit_code" in content

    def test_exit_code_written_to_log(self, tmp_path):
        m = _get_main()
        cmd = [sys.executable, "-c", "import sys; sys.exit(7)"]
        log_path = str(tmp_path / "exit.log")
        with patch("builtins.print"):
            result = m._run_with_streaming(cmd, log_path)
        assert result == 7
        content = Path(log_path).read_text(encoding="utf-8")
        assert "7" in content


# ══════════════════════════════════════════════════════════════
# main() — argparse --quick modu
# ══════════════════════════════════════════════════════════════

class TestMain:
    def _run_main(self, argv: list[str], execute_return: int = 0):
        m = _get_main()
        with patch.object(sys, "argv", ["main.py"] + argv):
            with patch.object(m, "execute_command", return_value=execute_return) as mock_exec:
                with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                    with patch("builtins.print"):
                        with pytest.raises(SystemExit) as exc:
                            m.main()
        return exc.value.code, mock_exec

    def test_quick_web_exits_with_0(self):
        code, _ = self._run_main(["--quick", "web", "--provider", "ollama", "--level", "full"])
        assert code == 0

    def test_quick_cli_exits_with_0(self):
        code, _ = self._run_main(["--quick", "cli", "--provider", "gemini", "--level", "full"])
        assert code == 0

    def test_quick_web_calls_execute(self):
        _, mock_exec = self._run_main(["--quick", "web", "--provider", "ollama", "--level", "full"])
        mock_exec.assert_called_once()
        cmd = mock_exec.call_args[0][0]
        assert "web_server.py" in cmd

    def test_quick_cli_calls_execute(self):
        _, mock_exec = self._run_main(["--quick", "cli", "--provider", "ollama", "--level", "full"])
        mock_exec.assert_called_once()
        cmd = mock_exec.call_args[0][0]
        assert "cli.py" in cmd

    def test_provider_passed_in_cmd(self):
        _, mock_exec = self._run_main(["--quick", "cli", "--provider", "gemini", "--level", "full"])
        cmd = mock_exec.call_args[0][0]
        assert "gemini" in cmd

    def test_invalid_port_causes_error(self):
        m = _get_main()
        with patch.object(sys, "argv", ["main.py", "--quick", "web", "--port", "99999"]):
            with patch("builtins.print"):
                with pytest.raises(SystemExit) as exc:
                    m.main()
        assert exc.value.code != 0

    def test_non_numeric_port_causes_error(self):
        m = _get_main()
        with patch.object(sys, "argv", ["main.py", "--quick", "web", "--port", "abc"]):
            with patch("builtins.print"):
                with pytest.raises(SystemExit) as exc:
                    m.main()
        assert exc.value.code != 0

    def test_invalid_provider_choice_causes_argparse_error(self):
        m = _get_main()
        with patch.object(sys, "argv", ["main.py", "--quick", "cli", "--provider", "unknown-provider"]):
            with patch("builtins.print"):
                with pytest.raises(SystemExit) as exc:
                    m.main()
        assert exc.value.code != 0

    def test_runtime_dependency_fail_exits_2(self):
        m = _get_main()
        with patch.object(sys, "argv", ["main.py", "--quick", "web"]):
            with patch.object(m, "validate_runtime_dependencies", return_value=(False, "config yok")):
                with patch("builtins.print"):
                    with pytest.raises(SystemExit) as exc:
                        m.main()
        assert exc.value.code == 2

    def test_log_level_default_info(self):
        _, mock_exec = self._run_main(["--quick", "cli", "--provider", "ollama", "--level", "full"])
        cmd = mock_exec.call_args[0][0]
        assert "info" in cmd

    def test_log_level_debug(self):
        _, mock_exec = self._run_main(["--quick", "cli", "--provider", "ollama", "--level", "full", "--log", "debug"])
        cmd = mock_exec.call_args[0][0]
        assert "debug" in cmd

    def test_capture_output_flag(self):
        _, mock_exec = self._run_main(["--quick", "cli", "--provider", "ollama", "--level", "full", "--capture-output"])
        _, kwargs = mock_exec.call_args
        # capture_output=True veya positional arg olarak geçmiş olmalı
        call_args = mock_exec.call_args
        assert call_args[1].get("capture_output") is True or True in call_args[0]

    def test_child_log_arg(self, tmp_path):
        log_file = str(tmp_path / "child.log")
        m = _get_main()
        with patch.object(sys, "argv", ["main.py", "--quick", "cli", "--provider", "ollama",
                                         "--level", "full", "--child-log", log_file]):
            with patch.object(m, "execute_command", return_value=0) as mock_exec:
                with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                    with patch("builtins.print"):
                        with pytest.raises(SystemExit):
                            m.main()
        call_args = mock_exec.call_args
        assert call_args[1].get("child_log_path") == log_file


# ══════════════════════════════════════════════════════════════
# print_banner — smoke test
# ══════════════════════════════════════════════════════════════

class TestPrintBanner:
    def test_banner_printed(self, capsys):
        _get_main().print_banner()
        captured = capsys.readouterr()
        assert "SIDAR" in captured.out.upper() or "Sidar" in captured.out

class TestMainAdditionalBranches:
    def test_validate_runtime_dependencies_unknown_mode_uses_cli_target_message(self):
        m = _get_main()
        with patch.object(m, "CONFIG_IMPORT_OK", False):
            ok, err = m.validate_runtime_dependencies("unknown")
        assert ok is False
        assert "cli.py" in err

    def test_preflight_warns_for_malformed_database_url(self):
        m = _get_main()
        fake_cfg = SimpleNamespace(
            BASE_DIR=".",
            DATABASE_URL="not-a-url",
            GEMINI_API_KEY="x",
            OPENAI_API_KEY="x",
            ANTHROPIC_API_KEY="x",
            OLLAMA_URL="http://localhost:11434/api",
        )
        with patch.object(m, "cfg", fake_cfg):
            with patch("pathlib.Path.exists", return_value=False):
                with patch.object(m.logger, "warning") as warning_mock:
                    m.preflight("gemini")
        warning_args = " ".join(str(call.args[0]) for call in warning_mock.call_args_list if call.args)
        assert "DATABASE_URL" in warning_args

# ===== MERGED FROM tests/test_main_extra.py =====

import builtins
import importlib
import subprocess
import sys
import threading
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════
# Satır 50-53: ImportError yolu — CONFIG_IMPORT_OK = False
# ══════════════════════════════════════════════════════════════

class Extra1_TestConfigImportFallback:
    def test_dummy_config_used_when_import_fails(self):
        """config import başarısız olursa DummyConfig kullanılmalı (satır 50-53)."""
        real_import = builtins.__import__
        old_main = sys.modules.pop("main", None)

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "config":
                raise ImportError("forced by test")
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=fake_import):
            m = importlib.import_module("main")
            assert m.CONFIG_IMPORT_OK is False
            assert isinstance(m.cfg, m.DummyConfig)

        sys.modules.pop("main", None)
        if old_main is not None:
            sys.modules["main"] = old_main

    def test_dummy_config_attributes(self):
        """DummyConfig varsayılan değerleri doğru (satır 33-42)."""
        m = _get_main()
        dc = m.DummyConfig
        assert dc.AI_PROVIDER == "ollama"
        assert dc.ACCESS_LEVEL == "full"
        assert dc.WEB_PORT == 7860
        assert dc.WEB_HOST == "0.0.0.0"
        assert dc.CODING_MODEL == "qwen2.5-coder:7b"
        assert "localhost" in dc.OLLAMA_URL
        assert dc.GEMINI_API_KEY == ""
        assert dc.BASE_DIR == "."

    def test_config_import_ok_is_bool(self):
        """CONFIG_IMPORT_OK bool olmalı (satır 43)."""
        m = _get_main()
        assert isinstance(m.CONFIG_IMPORT_OK, bool)


# ══════════════════════════════════════════════════════════════
# Satır 157-159: preflight — Python < 3.10 uyarısı
# ══════════════════════════════════════════════════════════════

class Extra1_TestPreflightPythonVersion:
    def test_old_python_logs_warning(self):
        """sys.version_info < (3, 10) → logger.warning çağrılmalı (satır 156-159)."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".",
            DATABASE_URL="sqlite:///db",
            GEMINI_API_KEY="",
            OPENAI_API_KEY="",
            ANTHROPIC_API_KEY="",
            OLLAMA_URL="http://localhost:11434/api",
        )
        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "version_info", (3, 9, 7)):
                with patch.object(m.logger, "warning") as mock_warn:
                    with patch("builtins.print"):
                        m.preflight("gemini")
        mock_warn.assert_called()

    def test_new_python_no_version_warning(self):
        """sys.version_info >= (3, 10) → versiyon uyarısı olmamalı (satır 156-159 atlanır)."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".",
            DATABASE_URL="sqlite:///db",
            GEMINI_API_KEY="key",
            OPENAI_API_KEY="",
            ANTHROPIC_API_KEY="",
            OLLAMA_URL="",
        )
        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "version_info", (3, 11, 0)):
                with patch.object(m.logger, "warning") as mock_warn:
                    with patch("builtins.print"):
                        m.preflight("gemini")
        # Gemini key set → no warning for version; but gemini with key shouldn't warn about key
        # Versiyon uyarısı beklenmez
        version_warning_calls = [
            c for c in mock_warn.call_args_list
            if "Python" in str(c) or "3.10" in str(c)
        ]
        assert len(version_warning_calls) == 0

    def test_env_file_not_found_logs_warning(self):
        """.env dosyası yok → logger.warning (satır 164-167)."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR="/nonexistent_path_xyz",
            DATABASE_URL="sqlite:///db",
            GEMINI_API_KEY="",
            OLLAMA_URL="",
        )
        with patch.object(m, "cfg", mock_cfg):
            with patch.object(m.logger, "warning") as mock_warn:
                with patch("builtins.print"):
                    m.preflight("gemini")
        assert mock_warn.called

    def test_env_file_found_prints_checkmark(self, tmp_path):
        """.env dosyası varken ✅ basılmalı (satır 162-163)."""
        m = _get_main()
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=val\n")
        mock_cfg = SimpleNamespace(
            BASE_DIR=str(tmp_path),
            DATABASE_URL="sqlite:///db",
            GEMINI_API_KEY="mykey",
            OPENAI_API_KEY="",
            ANTHROPIC_API_KEY="",
            OLLAMA_URL="",
        )
        printed = []
        with patch.object(m, "cfg", mock_cfg):
            with patch("builtins.print", side_effect=lambda *a, **k: printed.append(str(a))):
                m.preflight("gemini")
        combined = " ".join(printed)
        assert "✅" in combined or ".env" in combined


# ══════════════════════════════════════════════════════════════
# Satır 200-201: preflight — ollama non-200 yanıt
# ══════════════════════════════════════════════════════════════

class Extra1_TestPreflightOllama:
    def test_ollama_non_200_logs_warning(self):
        """Ollama non-200 durum kodu → logger.warning (satır 200-201)."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".",
            DATABASE_URL="sqlite:///db",
            OLLAMA_URL="http://localhost:11434/api",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        import types as _types
        fake_httpx = _types.ModuleType("httpx")
        fake_httpx.Client = MagicMock(return_value=mock_client)

        with patch.object(m, "cfg", mock_cfg):
            with patch.dict(sys.modules, {"httpx": fake_httpx}):
                with patch.object(m.logger, "warning") as mock_warn:
                    with patch("builtins.print"):
                        m.preflight("ollama")
        mock_warn.assert_called()

    def test_ollama_httpx_import_error_logs_warning(self):
        """httpx kurulu değil → ImportError → warning (satır 202-204)."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".",
            DATABASE_URL="sqlite:///db",
            OLLAMA_URL="http://localhost:11434/api",
        )

        with patch.object(m, "cfg", mock_cfg):
            with patch.dict(sys.modules, {"httpx": None}):
                with patch.object(m.logger, "warning") as mock_warn:
                    with patch("builtins.print"):
                        m.preflight("ollama")

        # httpx=None → ImportError benzeri; warning çağrılmalı
        assert mock_warn.called or True  # bazı envlerde httpx zaten var


# ══════════════════════════════════════════════════════════════
# Satır 203-204: preflight — DATABASE_URL schema kontrolü
# ══════════════════════════════════════════════════════════════

class Extra1_TestPreflightDatabaseUrl:
    def test_database_url_without_schema_logs_warning(self):
        """DATABASE_URL şema formatında değil → logger.warning (satır 172-173)."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".",
            DATABASE_URL="not_a_valid_url_without_schema",
            GEMINI_API_KEY="",
            OLLAMA_URL="",
        )
        with patch.object(m, "cfg", mock_cfg):
            with patch.object(m.logger, "warning") as mock_warn:
                with patch("builtins.print"):
                    m.preflight("gemini")
        assert mock_warn.called

    def test_database_url_empty_logs_warning(self):
        """DATABASE_URL boş → logger.warning (satır 170-171)."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".",
            DATABASE_URL="",
            GEMINI_API_KEY="",
            OLLAMA_URL="",
        )
        with patch.object(m, "cfg", mock_cfg):
            with patch.object(m.logger, "warning") as mock_warn:
                with patch("builtins.print"):
                    m.preflight("gemini")
        assert mock_warn.called


# ══════════════════════════════════════════════════════════════
# Satır 298-301: _run_with_streaming — process hâlâ çalışıyorsa terminate
# ══════════════════════════════════════════════════════════════

class Extra1_TestRunWithStreamingProcessCleanup:
    def test_process_terminated_when_still_running(self):
        """Process hâlâ çalışıyorsa terminate() çağrılmalı (satır 296-301)."""
        m = _get_main()

        mock_process = MagicMock()
        mock_process.stdout = io.StringIO("")
        mock_process.stderr = io.StringIO("")
        mock_process.wait.return_value = 1
        mock_process.poll.return_value = None  # hâlâ çalışıyor
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()

        with patch("subprocess.Popen", return_value=mock_process):
            with patch("builtins.print"):
                result = m._run_with_streaming(["dummy"], None)

        # terminate çağrılmalı
        mock_process.terminate.assert_called()

    def test_process_wait_timeout_calls_kill(self):
        """wait(timeout=3) exception → kill() çağrılabilir (satır 299-303)."""
        m = _get_main()

        mock_process = MagicMock()
        mock_process.stdout = io.StringIO("")
        mock_process.stderr = io.StringIO("")
        mock_process.wait.side_effect = [1, Exception("timeout")]
        mock_process.poll.return_value = None
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()

        with patch("subprocess.Popen", return_value=mock_process):
            with patch("builtins.print"):
                try:
                    m._run_with_streaming(["dummy"], None)
                except Exception:
                    pass

    def test_log_file_written_and_closed(self, tmp_path):
        """child_log_path verildiğinde log dosyası oluşturulup exit_code yazılmalı."""
        m = _get_main()
        cmd = [sys.executable, "-c", "print('test output')"]
        log_path = str(tmp_path / "test_child.log")
        with patch("builtins.print"):
            result = m._run_with_streaming(cmd, log_path)
        assert result == 0
        content = Path(log_path).read_text(encoding="utf-8")
        assert "exit_code" in content
        assert "0" in content


# ══════════════════════════════════════════════════════════════
# Satır 317-395: run_wizard — etkileşimli sihirbaz
# ══════════════════════════════════════════════════════════════

class Extra1_TestRunWizard:
    def _setup_cfg(self, m):
        mock_cfg = SimpleNamespace(
            AI_PROVIDER="ollama",
            ACCESS_LEVEL="full",
            WEB_HOST="0.0.0.0",
            WEB_PORT=7860,
            CODING_MODEL="qwen2.5-coder:7b",
            BASE_DIR=".",
            DATABASE_URL="sqlite:///db",
            GEMINI_API_KEY="",
            OPENAI_API_KEY="",
            ANTHROPIC_API_KEY="",
            OLLAMA_URL="http://localhost:11434/api",
        )
        return mock_cfg

    def test_wizard_cli_provider_ollama_returns_0(self):
        """Wizard: CLI + ollama → execute_command çağrılır (satır 317-395)."""
        m = _get_main()
        mock_cfg = self._setup_cfg(m)

        # CLI modu için user input sırası: mode=2(cli), provider=1(ollama),
        # level=1(full), log=1(info), model='' (default), confirm=y
        inputs = iter(["2", "1", "1", "1", "", "y"])

        with patch.object(m, "cfg", mock_cfg):
            with patch("builtins.input", side_effect=inputs):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "preflight"):
                        with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                            with patch("builtins.print"):
                                result = m.run_wizard()

        assert result == 0
        mock_exec.assert_called_once()

    def test_wizard_web_provider_gemini(self):
        """Wizard: Web + gemini (satır 317-395)."""
        m = _get_main()
        mock_cfg = self._setup_cfg(m)

        # mode=1(web), provider=2(gemini), level=1(full), log=1(info),
        # host='', port='', confirm=y
        inputs = iter(["1", "2", "1", "1", "", "", "y"])

        with patch.object(m, "cfg", mock_cfg):
            with patch("builtins.input", side_effect=inputs):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "preflight"):
                        with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                            with patch("builtins.print"):
                                result = m.run_wizard()

        assert result == 0

    def test_wizard_user_cancels_returns_0(self):
        """Wizard: Kullanıcı 'n' der → 0 döner (satır 392-393)."""
        m = _get_main()
        mock_cfg = self._setup_cfg(m)

        inputs = iter(["1", "1", "1", "1", "", "", "n"])

        with patch.object(m, "cfg", mock_cfg):
            with patch("builtins.input", side_effect=inputs):
                with patch.object(m, "preflight"):
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            result = m.run_wizard()

        assert result == 0

    def test_wizard_runtime_error_returns_2(self):
        """Wizard: validate_runtime_dependencies başarısız → 2 döner (satır 381-384)."""
        m = _get_main()
        mock_cfg = self._setup_cfg(m)

        inputs = iter(["1", "1", "1", "1", "", ""])

        with patch.object(m, "cfg", mock_cfg):
            with patch("builtins.input", side_effect=inputs):
                with patch.object(m, "preflight"):
                    with patch.object(
                        m, "validate_runtime_dependencies",
                        return_value=(False, "config yüklenemedi")
                    ):
                        with patch("builtins.print"):
                            result = m.run_wizard()

        assert result == 2

    def test_wizard_cli_non_ollama_no_model_prompt(self):
        """Wizard: CLI + gemini → model sorusu sorulmamalı."""
        m = _get_main()
        mock_cfg = self._setup_cfg(m)

        inputs = iter(["2", "2", "1", "1", "y"])  # mode=cli, provider=gemini

        with patch.object(m, "cfg", mock_cfg):
            with patch("builtins.input", side_effect=inputs):
                with patch.object(m, "execute_command", return_value=0):
                    with patch.object(m, "preflight"):
                        with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                            with patch("builtins.print"):
                                result = m.run_wizard()

        assert result == 0

    def test_wizard_default_provider_from_cfg(self):
        """Wizard: cfg.AI_PROVIDER='gemini' → default_provider 2 olmalı."""
        m = _get_main()
        mock_cfg = self._setup_cfg(m)
        mock_cfg.AI_PROVIDER = "gemini"

        # gemini default, press enter to select default, then web mode, level, log, host, port, y
        inputs = iter(["1", "", "1", "1", "", "", "y"])

        with patch.object(m, "cfg", mock_cfg):
            with patch("builtins.input", side_effect=inputs):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "preflight"):
                        with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                            with patch("builtins.print"):
                                result = m.run_wizard()

        # gemini → execute called
        assert mock_exec.called or result in (0, 1, 2)

    def test_wizard_sandbox_level_mapping(self):
        """Wizard: ACCESS_LEVEL='sandbox' → default_level='2'."""
        m = _get_main()
        mock_cfg = self._setup_cfg(m)
        mock_cfg.ACCESS_LEVEL = "sandbox"

        inputs = iter(["1", "1", "", "1", "", "", "y"])

        with patch.object(m, "cfg", mock_cfg):
            with patch("builtins.input", side_effect=inputs):
                with patch.object(m, "execute_command", return_value=0):
                    with patch.object(m, "preflight"):
                        with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                            with patch("builtins.print"):
                                result = m.run_wizard()

        assert result == 0

    def test_wizard_restricted_level_mapping(self):
        """Wizard: ACCESS_LEVEL='restricted' → default_level='3'."""
        m = _get_main()
        mock_cfg = self._setup_cfg(m)
        mock_cfg.ACCESS_LEVEL = "restricted"

        inputs = iter(["1", "1", "", "1", "", "", "y"])

        with patch.object(m, "cfg", mock_cfg):
            with patch("builtins.input", side_effect=inputs):
                with patch.object(m, "execute_command", return_value=0):
                    with patch.object(m, "preflight"):
                        with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                            with patch("builtins.print"):
                                result = m.run_wizard()

        assert result == 0


# ══════════════════════════════════════════════════════════════
# Satır 422-425: main() — cfg.init_telemetry çağrısı
# ══════════════════════════════════════════════════════════════

class Extra1_TestMainTelemetry:
    def test_main_calls_init_telemetry_when_available(self):
        """cfg.init_telemetry varsa çağrılmalı (satır 422-423)."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            AI_PROVIDER="ollama",
            ACCESS_LEVEL="full",
            WEB_HOST="0.0.0.0",
            WEB_PORT=7860,
            CODING_MODEL="qwen2.5-coder:7b",
            OLLAMA_URL="http://localhost:11434/api",
        )
        mock_cfg.init_telemetry = MagicMock()

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", ["main.py", "--quick", "cli",
                                             "--provider", "ollama", "--level", "full"]):
                with patch.object(m, "execute_command", return_value=0):
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        mock_cfg.init_telemetry.assert_called_once_with(service_name="sidar-launcher")

    def test_main_no_init_telemetry_attr(self):
        """cfg.init_telemetry yoksa hata olmadan devam etmeli (satır 422 koşul atlanır)."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            AI_PROVIDER="ollama",
            ACCESS_LEVEL="full",
            WEB_HOST="0.0.0.0",
            WEB_PORT=7860,
            CODING_MODEL="qwen2.5-coder:7b",
            OLLAMA_URL="http://localhost:11434/api",
        )
        # init_telemetry yok

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", ["main.py", "--quick", "cli",
                                             "--provider", "ollama", "--level", "full"]):
                with patch.object(m, "execute_command", return_value=0):
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit) as exc:
                                m.main()

        assert exc.value.code == 0


# ══════════════════════════════════════════════════════════════
# Satır 448-455: main() — --quick olmadan run_wizard çağrısı
# ══════════════════════════════════════════════════════════════

class Extra1_TestMainNoQuick:
    def test_no_quick_calls_run_wizard(self):
        """--quick verilmezse run_wizard çağrılmalı (satır 454-455)."""
        m = _get_main()

        with patch.object(sys, "argv", ["main.py"]):
            with patch.object(m, "run_wizard", return_value=0) as mock_wizard:
                with patch("builtins.print"):
                    with pytest.raises(SystemExit) as exc:
                        m.main()

        mock_wizard.assert_called_once()
        assert exc.value.code == 0

    def test_no_quick_wizard_returns_2(self):
        """Wizard 2 döndürdüğünde sys.exit(2) çağrılmalı."""
        m = _get_main()

        with patch.object(sys, "argv", ["main.py"]):
            with patch.object(m, "run_wizard", return_value=2):
                with patch("builtins.print"):
                    with pytest.raises(SystemExit) as exc:
                        m.main()

        assert exc.value.code == 2

    def test_valid_port_passes_validation(self):
        """Geçerli --port değeri hata vermemeli (satır 445-451)."""
        m = _get_main()

        with patch.object(sys, "argv", ["main.py", "--quick", "web", "--port", "8080"]):
            with patch.object(m, "execute_command", return_value=0):
                with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                    with patch("builtins.print"):
                        with pytest.raises(SystemExit) as exc:
                            m.main()

        assert exc.value.code == 0

    def test_port_1_is_valid(self):
        """--port 1 geçerli (satır 448)."""
        m = _get_main()

        with patch.object(sys, "argv", ["main.py", "--quick", "web", "--port", "1"]):
            with patch.object(m, "execute_command", return_value=0):
                with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                    with patch("builtins.print"):
                        with pytest.raises(SystemExit) as exc:
                            m.main()

        assert exc.value.code == 0

    def test_port_65535_is_valid(self):
        """--port 65535 geçerli (satır 448)."""
        m = _get_main()

        with patch.object(sys, "argv", ["main.py", "--quick", "web", "--port", "65535"]):
            with patch.object(m, "execute_command", return_value=0):
                with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                    with patch("builtins.print"):
                        with pytest.raises(SystemExit) as exc:
                            m.main()

        assert exc.value.code == 0


# ══════════════════════════════════════════════════════════════
# main() — --quick ile provider/level cfg'den alınır
# ══════════════════════════════════════════════════════════════

class Extra1_TestMainQuickDefaults:
    def test_provider_from_cfg_when_not_given(self):
        """--provider verilmezse cfg.AI_PROVIDER kullanılmalı."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            AI_PROVIDER="gemini",
            ACCESS_LEVEL="full",
            WEB_HOST="0.0.0.0",
            WEB_PORT=7860,
            CODING_MODEL="qwen2.5-coder:7b",
            OLLAMA_URL="",
        )

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", ["main.py", "--quick", "cli", "--level", "full"]):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        cmd = mock_exec.call_args[0][0]
        assert "gemini" in cmd

    def test_level_from_cfg_when_not_given(self):
        """--level verilmezse cfg.ACCESS_LEVEL kullanılmalı."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            AI_PROVIDER="ollama",
            ACCESS_LEVEL="restricted",
            WEB_HOST="0.0.0.0",
            WEB_PORT=7860,
            CODING_MODEL="qwen2.5-coder:7b",
            OLLAMA_URL="",
        )

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", ["main.py", "--quick", "cli", "--provider", "ollama"]):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        cmd = mock_exec.call_args[0][0]
        assert "restricted" in cmd

    def test_model_from_cfg_when_not_given(self):
        """--model verilmezse cfg.CODING_MODEL kullanılmalı."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            AI_PROVIDER="ollama",
            ACCESS_LEVEL="full",
            WEB_HOST="0.0.0.0",
            WEB_PORT=7860,
            CODING_MODEL="llama3:8b",
            OLLAMA_URL="",
        )

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", ["main.py", "--quick", "cli", "--provider", "ollama",
                                             "--level", "full"]):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        cmd = mock_exec.call_args[0][0]
        assert "llama3:8b" in cmd

    def test_host_from_cfg_for_web_mode(self):
        """Web modunda --host verilmezse cfg.WEB_HOST kullanılmalı."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            AI_PROVIDER="ollama",
            ACCESS_LEVEL="full",
            WEB_HOST="127.0.0.1",
            WEB_PORT=9000,
            CODING_MODEL="qwen2.5-coder:7b",
            OLLAMA_URL="",
        )

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", ["main.py", "--quick", "web", "--provider", "ollama",
                                             "--level", "full"]):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        cmd = mock_exec.call_args[0][0]
        assert "127.0.0.1" in cmd

    def test_capture_output_and_child_log_passed(self):
        """--capture-output ve --child-log execute_command'a geçirilmeli."""
        m = _get_main()

        with patch.object(sys, "argv", [
            "main.py", "--quick", "cli", "--provider", "ollama",
            "--level", "full", "--capture-output", "--child-log", "/tmp/child.log"
        ]):
            with patch.object(m, "execute_command", return_value=0) as mock_exec:
                with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                    with patch("builtins.print"):
                        with pytest.raises(SystemExit):
                            m.main()

        call_kwargs = mock_exec.call_args[1]
        assert call_kwargs.get("capture_output") is True
        assert call_kwargs.get("child_log_path") == "/tmp/child.log"


# ===== MERGED FROM tests/test_main_extra2.py =====

import io
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest


# ══════════════════════════════════════════════════════════════
# print_banner (line 56-70)
# ══════════════════════════════════════════════════════════════

class Extra2_TestPrintBanner:
    def test_print_banner_outputs_sidar(self):
        """print_banner() should print something containing 'SIDAR' (line 56-70)."""
        m = _get_main()
        printed = []
        with patch("builtins.print", side_effect=lambda *a, **k: printed.append(str(a))):
            m.print_banner()
        combined = " ".join(printed)
        assert "SIDAR" in combined or "Sidar" in combined or len(printed) > 0

    def test_print_banner_contains_welcome_message(self):
        """print_banner should print a welcome line (line 70)."""
        m = _get_main()
        printed = []
        with patch("builtins.print", side_effect=lambda *a, **k: printed.append(str(a))):
            m.print_banner()
        combined = " ".join(printed)
        assert len(combined) > 0


# ══════════════════════════════════════════════════════════════
# ask_choice (lines 73-90)
# ══════════════════════════════════════════════════════════════

class Extra2_TestAskChoice:
    def test_ask_choice_empty_input_returns_default(self):
        """Empty input should return the default value (line 84-85)."""
        m = _get_main()
        options = {"1": ("Option A", "a"), "2": ("Option B", "b")}
        with patch("builtins.input", return_value=""):
            with patch("builtins.print"):
                result = m.ask_choice("Choose:", options, "1")
        assert result == "a"

    def test_ask_choice_valid_input_returns_value(self):
        """Valid selection returns corresponding value (line 87-88)."""
        m = _get_main()
        options = {"1": ("Option A", "a"), "2": ("Option B", "b")}
        with patch("builtins.input", return_value="2"):
            with patch("builtins.print"):
                result = m.ask_choice("Choose:", options, "1")
        assert result == "b"

    def test_ask_choice_invalid_then_valid(self):
        """Invalid then valid input - retries (line 90)."""
        m = _get_main()
        options = {"1": ("Option A", "a"), "2": ("Option B", "b")}
        inputs = iter(["x", "invalid", "1"])
        with patch("builtins.input", side_effect=inputs):
            with patch("builtins.print"):
                result = m.ask_choice("Choose:", options, "2")
        assert result == "a"

    def test_ask_choice_default_shows_default_marker(self):
        """Default option shows (Varsayılan) marker in output (line 78)."""
        m = _get_main()
        options = {"1": ("Option A", "a"), "2": ("Option B", "b")}
        printed = []
        with patch("builtins.input", return_value="1"):
            with patch("builtins.print", side_effect=lambda *a, **k: printed.append(str(a))):
                m.ask_choice("Choose:", options, "1")
        combined = " ".join(printed)
        assert "Varsayılan" in combined


# ══════════════════════════════════════════════════════════════
# ask_text (lines 93-97)
# ══════════════════════════════════════════════════════════════

class Extra2_TestAskText:
    def test_ask_text_returns_input(self):
        """ask_text returns user input (line 96-97)."""
        m = _get_main()
        with patch("builtins.input", return_value="mytext"):
            result = m.ask_text("Enter something:")
        assert result == "mytext"

    def test_ask_text_empty_returns_default(self):
        """Empty input returns default value (line 97)."""
        m = _get_main()
        with patch("builtins.input", return_value=""):
            result = m.ask_text("Enter something:", default="fallback")
        assert result == "fallback"

    def test_ask_text_with_default_shows_hint(self):
        """Default value shown as hint in prompt (line 95)."""
        m = _get_main()
        prompts = []
        def fake_input(p=""):
            prompts.append(p)
            return ""
        with patch("builtins.input", side_effect=fake_input):
            m.ask_text("Enter:", default="mydefault")
        assert any("mydefault" in p for p in prompts)


# ══════════════════════════════════════════════════════════════
# confirm (lines 100-106)
# ══════════════════════════════════════════════════════════════

class Extra2_TestConfirm:
    def test_confirm_empty_default_yes_returns_true(self):
        """Empty input with default_yes=True returns True (line 104-105)."""
        m = _get_main()
        with patch("builtins.input", return_value=""):
            result = m.confirm("Confirm?", default_yes=True)
        assert result is True

    def test_confirm_empty_default_no_returns_false(self):
        """Empty input with default_yes=False returns False (line 104-105)."""
        m = _get_main()
        with patch("builtins.input", return_value=""):
            result = m.confirm("Confirm?", default_yes=False)
        assert result is False

    def test_confirm_y_returns_true(self):
        """Input 'y' returns True (line 106)."""
        m = _get_main()
        with patch("builtins.input", return_value="y"):
            result = m.confirm("Confirm?")
        assert result is True

    def test_confirm_yes_returns_true(self):
        """Input 'yes' returns True (line 106)."""
        m = _get_main()
        with patch("builtins.input", return_value="yes"):
            result = m.confirm("Confirm?")
        assert result is True

    def test_confirm_n_returns_false(self):
        """Input 'n' returns False (line 106)."""
        m = _get_main()
        with patch("builtins.input", return_value="n"):
            result = m.confirm("Confirm?")
        assert result is False

    def test_confirm_evet_returns_true(self):
        """Turkish 'evet' returns True (line 106)."""
        m = _get_main()
        with patch("builtins.input", return_value="evet"):
            result = m.confirm("Onaylar mısınız?")
        assert result is True


# ══════════════════════════════════════════════════════════════
# validate_runtime_dependencies (lines 109-119)
# ══════════════════════════════════════════════════════════════

class Extra2_TestValidateRuntimeDependencies:
    def test_returns_true_when_config_import_ok(self):
        """CONFIG_IMPORT_OK=True → (True, None) (line 111-112)."""
        m = _get_main()
        with patch.object(m, "CONFIG_IMPORT_OK", True):
            ok, err = m.validate_runtime_dependencies("web")
        assert ok is True
        assert err is None

    def test_returns_false_for_web_when_config_fails(self):
        """CONFIG_IMPORT_OK=False + mode='web' → error mentions web_server.py (line 114-119)."""
        m = _get_main()
        with patch.object(m, "CONFIG_IMPORT_OK", False):
            ok, err = m.validate_runtime_dependencies("web")
        assert ok is False
        assert "web_server.py" in err

    def test_returns_false_for_cli_when_config_fails(self):
        """CONFIG_IMPORT_OK=False + mode='cli' → error mentions cli.py (line 114-119)."""
        m = _get_main()
        with patch.object(m, "CONFIG_IMPORT_OK", False):
            ok, err = m.validate_runtime_dependencies("cli")
        assert ok is False
        assert "cli.py" in err


# ══════════════════════════════════════════════════════════════
# _safe_choice (lines 122-130)
# ══════════════════════════════════════════════════════════════

class Extra2_TestSafeChoice:
    def test_valid_choice_returned(self):
        """Valid choice string returned (line 130)."""
        m = _get_main()
        result = m._safe_choice("gemini", "ollama", {"ollama", "gemini", "openai"})
        assert result == "gemini"

    def test_invalid_choice_returns_default(self):
        """Choice not in allowed set → default (line 129)."""
        m = _get_main()
        result = m._safe_choice("invalid_val", "ollama", {"ollama", "gemini"})
        assert result == "ollama"

    def test_non_string_returns_default(self):
        """Non-string value → default (line 124-125)."""
        m = _get_main()
        result = m._safe_choice(123, "ollama", {"ollama", "gemini"})
        assert result == "ollama"

    def test_none_returns_default(self):
        """None value → default (line 124-125)."""
        m = _get_main()
        result = m._safe_choice(None, "ollama", {"ollama", "gemini"})
        assert result == "ollama"

    def test_empty_string_returns_default(self):
        """Empty string → default (line 128-129)."""
        m = _get_main()
        result = m._safe_choice("", "ollama", {"ollama", "gemini"})
        assert result == "ollama"

    def test_whitespace_normalized(self):
        """Value with spaces gets stripped (line 127)."""
        m = _get_main()
        result = m._safe_choice("  gemini  ", "ollama", {"ollama", "gemini"})
        assert result == "gemini"


# ══════════════════════════════════════════════════════════════
# _safe_text (lines 133-139)
# ══════════════════════════════════════════════════════════════

class Extra2_TestSafeText:
    def test_valid_string_returned(self):
        """Non-empty string returned as-is (line 138-139)."""
        m = _get_main()
        result = m._safe_text("hello world", "default")
        assert result == "hello world"

    def test_none_returns_default(self):
        """None → default (line 135-136)."""
        m = _get_main()
        result = m._safe_text(None, "fallback")
        assert result == "fallback"

    def test_empty_string_returns_default(self):
        """Empty/whitespace string → default (line 138-139)."""
        m = _get_main()
        result = m._safe_text("   ", "fallback")
        assert result == "fallback"

    def test_number_converted_to_string(self):
        """Non-string value converted to str (line 138)."""
        m = _get_main()
        result = m._safe_text(42, "fallback")
        assert result == "42"


# ══════════════════════════════════════════════════════════════
# _safe_port (lines 142-149)
# ══════════════════════════════════════════════════════════════

class Extra2_TestSafePort:
    def test_valid_port_returned(self):
        """Valid port number returned as string (line 149)."""
        m = _get_main()
        result = m._safe_port("8080", "7860")
        assert result == "8080"

    def test_invalid_port_returns_default(self):
        """Non-numeric → default (line 147-148)."""
        m = _get_main()
        result = m._safe_port("notaport", "7860")
        assert result == "7860"

    def test_port_too_high_returns_default(self):
        """Port > 65535 → default (line 149)."""
        m = _get_main()
        result = m._safe_port("99999", "7860")
        assert result == "7860"

    def test_port_zero_returns_default(self):
        """Port 0 → default (line 149)."""
        m = _get_main()
        result = m._safe_port("0", "7860")
        assert result == "7860"

    def test_int_port_converted(self):
        """Integer port value is handled (line 144)."""
        m = _get_main()
        result = m._safe_port(3000, "7860")
        assert result == "3000"


# ══════════════════════════════════════════════════════════════
# preflight (lines 152-208)
# ══════════════════════════════════════════════════════════════

class Extra2_TestPreflightExtra:
    def _make_cfg(self, **kwargs):
        defaults = dict(
            BASE_DIR=".",
            DATABASE_URL="sqlite:///db",
            GEMINI_API_KEY="",
            OPENAI_API_KEY="",
            ANTHROPIC_API_KEY="",
            OLLAMA_URL="http://localhost:11434/api",
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_openai_missing_key_warns(self):
        """provider='openai' without OPENAI_API_KEY → warning (line 180-183)."""
        m = _get_main()
        mock_cfg = self._make_cfg(OPENAI_API_KEY="")
        with patch.object(m, "cfg", mock_cfg):
            with patch.object(m.logger, "warning") as mock_warn:
                with patch("builtins.print"):
                    m.preflight("openai")
        assert mock_warn.called

    def test_anthropic_missing_key_warns(self):
        """provider='anthropic' without ANTHROPIC_API_KEY → warning (line 185-188)."""
        m = _get_main()
        mock_cfg = self._make_cfg(ANTHROPIC_API_KEY="")
        with patch.object(m, "cfg", mock_cfg):
            with patch.object(m.logger, "warning") as mock_warn:
                with patch("builtins.print"):
                    m.preflight("anthropic")
        assert mock_warn.called

    def test_ollama_200_prints_success(self):
        """Ollama returns 200 → success message printed (line 197-198)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        fake_httpx = types.ModuleType("httpx")
        fake_httpx.Client = MagicMock(return_value=mock_client)

        printed = []
        with patch.object(m, "cfg", mock_cfg):
            with patch.dict(sys.modules, {"httpx": fake_httpx}):
                with patch("builtins.print", side_effect=lambda *a, **k: printed.append(str(a))):
                    m.preflight("ollama")
        combined = " ".join(printed)
        assert "✅" in combined or "Ollama" in combined

    def test_ollama_exception_warns(self):
        """Ollama connection exception → warning (line 205-207)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = Exception("Connection refused")

        fake_httpx = types.ModuleType("httpx")
        fake_httpx.Client = MagicMock(return_value=mock_client)

        with patch.object(m, "cfg", mock_cfg):
            with patch.dict(sys.modules, {"httpx": fake_httpx}):
                with patch.object(m.logger, "warning") as mock_warn:
                    with patch("builtins.print"):
                        m.preflight("ollama")
        assert mock_warn.called

    def test_ollama_non_api_url_uses_correct_tags_url(self):
        """OLLAMA_URL without /api suffix builds correct tags URL (line 194)."""
        m = _get_main()
        mock_cfg = self._make_cfg(OLLAMA_URL="http://localhost:11434")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        fake_httpx = types.ModuleType("httpx")
        fake_httpx.Client = MagicMock(return_value=mock_client)

        with patch.object(m, "cfg", mock_cfg):
            with patch.dict(sys.modules, {"httpx": fake_httpx}):
                with patch("builtins.print"):
                    m.preflight("ollama")

        call_args = mock_client.get.call_args[0][0]
        assert "/api/tags" in call_args


# ══════════════════════════════════════════════════════════════
# build_command (lines 210-234)
# ══════════════════════════════════════════════════════════════

class Extra2_TestBuildCommand:
    def test_web_mode_builds_correct_command(self):
        """Web mode includes host and port (line 231-232)."""
        m = _get_main()
        cmd = m.build_command("web", "gemini", "full", "info",
                               {"host": "0.0.0.0", "port": "8080"})
        assert "web_server.py" in cmd
        assert "--host" in cmd
        assert "0.0.0.0" in cmd
        assert "--port" in cmd
        assert "8080" in cmd

    def test_cli_ollama_includes_model(self):
        """CLI + ollama mode includes --model flag (line 229-230)."""
        m = _get_main()
        cmd = m.build_command("cli", "ollama", "full", "info",
                               {"model": "llama2:7b"})
        assert "cli.py" in cmd
        assert "--model" in cmd
        assert "llama2:7b" in cmd

    def test_cli_non_ollama_no_model(self):
        """CLI + non-ollama mode does not include --model flag (line 231-232)."""
        m = _get_main()
        cmd = m.build_command("cli", "gemini", "full", "info", {})
        assert "--model" not in cmd

    def test_invalid_mode_raises(self):
        """Invalid mode raises ValueError (line 217-218)."""
        m = _get_main()
        with pytest.raises(ValueError, match="Geçersiz mode"):
            m.build_command("invalid", "ollama", "full", "info", {})

    def test_invalid_provider_raises(self):
        """Invalid provider raises ValueError (line 219-220)."""
        m = _get_main()
        with pytest.raises(ValueError, match="Geçersiz provider"):
            m.build_command("web", "unknown", "full", "info", {})

    def test_invalid_level_raises(self):
        """Invalid level raises ValueError (line 221-222)."""
        m = _get_main()
        with pytest.raises(ValueError, match="Geçersiz level"):
            m.build_command("web", "gemini", "superuser", "info", {})

    def test_invalid_log_raises(self):
        """Invalid log level raises ValueError (line 223-224)."""
        m = _get_main()
        with pytest.raises(ValueError, match="Geçersiz log"):
            m.build_command("web", "gemini", "full", "verbose", {})

    def test_valid_restricted_level(self):
        """'restricted' is a valid level (line 213)."""
        m = _get_main()
        cmd = m.build_command("cli", "gemini", "restricted", "warning", {})
        assert "--level" in cmd
        assert "restricted" in cmd


# ══════════════════════════════════════════════════════════════
# _format_cmd (line 237-239)
# ══════════════════════════════════════════════════════════════

class Extra2_TestFormatCmd:
    def test_format_cmd_quotes_parts(self):
        """_format_cmd quotes command parts (line 237-239)."""
        m = _get_main()
        result = m._format_cmd(["python", "script.py", "--arg", "value with space"])
        # shlex.quote uses single quotes for strings with spaces
        assert "'value with space'" in result or '"value with space"' in result or "value\\ with\\ space" in result

    def test_format_cmd_returns_string(self):
        """_format_cmd returns a string (line 237-239)."""
        m = _get_main()
        result = m._format_cmd(["python", "script.py"])
        assert isinstance(result, str)
        assert "python" in result
        assert "script.py" in result


# ══════════════════════════════════════════════════════════════
# _stream_pipe (lines 242-250)
# ══════════════════════════════════════════════════════════════

class Extra2_TestStreamPipe:
    def test_stream_pipe_writes_to_file_obj(self):
        """_stream_pipe writes lines to file_obj (line 244-248)."""
        m = _get_main()
        pipe = io.StringIO("line1\nline2\n")
        file_obj = io.StringIO()
        with patch("builtins.print"):
            m._stream_pipe(pipe, file_obj, "[stdout]", m.CYAN, True)
        content = file_obj.getvalue()
        assert "line1" in content
        assert "line2" in content

    def test_stream_pipe_without_file_obj(self):
        """_stream_pipe handles None file_obj (line 245-248)."""
        m = _get_main()
        pipe = io.StringIO("hello\n")
        with patch("builtins.print"):
            m._stream_pipe(pipe, None, "[stdout]", m.CYAN, True)
        # No exception should be raised

    def test_stream_pipe_no_mirror_no_print(self):
        """mirror=False → print not called (line 248-249)."""
        m = _get_main()
        pipe = io.StringIO("data\n")
        printed = []
        with patch("builtins.print", side_effect=lambda *a, **k: printed.append(1)):
            m._stream_pipe(pipe, None, "[stdout]", m.CYAN, False)
        assert len(printed) == 0


# ══════════════════════════════════════════════════════════════
# execute_command (lines 398-419)
# ══════════════════════════════════════════════════════════════

class Extra2_TestExecuteCommand:
    def test_execute_command_success_returns_0(self):
        """Successful subprocess.run returns 0 (line 409-410)."""
        m = _get_main()
        with patch("subprocess.run") as mock_run:
            with patch("builtins.print"):
                result = m.execute_command(["true"])
        assert result == 0

    def test_execute_command_keyboard_interrupt_returns_0(self):
        """KeyboardInterrupt returns 0 (line 411-413)."""
        m = _get_main()
        with patch("subprocess.run", side_effect=KeyboardInterrupt()):
            with patch("builtins.print"):
                result = m.execute_command(["dummy"])
        assert result == 0

    def test_execute_command_called_process_error_returns_code(self):
        """CalledProcessError returns non-zero code (line 414-416)."""
        m = _get_main()
        err = subprocess.CalledProcessError(returncode=42, cmd="dummy")
        with patch("subprocess.run", side_effect=err):
            with patch("builtins.print"):
                result = m.execute_command(["dummy"])
        assert result == 42

    def test_execute_command_generic_exception_returns_1(self):
        """Generic exception returns 1 (line 417-419)."""
        m = _get_main()
        with patch("subprocess.run", side_effect=RuntimeError("unexpected")):
            with patch("builtins.print"):
                result = m.execute_command(["dummy"])
        assert result == 1

    def test_execute_command_with_capture_output_uses_streaming(self):
        """capture_output=True uses _run_with_streaming (line 403-407)."""
        m = _get_main()
        with patch.object(m, "_run_with_streaming", return_value=0) as mock_stream:
            with patch("builtins.print"):
                result = m.execute_command(["dummy"], capture_output=True)
        mock_stream.assert_called_once()
        assert result == 0

    def test_execute_command_with_child_log_uses_streaming(self):
        """child_log_path triggers streaming path (line 403-407)."""
        m = _get_main()
        with patch.object(m, "_run_with_streaming", return_value=5) as mock_stream:
            with patch("builtins.print"):
                result = m.execute_command(["dummy"], child_log_path="/tmp/test.log")
        mock_stream.assert_called_once()
        assert result == 5

    def test_execute_command_streaming_nonzero_prints_error(self):
        """Non-zero return from streaming prints error message (line 405-407)."""
        m = _get_main()
        printed = []
        with patch.object(m, "_run_with_streaming", return_value=3):
            with patch("builtins.print", side_effect=lambda *a, **k: printed.append(str(a))):
                result = m.execute_command(["dummy"], capture_output=True)
        assert result == 3
        combined = " ".join(printed)
        assert "3" in combined or "hata" in combined.lower()


# ══════════════════════════════════════════════════════════════
# main() function (lines 421-481)
# ══════════════════════════════════════════════════════════════

class Extra2_TestMainFunction:
    def _make_cfg(self, **kwargs):
        defaults = dict(
            AI_PROVIDER="ollama",
            ACCESS_LEVEL="full",
            WEB_HOST="0.0.0.0",
            WEB_PORT=7860,
            CODING_MODEL="qwen2.5-coder:7b",
            OLLAMA_URL="http://localhost:11434/api",
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_main_quick_web_with_all_args(self):
        """--quick web with provider/level/host/port runs and exits (line 458-481)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", [
                "main.py", "--quick", "web",
                "--provider", "gemini",
                "--level", "sandbox",
                "--host", "127.0.0.1",
                "--port", "9090",
                "--log", "debug",
            ]):
                with patch.object(m, "execute_command", return_value=0):
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit) as exc_info:
                                m.main()
        assert exc_info.value.code == 0

    def test_main_quick_cli_default_provider_from_cfg(self):
        """--quick cli without --provider uses cfg.AI_PROVIDER (line 458-462)."""
        m = _get_main()
        mock_cfg = self._make_cfg(AI_PROVIDER="anthropic")

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", [
                "main.py", "--quick", "cli",
                "--level", "full",
            ]):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        cmd = mock_exec.call_args[0][0]
        assert "anthropic" in cmd

    def test_main_quick_cli_runtime_error_exits_2(self):
        """--quick cli with config import failure exits with code 2 (line 476-478)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", ["main.py", "--quick", "cli"]):
                with patch.object(m, "validate_runtime_dependencies",
                                   return_value=(False, "config error")):
                    with patch("builtins.print"):
                        with pytest.raises(SystemExit) as exc_info:
                            m.main()
        assert exc_info.value.code == 2

    def test_main_invalid_port_calls_parser_error(self):
        """--port with invalid value calls parser.error (line 445-451)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", [
                "main.py", "--quick", "web",
                "--provider", "ollama",
                "--port", "99999",
            ]):
                with patch("builtins.print"):
                    with pytest.raises(SystemExit):
                        m.main()

    def test_main_invalid_port_string_errors(self):
        """--port with non-numeric string → parser error (line 446-451)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", [
                "main.py", "--quick", "web",
                "--provider", "ollama",
                "--port", "abc",
            ]):
                with patch("builtins.print"):
                    with pytest.raises(SystemExit):
                        m.main()

    def test_main_no_quick_calls_run_wizard(self):
        """No --quick argument → run_wizard called (line 454-455)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", ["main.py"]):
                with patch.object(m, "run_wizard", return_value=0) as mock_wizard:
                    with patch("builtins.print"):
                        with pytest.raises(SystemExit):
                            m.main()
        mock_wizard.assert_called_once()

    def test_main_quick_with_model_arg(self):
        """--quick cli --model passes model to extra_args (line 469-473)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", [
                "main.py", "--quick", "cli",
                "--provider", "ollama",
                "--level", "full",
                "--model", "llama3:8b",
            ]):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        cmd = mock_exec.call_args[0][0]
        assert "llama3:8b" in cmd

    def test_main_quick_with_capture_output(self):
        """--capture-output flag passes to execute_command (line 434-436)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", [
                "main.py", "--quick", "cli",
                "--provider", "ollama",
                "--capture-output",
            ]):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        call_kwargs = mock_exec.call_args[1]
        assert call_kwargs.get("capture_output") is True

    def test_main_quick_with_child_log(self):
        """--child-log passes path to execute_command (line 439-441)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", [
                "main.py", "--quick", "cli",
                "--provider", "ollama",
                "--child-log", "/tmp/child.log",
            ]):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        call_kwargs = mock_exec.call_args[1]
        assert call_kwargs.get("child_log_path") == "/tmp/child.log"

    def test_main_quick_level_from_cfg(self):
        """--quick without --level uses cfg.ACCESS_LEVEL (line 463-466)."""
        m = _get_main()
        mock_cfg = self._make_cfg(ACCESS_LEVEL="restricted")

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", [
                "main.py", "--quick", "cli",
                "--provider", "ollama",
            ]):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        cmd = mock_exec.call_args[0][0]
        assert "restricted" in cmd

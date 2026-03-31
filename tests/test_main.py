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
        with patch("builtins.print"):
            result = m.execute_command(cmd)
        assert result == 0

    def test_failed_run_returns_nonzero(self):
        m = _get_main()
        cmd = [sys.executable, "-c", "import sys; sys.exit(3)"]
        with patch("builtins.print"):
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

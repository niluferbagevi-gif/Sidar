"""
Kapsamlı boşluk testi: managers/code_manager.py için %100 kapsama hedefi.

Hedef satır/dal'lar:
  47, 53, 70, 75, 144, 146, 149-150, 166->174,
  273-275, 279, 282, 290,
  395->397 (unreachable; _strip_markdown_code_fences basitleştirilerek giderildi),
  397->399, 510->512, 514, 544-545, 668, 691, 704,
  1168, 1175-1179, 1283-1284, 1392->1388, 1595-1596, 1617, 1633->1637
"""
import os
import stat
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_code_manager_runtime import CM_MOD, DummySecurity, FULL

# Gerçek _init_docker referansını modül yüklenirken saklıyoruz.
# Başka test dosyaları (örn. test_code_manager_final_gap_push.py) doğrudan
# CM_MOD.CodeManager._init_docker'ı monkeypatch olmadan değiştirdiğinden,
# bu referans olmadan `original_init` sahte lambda'yı alırdı.
_REAL_INIT_DOCKER = CM_MOD.CodeManager._init_docker


# ─────────────────────────────────────────────
# Yardımcı: init_docker'ı devre dışı bırakan manager oluşturucu
# ─────────────────────────────────────────────

class DummySecurityWithPathCheck(DummySecurity):
    """is_path_under desteğiyle genişletilmiş güvenlik taklidi."""

    def is_path_under(self, path_str: str, base: Path) -> bool:
        try:
            Path(path_str).resolve().relative_to(base.resolve())
            return True
        except ValueError:
            return False


def _make_mgr(monkeypatch, tmp_path, **sec_kwargs):
    monkeypatch.setattr(CM_MOD.CodeManager, "_init_docker", lambda self: None)
    sec = DummySecurityWithPathCheck(tmp_path, level=FULL, **sec_kwargs)
    mgr = CM_MOD.CodeManager(sec, tmp_path)
    mgr.docker_available = False
    mgr.docker_client = None
    return mgr


# ═══════════════════════════════════════════════
# 1. _file_uri_to_path  —  satır 47, 53
# ═══════════════════════════════════════════════

def test_file_uri_to_path_raises_for_non_file_scheme():
    """Satır 47: 'file' dışı URI şeması ValueError fırlatmalı."""
    with pytest.raises(ValueError, match="Desteklenmeyen URI şeması"):
        CM_MOD._file_uri_to_path("http://example.com/foo.py")


# ═══════════════════════════════════════════════
# 2. _decode_lsp_stream  —  satır 70, 75
# ═══════════════════════════════════════════════

def test_decode_lsp_stream_no_header_end_returns_empty():
    """Satır 70: \\r\\n\\r\\n bulunamadığında döngü break'e düşmeli → boş liste."""
    result = CM_MOD._decode_lsp_stream(b"Content-Length: 5\r\nincomplete")
    assert result == []


def test_decode_lsp_stream_header_line_without_colon_is_skipped():
    """Satır 75: ':' içermeyen başlık satırı atlanmalı, mesaj yine de ayrıştırılmalı."""
    body = b'{"id": 1}'
    header = b"Content-Length: 9\r\nX-No-Colon\r\n\r\n"
    data = header + body
    result = CM_MOD._decode_lsp_stream(data)
    assert result == [{"id": 1}]


# ═══════════════════════════════════════════════
# 3. _resolve_runtime  —  satır 144, 146, 149-150
# ═══════════════════════════════════════════════

def test_resolve_runtime_gvisor_mode_sets_runsc():
    """Satır 144: docker_microvm_mode='gvisor' iken runtime='runsc' seçilmeli."""
    mgr = object.__new__(CM_MOD.CodeManager)
    mgr.docker_microvm_mode = "gvisor"
    mgr.docker_runtime = ""
    mgr.docker_allowed_runtimes = ["", "runsc"]
    assert mgr._resolve_runtime() == "runsc"


def test_resolve_runtime_kata_mode_sets_kata_runtime():
    """Satır 146: docker_microvm_mode='kata' iken runtime='kata-runtime' seçilmeli."""
    mgr = object.__new__(CM_MOD.CodeManager)
    mgr.docker_microvm_mode = "kata"
    mgr.docker_runtime = ""
    mgr.docker_allowed_runtimes = ["", "kata-runtime"]
    assert mgr._resolve_runtime() == "kata-runtime"


def test_resolve_runtime_not_in_allowed_list_returns_empty():
    """Satır 149-150: runtime izinli listede yoksa uyarı verip '' döndürmeli."""
    mgr = object.__new__(CM_MOD.CodeManager)
    mgr.docker_microvm_mode = "off"
    mgr.docker_runtime = "custom-runtime"
    mgr.docker_allowed_runtimes = ["", "runc"]
    result = mgr._resolve_runtime()
    assert result == ""


# ═══════════════════════════════════════════════
# 4. _resolve_sandbox_limits  —  dal 166->174
# ═══════════════════════════════════════════════

def test_resolve_sandbox_limits_whitespace_cpus_skips_float_branch():
    """Dal 166->174: cpus sadece boşluk ise strip() sonrası '' → if cpus: False, nano_cpus değişmez."""
    mgr = object.__new__(CM_MOD.CodeManager)
    mgr.cfg = SimpleNamespace(SANDBOX_LIMITS={"cpus": "   ", "pids_limit": 8, "timeout": 5})
    mgr.docker_mem_limit = "256m"
    mgr.docker_exec_timeout = 10
    mgr.docker_nano_cpus = 777_000_000
    limits = mgr._resolve_sandbox_limits()
    # cpus boşluk → strip ile "" → if cpus: False → nano_cpus hiç güncellenmez
    assert limits["nano_cpus"] == 777_000_000


# ═══════════════════════════════════════════════
# 5. _init_docker  —  satır 273-275, 279, 282, 290
# ═══════════════════════════════════════════════

def test_init_docker_success_docker_sdk(monkeypatch, tmp_path):
    """Satır 273-275: docker SDK başarıyla import edildiğinde docker_available=True olmalı."""
    sec = DummySecurity(tmp_path)
    monkeypatch.setattr(CM_MOD.CodeManager, "_init_docker", lambda self: None)
    mgr = CM_MOD.CodeManager(sec, tmp_path)

    class _FakeClient:
        def ping(self):
            return True

    class _FakeDocker:
        @staticmethod
        def from_env():
            return _FakeClient()

    # builtins.__import__ yerine sys.modules'u kullanıyoruz (coverage hook'larını bozmamak için)
    monkeypatch.setitem(sys.modules, "docker", _FakeDocker)

    _REAL_INIT_DOCKER(mgr)

    assert mgr.docker_available is True
    assert isinstance(mgr.docker_client, _FakeClient)


def test_init_docker_exception_wsl_fails_cli_succeeds(monkeypatch, tmp_path):
    """Satır 290: Exception dalı + WSL fallback başarısız + CLI fallback başarılı → return.

    docker SDK var (from_env Exception), WSL socket yok (OSError), CLI başarılı (returncode=0).
    """
    sec = DummySecurity(tmp_path)
    monkeypatch.setattr(CM_MOD.CodeManager, "_init_docker", lambda self: None)
    mgr = CM_MOD.CodeManager(sec, tmp_path)

    class _DockerMod:
        @staticmethod
        def from_env():
            raise RuntimeError("daemon down")

        class DockerClient:
            def __init__(self, base_url=None):
                pass

            def ping(self):
                raise RuntimeError("sock down")

    # sys.modules'a mock docker koyuyoruz → import docker başarılı, from_env Exception fırlatır
    monkeypatch.setitem(sys.modules, "docker", _DockerMod)

    # Tüm WSL socket yolları OSError fırlatacak → _try_wsl_socket_fallback False döner
    monkeypatch.setattr(CM_MOD.os, "stat", lambda _p, *a, **k: (_ for _ in ()).throw(OSError("no socket")))

    # CLI fallback başarılı
    monkeypatch.setattr(
        CM_MOD.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="Server Version: 27.0.0\n", stderr=""),
    )

    _REAL_INIT_DOCKER(mgr)

    assert mgr.docker_available is True
    assert mgr.docker_client is None


# ═══════════════════════════════════════════════
# 6. _strip_markdown_code_fences  —  dal 397->399
# ═══════════════════════════════════════════════

def test_strip_markdown_code_fences_no_closing_fence():
    """Dal 397->399: Kapanış ``` olmadığında False dalı izlenmeli."""
    result = CM_MOD.CodeManager._strip_markdown_code_fences("```python\nsome_code")
    assert result == "some_code"


def test_strip_markdown_code_fences_with_closing_fence():
    """Dal 397->398: Kapanış ``` varsa çıkarılmalı."""
    result = CM_MOD.CodeManager._strip_markdown_code_fences("```python\nsome_code\n```")
    assert result == "some_code"


# ═══════════════════════════════════════════════
# 7. execute_code  —  dal 510->512, satır 514, satır 544-545
# ═══════════════════════════════════════════════

def test_execute_code_network_enabled_and_runtime_selected(monkeypatch, tmp_path):
    """Dal 510->512 ve satır 514: network_disabled=False + network_mode!='none' + runtime seçili."""
    mgr = _make_mgr(monkeypatch, tmp_path, can_execute=True)
    mgr.docker_available = True
    mgr.docker_network_disabled = False

    class _Container:
        status = "exited"

        def reload(self):
            pass

        def logs(self, stdout=True, stderr=True):
            return b"output"

        def wait(self, timeout=1):
            return {"StatusCode": 0}

        def remove(self, force=True):
            pass

    class _Containers:
        def run(self, **kwargs):
            # network_mode eklenMEMELİ (False dal)
            assert "network_mode" not in kwargs
            # runtime EKLENECEK (satır 514)
            assert kwargs.get("runtime") == "runsc"
            return _Container()

    mgr.docker_client = SimpleNamespace(containers=_Containers())
    monkeypatch.setitem(
        sys.modules,
        "docker",
        SimpleNamespace(errors=SimpleNamespace(ImageNotFound=RuntimeError)),
    )
    monkeypatch.setattr(
        mgr,
        "_resolve_sandbox_limits",
        lambda: {
            "memory": "256m",
            "nano_cpus": 1_000_000_000,
            "pids_limit": 64,
            "timeout": 5,
            "network_mode": "bridge",  # none değil → 510 False dalı
        },
    )
    monkeypatch.setattr(mgr, "_resolve_runtime", lambda: "runsc")  # boş değil → 514 çalışır

    ok, msg = mgr.execute_code("print('hi')")
    assert ok is True


def test_execute_code_container_wait_raises_sets_exit_code_none(monkeypatch, tmp_path):
    """Satır 544-545: container.wait() exception fırlatırsa exit_code=None olmalı."""
    mgr = _make_mgr(monkeypatch, tmp_path, can_execute=True)
    mgr.docker_available = True
    mgr.docker_network_disabled = True

    class _Container:
        status = "exited"

        def reload(self):
            pass

        def logs(self, stdout=True, stderr=True):
            return b"all good"

        def wait(self, timeout=1):
            raise RuntimeError("wait borked")

        def remove(self, force=True):
            pass

    mgr.docker_client = SimpleNamespace(
        containers=SimpleNamespace(run=lambda **_: _Container())
    )
    monkeypatch.setitem(
        sys.modules,
        "docker",
        SimpleNamespace(errors=SimpleNamespace(ImageNotFound=RuntimeError)),
    )
    monkeypatch.setattr(
        mgr,
        "_resolve_sandbox_limits",
        lambda: {
            "memory": "256m",
            "nano_cpus": 1_000_000_000,
            "pids_limit": 64,
            "timeout": 5,
            "network_mode": "none",
        },
    )
    monkeypatch.setattr(mgr, "_resolve_runtime", lambda: "")

    ok, msg = mgr.execute_code("print('x')")
    # exit_code None → başarı sayılır
    assert ok is True
    assert "all good" in msg


# ═══════════════════════════════════════════════
# 8. run_shell_in_sandbox  —  satır 668, 691, 704
# ═══════════════════════════════════════════════

def test_run_shell_in_sandbox_path_outside_base_dir_rejected(monkeypatch, tmp_path):
    """Satır 668: Çalışma dizini proje kökü dışındaysa reddedilmeli."""
    mgr = _make_mgr(monkeypatch, tmp_path, can_execute=True)
    mgr.docker_available = True

    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)

    ok, msg = mgr.run_shell_in_sandbox("ls", cwd=str(outside))
    assert ok is False
    assert "Sandbox çalışma dizini proje kökü dışında" in msg or "Geçersiz çalışma dizini" in msg


def test_run_shell_in_sandbox_runtime_selected_adds_runtime_flag(monkeypatch, tmp_path):
    """Satır 691: Runtime seçildiğinde docker komutuna --runtime eklenmeli."""
    mgr = _make_mgr(monkeypatch, tmp_path, can_execute=True)
    mgr.docker_available = True

    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(CM_MOD.subprocess, "run", fake_run)
    monkeypatch.setattr(CM_MOD.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(mgr, "_resolve_runtime", lambda: "runsc")
    monkeypatch.setattr(
        mgr,
        "_resolve_sandbox_limits",
        lambda: {
            "memory": "256m",
            "cpus": "0.5",
            "pids_limit": 64,
            "timeout": 5,
            "network_mode": "none",
        },
    )

    ok, msg = mgr.run_shell_in_sandbox("ls")
    assert "--runtime" in captured["args"]
    assert "runsc" in captured["args"]


def test_run_shell_in_sandbox_filenotfounderror_from_subprocess(monkeypatch, tmp_path):
    """Satır 704: subprocess.run FileNotFoundError fırlatırsa uygun mesaj döndürmeli."""
    mgr = _make_mgr(monkeypatch, tmp_path, can_execute=True)
    mgr.docker_available = True

    def fake_run(*_args, **_kwargs):
        raise FileNotFoundError("docker not found")

    monkeypatch.setattr(CM_MOD.subprocess, "run", fake_run)
    monkeypatch.setattr(CM_MOD.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(mgr, "_resolve_runtime", lambda: "")
    monkeypatch.setattr(
        mgr,
        "_resolve_sandbox_limits",
        lambda: {
            "memory": "256m",
            "cpus": "0.5",
            "pids_limit": 64,
            "timeout": 5,
            "network_mode": "none",
        },
    )

    ok, msg = mgr.run_shell_in_sandbox("ls")
    assert ok is False
    assert "Docker CLI bulunamadı" in msg


# ═══════════════════════════════════════════════
# 9. LSP yardımcıları  —  satır 1168, 1175-1179, 1283-1284
# ═══════════════════════════════════════════════

def test_detect_language_id_typescript_extension(monkeypatch, tmp_path):
    """Satır 1168: .ts uzantısı 'typescript' dil kimliği döndürmeli."""
    mgr = _make_mgr(monkeypatch, tmp_path)
    result = mgr._detect_language_id(Path("foo.ts"))
    assert result == "typescript"


def test_resolve_lsp_command_typescript_and_unknown_language(monkeypatch, tmp_path):
    """Satır 1175-1179: TypeScript LSP komutu döndürmeli; bilinmeyen dil ValueError fırlatmalı."""
    mgr = _make_mgr(monkeypatch, tmp_path)
    mgr.typescript_lsp_server = "typescript-language-server"

    cmd = mgr._resolve_lsp_command("typescript")
    assert "typescript-language-server" in cmd[0] or "typescript-language-server" in cmd
    assert "--stdio" in cmd

    with pytest.raises(ValueError, match="LSP desteklenmeyen dil"):
        mgr._resolve_lsp_command("ruby")


def test_start_lsp_process_filenotfound_raises(monkeypatch, tmp_path):
    """Satır 1283-1284: LSP binary bulunamazsa FileNotFoundError fırlatılmalı."""
    mgr = _make_mgr(monkeypatch, tmp_path)
    demo = tmp_path / "demo.py"
    demo.write_text("x = 1\n", encoding="utf-8")

    def fake_popen(args, **kwargs):
        raise FileNotFoundError("no such binary")

    monkeypatch.setattr(CM_MOD.subprocess, "Popen", fake_popen)

    with pytest.raises(FileNotFoundError, match="LSP binary bulunamadı"):
        mgr._run_lsp_sequence(
            primary_path=demo,
            request_method=None,
            extra_open_files=[],
        )


# ═══════════════════════════════════════════════
# 10. _apply_workspace_edit  —  dal 1392->1388
# ═══════════════════════════════════════════════

def test_apply_workspace_edit_doc_change_without_uri_is_skipped(monkeypatch, tmp_path):
    """Dal 1392->1388: textDocument içinde uri yoksa o değişiklik atlanmalı."""
    mgr = _make_mgr(monkeypatch, tmp_path, can_write=True)

    # uri içermeyen bir documentChange + geçerli changes ile boş döner
    edit = {
        "documentChanges": [
            {"textDocument": {}, "edits": [{"range": {}, "newText": "foo"}]},  # uri yok
        ]
    }
    ok, msg = mgr._apply_workspace_edit(edit)
    assert ok is False
    assert "Workspace edit boş döndü" in msg


# ═══════════════════════════════════════════════
# 11. lsp_semantic_audit exception  —  satır 1595-1596
# ═══════════════════════════════════════════════

def test_lsp_semantic_audit_exception_returns_tool_error(monkeypatch, tmp_path):
    """Satır 1595-1596: _run_lsp_sequence exception fırlatırsa tool-error durumu döndürülmeli."""
    src = tmp_path / "demo.py"
    src.write_text("x = 1\n", encoding="utf-8")

    mgr = _make_mgr(monkeypatch, tmp_path)

    monkeypatch.setattr(mgr, "_run_lsp_sequence", lambda **_: (_ for _ in ()).throw(RuntimeError("lsp crashed")))

    ok, result = mgr.lsp_semantic_audit([str(src)])
    assert ok is False
    assert result["status"] == "tool-error"
    assert "lsp crashed" in result["summary"]


# ═══════════════════════════════════════════════
# 12. lsp_workspace_diagnostics no-issues path  —  satır 1617
# ═══════════════════════════════════════════════

def test_lsp_workspace_diagnostics_no_issues_returns_summary(monkeypatch, tmp_path):
    """Satır 1617: issue yoksa özet metni döndürmeli."""
    mgr = _make_mgr(monkeypatch, tmp_path)

    monkeypatch.setattr(
        mgr,
        "lsp_semantic_audit",
        lambda _paths=None: (True, {"issues": [], "summary": "Temiz kod."}),
    )

    ok, msg = mgr.lsp_workspace_diagnostics([])
    assert ok is True
    assert "Temiz kod." in msg


# ═══════════════════════════════════════════════
# 13. audit_project exclude_dirs not None  —  dal 1633->1637
# ═══════════════════════════════════════════════

def test_audit_project_with_custom_exclude_dirs(monkeypatch, tmp_path):
    """Dal 1633->1637: exclude_dirs verildiğinde None kontrolü atlanmalı, özel dizin dışarıda kalmalı."""
    mgr = _make_mgr(monkeypatch, tmp_path)

    root = tmp_path / "proj"
    excluded_dir = root / "skip_me"
    excluded_dir.mkdir(parents=True)
    (root / "good.py").write_text("x = 1\n", encoding="utf-8")
    (excluded_dir / "hidden.py").write_text("y = 2\n", encoding="utf-8")

    report = mgr.audit_project(str(root), exclude_dirs=["skip_me"])

    assert "good.py" in report or "Toplam Python" in report
    assert "hidden.py" not in report

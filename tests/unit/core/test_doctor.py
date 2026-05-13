from __future__ import annotations

import json

import pytest

from core import doctor
from core.doctor import DoctorCheck


@pytest.fixture(autouse=True)
def _isolate_database_env(monkeypatch):
    """Keep doctor database checks independent from shell/.env defaults."""
    for name in (
        "DATABASE_URL",
        "SIDAR_CONTAINER_DATABASE_URL",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
    ):
        monkeypatch.delenv(name, raising=False)


def test_run_doctor_report_writes_json_and_aggregates_warn(monkeypatch, tmp_path):
    checks = [
        DoctorCheck("uv", "pass", "ok"),
        DoctorCheck("gpu", "warn", "no gpu", {"run_gpu_stress": False}),
    ]
    monkeypatch.setattr(doctor, "check_uv", lambda: checks[0])
    monkeypatch.setattr(doctor, "check_database_env", lambda: DoctorCheck("db", "pass", "ok"))
    monkeypatch.setattr(doctor, "check_migrations", lambda: DoctorCheck("migrations", "pass", "ok"))
    monkeypatch.setattr(doctor, "check_agent_catalog", lambda: DoctorCheck("catalog", "pass", "ok"))
    monkeypatch.setattr(
        doctor, "check_supervisor_routing", lambda: DoctorCheck("routing", "pass", "ok")
    )
    monkeypatch.setattr(doctor, "check_websocket_routes", lambda: DoctorCheck("ws", "pass", "ok"))
    monkeypatch.setattr(doctor, "check_gpu", lambda: checks[1])
    monkeypatch.setattr(
        doctor, "check_model", lambda smoke=True: DoctorCheck("model", "pass", "ok")
    )

    output = tmp_path / "doctor.json"
    report = doctor.run_doctor_report(output_path=output)

    assert report["overall_status"] == "warn"
    assert report["run_gpu_stress"] is False
    assert json.loads(output.read_text(encoding="utf-8"))["overall_status"] == "warn"


def test_gpu_check_requests_stress_when_nvidia_smi_detected(monkeypatch):
    monkeypatch.setattr(
        doctor.shutil, "which", lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None
    )
    monkeypatch.setattr(doctor, "_run_command", lambda cmd, timeout=20: (0, "NVIDIA Test GPU"))

    check = doctor.check_gpu()

    assert check.status == "pass"
    assert check.details["detected"] is True
    assert check.details["run_gpu_stress"] is True


def test_websocket_check_falls_back_to_static_routes(monkeypatch, tmp_path):
    source = tmp_path / "web_server.py"
    source.write_text('@app.websocket("/ws/chat")\n@app.websocket("/ws/voice")\n', encoding="utf-8")
    monkeypatch.setattr(doctor, "BASE_DIR", tmp_path)

    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "web_server":
            raise RuntimeError("config not ready")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    check = doctor.check_websocket_routes()

    assert check.status == "warn"
    assert check.details["websocket_paths"] == ["/ws/chat", "/ws/voice"]


def test_migration_parser_identifies_head(tmp_path, monkeypatch):
    versions = tmp_path / "migrations" / "versions"
    versions.mkdir(parents=True)
    (versions / "0001_first.py").write_text(
        "revision = 'a'\ndown_revision = None\n", encoding="utf-8"
    )
    (versions / "0002_second.py").write_text(
        "revision = 'b'\ndown_revision = 'a'\n", encoding="utf-8"
    )
    monkeypatch.setattr(doctor, "migrations_path", lambda: tmp_path / "migrations")

    revisions, down_revisions = doctor._parse_migration_revisions()

    assert revisions == ["a", "b"]
    assert down_revisions == ["a"]


def test_run_command_success_file_not_found_and_timeout(monkeypatch):
    class Completed:
        returncode = 0
        stdout = " done \n"

    monkeypatch.setattr(doctor.subprocess, "run", lambda *args, **kwargs: Completed())
    assert doctor._run_command(["echo", "ok"]) == (0, "done")

    def raise_missing(*args, **kwargs):
        raise FileNotFoundError("missing-bin")

    monkeypatch.setattr(doctor.subprocess, "run", raise_missing)
    rc, output = doctor._run_command(["missing-bin"])
    assert rc == 127
    assert "missing-bin" in output

    def raise_timeout(*args, **kwargs):
        raise doctor.subprocess.TimeoutExpired(cmd=["slow"], timeout=3, output="partial")

    monkeypatch.setattr(doctor.subprocess, "run", raise_timeout)
    assert doctor._run_command(["slow"], timeout=3) == (124, "timeout after 3s\npartial")


def test_status_and_secret_helpers_cover_pass_warn_fail():
    assert doctor._status_from_bool(True) == "pass"
    assert doctor._status_from_bool(False, warn=True) == "warn"
    assert doctor._status_from_bool(False) == "fail"
    assert doctor._is_weak_secret(None) is True
    assert doctor._is_weak_secret("password") is True
    assert doctor._is_weak_secret("x" * 24) is False


def test_uv_check_reports_missing_and_lock_failure(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    missing = doctor.check_uv()
    assert missing.status == "fail"
    assert "not found" in missing.message

    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/bin/uv")

    def fake_run(cmd, timeout=20):
        return (1, "lock stale") if cmd[-2:] == ["lock", "--check"] else (0, "uv 1.0")

    monkeypatch.setattr(doctor, "_run_command", fake_run)
    failed = doctor.check_uv()
    assert failed.status == "fail"
    assert failed.details == {"path": "/bin/uv", "version": "uv 1.0", "lock_check": "lock stale"}


def test_uv_check_passes_when_binary_and_lock_are_ready(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/bin/uv")
    monkeypatch.setattr(doctor, "_run_command", lambda cmd, timeout=20: (0, "ok"))

    check = doctor.check_uv()

    assert check.status == "pass"
    assert check.message == "uv and uv.lock are ready"


def test_database_env_warns_without_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SIDAR_CONTAINER_DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    check = doctor.check_database_env()

    assert check.status == "warn"
    assert check.details["database_url_set"] is False


def test_database_env_fails_for_weak_passwords_and_legacy_container_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://sidar:short@localhost:5432/sidar")
    monkeypatch.setenv("POSTGRES_PASSWORD", "postgres")
    monkeypatch.setenv("SIDAR_CONTAINER_DATABASE_URL", "postgresql://sidar:sidar@db/sidar")

    check = doctor.check_database_env()

    assert check.status == "fail"
    assert "weak database password" in check.message
    assert "POSTGRES_PASSWORD is weak" in check.message
    assert "legacy default password" in check.message
    assert check.details["scheme"] == "postgresql"
    assert check.details["container_scheme"] == "postgresql"


def test_database_env_fails_when_database_url_password_differs_from_postgres_password(
    monkeypatch,
):
    monkeypatch.setenv("POSTGRES_USER", "sidar")
    monkeypatch.setenv("POSTGRES_PASSWORD", "a" * 24)
    monkeypatch.setenv("POSTGRES_DB", "sidar")
    monkeypatch.setenv("DATABASE_URL", "postgresql://sidar:" + "b" * 24 + "@localhost:5432/sidar")
    monkeypatch.setenv(
        "SIDAR_CONTAINER_DATABASE_URL", "postgresql://sidar:" + "a" * 24 + "@db:5432/sidar"
    )

    check = doctor.check_database_env()

    assert check.status == "fail"
    assert "DATABASE_URL password does not match POSTGRES_PASSWORD" in check.message
    assert check.details["postgres_user_set"] is True
    assert check.details["postgres_db_set"] is True


def test_database_env_warns_when_database_name_differs_from_postgres_db(monkeypatch):
    monkeypatch.setenv("POSTGRES_USER", "sidar")
    monkeypatch.setenv("POSTGRES_PASSWORD", "a" * 24)
    monkeypatch.setenv("POSTGRES_DB", "sidar")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://sidar:" + "a" * 24 + "@localhost:5432/other"
    )

    check = doctor.check_database_env()

    assert check.status == "warn"
    assert "DATABASE_URL database name does not match POSTGRES_DB" in check.message


def test_database_env_passes_for_strong_postgres_settings(monkeypatch):
    password = "a" * 24
    monkeypatch.setenv("POSTGRES_USER", "sidar")
    monkeypatch.setenv("POSTGRES_PASSWORD", password)
    monkeypatch.setenv("POSTGRES_DB", "sidar")
    monkeypatch.setenv("DATABASE_URL", f"postgresql://sidar:{password}@localhost:5432/sidar")
    monkeypatch.setenv("SIDAR_CONTAINER_DATABASE_URL", f"postgresql://sidar:{password}@db/sidar")

    check = doctor.check_database_env()

    assert check.status == "pass"
    assert check.message == "database environment looks secure"


def test_migrations_fail_when_no_revisions(monkeypatch, tmp_path):
    versions = tmp_path / "migrations" / "versions"
    versions.mkdir(parents=True)
    monkeypatch.setattr(doctor, "migrations_path", lambda: tmp_path / "migrations")

    check = doctor.check_migrations()

    assert check.status == "fail"
    assert check.message == "no Alembic migration revisions found"


def test_migrations_pass_and_warn_based_on_alembic_head(monkeypatch, tmp_path):
    versions = tmp_path / "migrations" / "versions"
    versions.mkdir(parents=True)
    (versions / "0001.py").write_text("revision = 'base'\ndown_revision = None\n", encoding="utf-8")
    (versions / "0002.py").write_text(
        "revision = 'head'\ndown_revision = 'base'\n", encoding="utf-8"
    )
    monkeypatch.setattr(doctor, "migrations_path", lambda: tmp_path / "migrations")
    monkeypatch.setattr(doctor, "_run_command", lambda cmd, timeout=20: (0, "head"))

    passed = doctor.check_migrations()
    assert passed.status == "pass"
    assert passed.details["expected_heads"] == ["head"]

    monkeypatch.setattr(doctor, "_run_command", lambda cmd, timeout=20: (1, "broken"))
    warned = doctor.check_migrations()
    assert warned.status == "warn"
    assert warned.details["alembic_heads_output"] == "broken"


def test_agent_catalog_reports_registered_missing_and_import_failure(monkeypatch):
    class Spec:
        def __init__(self, role_name):
            self.role_name = role_name

    class Catalog:
        @staticmethod
        def list_all():
            return [
                Spec(role)
                for role in {"coder", "researcher", "reviewer", "poyraz", "qa", "coverage"}
            ]

    original_import = __import__

    def catalog_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "agent.registry":
            return type("RegistryModule", (), {"AgentCatalog": Catalog})()
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", catalog_import)
    assert doctor.check_agent_catalog().status == "pass"

    class MissingCatalog:
        @staticmethod
        def list_all():
            return [Spec("coder")]

    def missing_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "agent.registry":
            return type("RegistryModule", (), {"AgentCatalog": MissingCatalog})()
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", missing_import)
    missing = doctor.check_agent_catalog()
    assert missing.status == "fail"
    assert "coverage" in missing.message

    def failing_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "agent.registry":
            raise RuntimeError("registry broken")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", failing_import)
    failed = doctor.check_agent_catalog()
    assert failed.status == "fail"
    assert "registry broken" in failed.message


def test_supervisor_routing_reports_success_mismatch_and_import_failure(monkeypatch):
    class SupervisorAgent:
        @staticmethod
        def _intent(prompt):
            mapping = {
                "web kaynak araştır": "research",
                "pull request review incele": "review",
                "seo kampanya metni üret": "marketing",
                "pytest coverage eksik test yaz": "coverage",
                "dosyaya fonksiyon ekle": "code",
            }
            return mapping[prompt]

    original_import = __import__

    def supervisor_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "agent.core.supervisor":
            return type("SupervisorModule", (), {"SupervisorAgent": SupervisorAgent})()
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", supervisor_import)
    assert doctor.check_supervisor_routing().status == "pass"

    class MismatchSupervisor:
        @staticmethod
        def _intent(prompt):
            return "code"

    def mismatch_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "agent.core.supervisor":
            return type("SupervisorModule", (), {"SupervisorAgent": MismatchSupervisor})()
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", mismatch_import)
    mismatch = doctor.check_supervisor_routing()
    assert mismatch.status == "fail"
    assert "routing mismatches" in mismatch.message

    def failing_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "agent.core.supervisor":
            raise RuntimeError("supervisor broken")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", failing_import)
    failed = doctor.check_supervisor_routing()
    assert failed.status == "fail"
    assert "supervisor broken" in failed.message


def test_websocket_check_reports_imported_routes_and_missing_static(monkeypatch, tmp_path):
    class WebSocketRoute:
        def __init__(self, path):
            self.path = path

    class HttpRoute:
        path = "/http"

    app = type(
        "App",
        (),
        {"routes": [WebSocketRoute("/ws/chat"), WebSocketRoute("/ws/voice"), HttpRoute()]},
    )()
    original_import = __import__

    def web_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "web_server":
            return type("WebServerModule", (), {"app": app})()
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", web_import)
    assert doctor.check_websocket_routes().status == "pass"

    missing_app = type("App", (), {"routes": [WebSocketRoute("/ws/chat")]})()

    def missing_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "web_server":
            return type("WebServerModule", (), {"app": missing_app})()
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", missing_import)
    imported_missing = doctor.check_websocket_routes()
    assert imported_missing.status == "fail"
    assert imported_missing.details["websocket_paths"] == ["/ws/chat"]

    (tmp_path / "web_server.py").write_text('@app.websocket("/ws/chat")\n', encoding="utf-8")
    monkeypatch.setattr(doctor, "BASE_DIR", tmp_path)

    def broken_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "web_server":
            raise RuntimeError("web import broken")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", broken_import)
    static_missing = doctor.check_websocket_routes()
    assert static_missing.status == "fail"
    assert static_missing.details["websocket_paths"] == ["/ws/chat"]


def test_gpu_check_uses_torch_fallback_and_records_torch_errors(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    original_import = __import__

    class Cuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def device_count():
            return 2

        @staticmethod
        def get_device_name(index):
            return f"GPU-{index}"

    def torch_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "torch":
            return type("TorchModule", (), {"cuda": Cuda})()
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", torch_import)
    check = doctor.check_gpu()
    assert check.status == "pass"
    assert check.details["source"] == "torch"
    assert check.details["devices"] == ["GPU-0", "GPU-1"]

    def failing_torch_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "torch":
            raise RuntimeError("torch unavailable")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", failing_torch_import)
    failed = doctor.check_gpu()
    assert failed.status == "warn"
    assert failed.details["torch_error"] == "torch unavailable"


def test_ollama_base_url_normalizes_api_suffix(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://ollama:11434")
    assert doctor._ollama_base_url() == "http://ollama:11434/api"
    monkeypatch.setenv("OLLAMA_URL", "http://ollama:11434/api/")
    assert doctor._ollama_base_url() == "http://ollama:11434/api"


def test_model_check_handles_present_missing_smoke_failure_and_http_errors(monkeypatch):
    class Response:
        def __init__(self, payload, *, raise_error=False):
            self.payload = payload
            self.raise_error = raise_error

        def raise_for_status(self):
            if self.raise_error:
                raise RuntimeError("http down")

        def json(self):
            return self.payload

    class Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url):
            return Response({"models": [{"name": "qwen2.5-coder:7b"}]})

        def post(self, url, json, timeout):
            return Response({"response": '{"sidar_doctor": true}'})

    original_import = __import__

    def httpx_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "httpx":
            return type("HttpxModule", (), {"Client": Client})()
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", httpx_import)
    assert doctor.check_model().status == "pass"
    assert doctor.check_model(coding_model="qwen2.5-coder:latest", smoke=False).status == "pass"

    class MissingClient(Client):
        def get(self, url):
            return Response({"models": [{"name": "llama3"}]})

    def missing_httpx_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "httpx":
            return type("HttpxModule", (), {"Client": MissingClient})()
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", missing_httpx_import)
    missing = doctor.check_model(coding_model="qwen2.5-coder:7b")
    assert missing.status == "warn"
    assert missing.details["present"] is False

    class BadSmokeClient(Client):
        def post(self, url, json, timeout):
            return Response({"response": '{"sidar_doctor": false}'})

    def bad_smoke_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "httpx":
            return type("HttpxModule", (), {"Client": BadSmokeClient})()
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", bad_smoke_import)
    bad_smoke = doctor.check_model()
    assert bad_smoke.status == "fail"
    assert bad_smoke.details["json_smoke"] is False

    class ErrorClient(Client):
        def get(self, url):
            return Response({}, raise_error=True)

    def error_httpx_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "httpx":
            return type("HttpxModule", (), {"Client": ErrorClient})()
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", error_httpx_import)
    error = doctor.check_model()
    assert error.status == "warn"
    assert "http down" in error.details["error"]


def test_run_doctor_report_aggregates_failures_and_skips_model_smoke(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "check_uv", lambda: DoctorCheck("uv", "pass", "ok"))
    monkeypatch.setattr(doctor, "check_database_env", lambda: DoctorCheck("db", "fail", "bad"))
    monkeypatch.setattr(doctor, "check_migrations", lambda: DoctorCheck("migrations", "pass", "ok"))
    monkeypatch.setattr(doctor, "check_agent_catalog", lambda: DoctorCheck("catalog", "pass", "ok"))
    monkeypatch.setattr(
        doctor, "check_supervisor_routing", lambda: DoctorCheck("routing", "pass", "ok")
    )
    monkeypatch.setattr(doctor, "check_websocket_routes", lambda: DoctorCheck("ws", "pass", "ok"))
    monkeypatch.setattr(
        doctor, "check_gpu", lambda: DoctorCheck("gpu", "pass", "ok", {"run_gpu_stress": True})
    )

    observed = {}

    def fake_model(*, smoke=True):
        observed["smoke"] = smoke
        return DoctorCheck("model", "pass", "ok")

    monkeypatch.setattr(doctor, "check_model", fake_model)
    report = doctor.run_doctor_report(
        output_path=tmp_path / "doctor.json", include_model_smoke=False
    )

    assert report["overall_status"] == "fail"
    assert report["run_gpu_stress"] is True
    assert observed == {"smoke": False}


def test_main_returns_zero_for_warn_and_one_for_fail(monkeypatch, tmp_path, capsys):
    output = tmp_path / "doctor.json"
    monkeypatch.setattr(doctor.sys, "argv", ["sidar-doctor", str(output)])
    monkeypatch.setattr(
        doctor,
        "run_doctor_report",
        lambda output_path: {
            "overall_status": "warn",
            "checks": [],
            "output_path": str(output_path),
        },
    )
    assert doctor.main() == 0
    assert "warn" in capsys.readouterr().out

    monkeypatch.setattr(doctor.sys, "argv", ["sidar-doctor"])
    monkeypatch.setattr(
        doctor,
        "run_doctor_report",
        lambda output_path: {
            "overall_status": "fail",
            "checks": [],
            "output_path": str(output_path),
        },
    )
    assert doctor.main() == 1

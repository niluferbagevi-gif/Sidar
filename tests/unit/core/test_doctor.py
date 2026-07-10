from __future__ import annotations

import json
import sys
import types

import pytest

from core import doctor
from core.doctor import DoctorCheck

# scripts.secret_strength.is_weak_secret rejects low-uniqueness/repeated-character
# strings (e.g. "a" * 24), so fixtures standing in for a genuinely strong secret
# need real entropy instead of a repeated filler character.
_STRONG_TEST_PASSWORD = "Dk4uZsySGysqYRv0MtiFeJIgI69s"


@pytest.fixture(autouse=True)
def _isolate_database_env(monkeypatch):
    """Keep doctor database checks independent from shell/.env defaults."""
    for name in (
        "DATABASE_URL",
        "SIDAR_CONTAINER_DATABASE_URL",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "RAG_VECTOR_BACKEND",
        "ENABLE_GRAPH_RAG",
        "RAG_DIR",
        "HEALTHCHECK_CONNECT_TIMEOUT_MS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_run_doctor_report_writes_json_and_aggregates_warn(monkeypatch, tmp_path):
    checks = [
        DoctorCheck("uv", "pass", "ok"),
        DoctorCheck("gpu", "warn", "no gpu", {"run_gpu_stress": False}),
    ]
    monkeypatch.setattr(doctor, "check_uv", lambda: checks[0])
    monkeypatch.setattr(
        doctor, "check_environment_profile", lambda: DoctorCheck("env", "pass", "ok")
    )
    monkeypatch.setattr(
        doctor, "check_gpu_memory_config", lambda: DoctorCheck("gpu_memory_config", "pass", "ok")
    )
    monkeypatch.setattr(doctor, "check_database_env", lambda: DoctorCheck("db", "pass", "ok"))
    monkeypatch.setattr(
        doctor, "check_database_connectivity", lambda: DoctorCheck("db_conn", "pass", "ok")
    )
    monkeypatch.setattr(doctor, "check_rag_readiness", lambda: DoctorCheck("rag", "pass", "ok"))
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
    assert doctor._is_weak_secret(_STRONG_TEST_PASSWORD) is False


def test_runtime_and_redaction_helpers_cover_edge_cases(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda name: object())
    assert doctor.check_prometheus_runtime().status == "pass"

    assert doctor._redact_url("postgresql://sidar@localhost/sidar") == (
        "postgresql://sidar@localhost/sidar"
    )
    redacted = doctor._redact_exception_text(
        RuntimeError("password secret-value in postgresql://sidar:secret-value@localhost/sidar"),
        database_url="postgresql://sidar:secret-value@localhost/sidar",
    )
    assert "secret-value" not in redacted

    monkeypatch.setenv("FEATURE_FLAG", "off")
    assert doctor._get_bool_env("FEATURE_FLAG", True) is False
    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("[", encoding="utf-8")
    assert doctor._load_json_object(invalid_json) == {}


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (RuntimeError("role sidar does not exist"), "missing_role_or_database"),
        (RuntimeError("SSL handshake failed: certificate verify failed"), "tls"),
        (TimeoutError("timed out"), "timeout"),
        (ConnectionRefusedError("connection refused"), "connection"),
        (RuntimeError("unexpected failure"), "unknown"),
    ],
)
def test_postgres_connectivity_failure_guidance_classifies_errors(error, category):
    message, details = doctor._postgres_connectivity_failure_guidance(error)

    assert message
    assert details["failure_category"] == category


def test_dotenv_helpers_parse_assignments_and_report_effective_sources(monkeypatch, tmp_path):
    env_file = tmp_path / ".env.test"
    env_file.write_text(
        "\n# comment\nexport DATABASE_URL='postgresql://sidar:test@localhost/sidar'\n"
        "INVALID KEY=value\nEMPTY_KEY = ignored\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://sidar:test@localhost/sidar")

    values = doctor._parse_env_file_values(env_file)
    assignments = doctor._read_env_file_assignments(env_file)

    assert values == {
        "DATABASE_URL": "postgresql://sidar:test@localhost/sidar",
        "EMPTY_KEY": "ignored",
    }
    assert assignments["DATABASE_URL"] == "postgresql://sidar:test@localhost/sidar"

    import config

    monkeypatch.setattr(
        config,
        "get_dotenv_load_report",
        lambda: [
            {"loaded": False, "path": str(env_file)},
            {"loaded": True, "path": str(env_file), "label": "profile", "override": True},
        ],
    )
    report = doctor._dotenv_source_report(("DATABASE_URL", "POSTGRES_DB"))

    assert report["sources"]["DATABASE_URL"]["label"] == "profile"
    assert report["definitions"]["POSTGRES_DB"] == []


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


def test_database_env_derives_urls_when_missing_but_postgres_password_present(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SIDAR_CONTAINER_DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_USER", "sidar")
    monkeypatch.setenv("POSTGRES_PASSWORD", _STRONG_TEST_PASSWORD)
    monkeypatch.setenv("POSTGRES_DB", "sidar")

    check = doctor.check_database_env()

    assert check.status == "pass"
    assert check.details["database_url_set"] is True
    assert check.details["container_database_url_set"] is True
    assert check.details["database_url_explicit"] is False
    assert check.details["container_database_url_explicit"] is False
    assert check.details["database_url_derived"] is True
    assert check.details["postgres_password_set"] is True


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
    assert (
        check.details["auto_fix"]
        == "uv run python -m scripts.sync_database_passwords --remove-explicit-urls"
    )
    assert (
        "uv run python -m scripts.sync_database_passwords --remove-explicit-urls"
        in check.details["recommended_commands"]
    )
    assert "otomatik üretir" in check.details["root_cause_hints"][0]
    assert not any("Docker volume" in hint for hint in check.details["root_cause_hints"])


def test_database_env_fails_when_local_and_container_passwords_drift_without_postgres_password(
    monkeypatch,
):
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("POSTGRES_USER", raising=False)
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://sidar:" + "a" * 24 + "@localhost:5432/sidar")
    monkeypatch.setenv(
        "SIDAR_CONTAINER_DATABASE_URL", "postgresql://sidar:" + "b" * 24 + "@postgres:5432/sidar"
    )

    check = doctor.check_database_env()

    assert check.status == "fail"
    assert (
        "DATABASE_URL password does not match SIDAR_CONTAINER_DATABASE_URL password"
        in check.message
    )


def test_database_env_warns_when_local_and_container_database_names_drift(monkeypatch):
    password = _STRONG_TEST_PASSWORD
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    monkeypatch.setenv("POSTGRES_PASSWORD", password)
    monkeypatch.setenv("DATABASE_URL", f"postgresql://sidar:{password}@localhost:5432/sidar")
    monkeypatch.setenv(
        "SIDAR_CONTAINER_DATABASE_URL", f"postgresql://sidar:{password}@postgres:5432/sidar_ci"
    )

    check = doctor.check_database_env()

    assert check.status == "warn"
    assert "DATABASE_URL database name does not match SIDAR_CONTAINER_DATABASE_URL" in check.message


def test_database_env_warns_when_database_name_differs_from_postgres_db(monkeypatch):
    monkeypatch.setenv("POSTGRES_USER", "sidar")
    monkeypatch.setenv("POSTGRES_PASSWORD", _STRONG_TEST_PASSWORD)
    monkeypatch.setenv("POSTGRES_DB", "sidar")
    monkeypatch.setenv(
        "DATABASE_URL", f"postgresql://sidar:{_STRONG_TEST_PASSWORD}@localhost:5432/other"
    )

    check = doctor.check_database_env()

    assert check.status == "warn"
    assert "DATABASE_URL database name does not match POSTGRES_DB" in check.message


def test_database_env_allows_non_postgres_url_without_postgres_sync_failures(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///tmp/sidar.db")
    monkeypatch.setenv("POSTGRES_USER", "sidar")
    monkeypatch.setenv("POSTGRES_PASSWORD", _STRONG_TEST_PASSWORD)
    monkeypatch.setenv("POSTGRES_DB", "sidar")

    check = doctor.check_database_env()

    assert check.status == "pass"
    assert check.details["scheme"] == "sqlite"


def test_database_env_fails_when_database_url_user_differs_from_postgres_user(monkeypatch):
    password = "a" * 24
    monkeypatch.setenv("POSTGRES_USER", "sidar")
    monkeypatch.setenv("POSTGRES_PASSWORD", password)
    monkeypatch.setenv("POSTGRES_DB", "sidar")
    monkeypatch.setenv("DATABASE_URL", f"postgresql://other:{password}@localhost:5432/sidar")

    check = doctor.check_database_env()

    assert check.status == "fail"
    assert "DATABASE_URL user does not match POSTGRES_USER" in check.message


def test_database_env_passes_for_strong_postgres_settings(monkeypatch):
    password = _STRONG_TEST_PASSWORD
    monkeypatch.setenv("POSTGRES_USER", "sidar")
    monkeypatch.setenv("POSTGRES_PASSWORD", password)
    monkeypatch.setenv("POSTGRES_DB", "sidar")
    monkeypatch.setenv("DATABASE_URL", f"postgresql://sidar:{password}@localhost:5432/sidar")
    monkeypatch.setenv("SIDAR_CONTAINER_DATABASE_URL", f"postgresql://sidar:{password}@db/sidar")

    check = doctor.check_database_env()

    assert check.status == "pass"
    assert check.message == "database environment looks secure"


def test_database_connectivity_passes_and_redacts_password(monkeypatch):
    class _Conn:
        async def fetchval(self, query):
            if "pg_extension" in query:
                return True
            return 1

        async def close(self):
            return None

    async def _connect(dsn):
        assert dsn == "postgresql://sidar:secretpasswordsecretpassword@localhost:5432/sidar"
        return _Conn()

    monkeypatch.setitem(sys.modules, "asyncpg", types.SimpleNamespace(connect=_connect))
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://sidar:secretpasswordsecretpassword@localhost:5432/sidar",
    )
    monkeypatch.setenv("HEALTHCHECK_CONNECT_TIMEOUT_MS", "1000")

    check = doctor.check_database_connectivity()

    assert check.status == "pass"
    assert check.details["select_1"] is True
    assert check.details["pgvector_extension_installed"] is True
    assert "secretpassword" not in check.details["database_url"]


def test_database_connectivity_uses_derived_database_url(monkeypatch):
    captured = {}

    class _Conn:
        async def fetchval(self, query):
            return True if "pg_extension" in query else 1

        async def close(self):
            return None

    async def _connect(dsn):
        captured["dsn"] = dsn
        return _Conn()

    monkeypatch.setitem(sys.modules, "asyncpg", types.SimpleNamespace(connect=_connect))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_USER", "sidar")
    monkeypatch.setenv("POSTGRES_PASSWORD", "a" * 24)
    monkeypatch.setenv("POSTGRES_DB", "sidar")
    monkeypatch.setenv("HEALTHCHECK_CONNECT_TIMEOUT_MS", "1000")

    check = doctor.check_database_connectivity()

    assert check.status == "pass"
    assert check.details["database_url_explicit"] is False
    assert check.details["database_url_derived"] is True
    assert captured["dsn"].startswith("postgresql://sidar:")


def test_database_connectivity_warns_when_postgres_unreachable(monkeypatch):
    async def _connect(dsn):
        raise ConnectionRefusedError("db down")

    monkeypatch.setitem(sys.modules, "asyncpg", types.SimpleNamespace(connect=_connect))
    monkeypatch.setenv("DATABASE_URL", "postgresql://sidar:" + "a" * 24 + "@localhost:5432/sidar")

    check = doctor.check_database_connectivity()

    assert check.status == "warn"
    assert "container/service is running" in check.message
    assert check.details["failure_category"] == "connection"
    assert check.details["error_type"] == "ConnectionRefusedError"
    assert "docker compose ps postgres" in check.details["recommended_commands"]


def test_database_connectivity_warns_when_postgres_times_out(monkeypatch):
    async def _connect(dsn):
        raise TimeoutError("connection timed out")

    monkeypatch.setitem(sys.modules, "asyncpg", types.SimpleNamespace(connect=_connect))
    monkeypatch.setenv("DATABASE_URL", "postgresql://sidar:" + "a" * 24 + "@localhost:5432/sidar")

    check = doctor.check_database_connectivity()

    assert check.status == "warn"
    assert check.details["failure_category"] == "timeout"
    assert "timed out" in check.message


def test_database_checks_fail_fast_for_malformed_dsn(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://sidar:secret@[invalid/sidar")
    monkeypatch.setenv("SIDAR_CONTAINER_DATABASE_URL", "postgresql://sidar:secret@[invalid/sidar")
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "pgvector")
    monkeypatch.setenv("RAG_DIR", str(tmp_path / "rag"))

    env_check = doctor.check_database_env()
    connectivity_check = doctor.check_database_connectivity()
    pgvector_check = doctor.check_pgvector_ready()
    rag_state = doctor._rag_readiness_state()

    assert env_check.status == "fail"
    assert "DATABASE_URL is malformed" in env_check.message
    assert "SIDAR_CONTAINER_DATABASE_URL is malformed" in env_check.message
    assert connectivity_check.status == "warn"
    assert connectivity_check.details["failure_category"] == "invalid_dsn"
    assert "DATABASE_URL is malformed" in connectivity_check.message
    assert pgvector_check.status == "warn"
    assert pgvector_check.details["failure_category"] == "invalid_dsn"
    assert rag_state["details"]["database_env_status"] == "fail"
    assert rag_state["details"]["blocked_by"] == "database_env"


def test_database_connectivity_auth_failure_reports_volume_remediation_and_redacts(
    monkeypatch,
):
    password = "secretpasswordsecretpassword"

    async def _connect(dsn):
        raise RuntimeError(f"password authentication failed for {dsn} with password={password}")

    monkeypatch.setitem(sys.modules, "asyncpg", types.SimpleNamespace(connect=_connect))
    monkeypatch.setenv(
        "DATABASE_URL", f"postgresql+asyncpg://sidar:{password}@localhost:5432/sidar"
    )

    check = doctor.check_database_connectivity()

    assert check.status == "warn"
    assert "Docker volume already existed" in check.message
    assert check.details["failure_category"] == "authentication"
    assert check.details["auto_fix"] == "uv run python -m scripts.sync_postgres_password"
    assert any("older password" in hint for hint in check.details["root_cause_hints"])
    assert (
        check.details["recommended_commands"][0]
        == "uv run python -m scripts.sync_postgres_password"
    )
    assert not any("<POSTGRES_PASSWORD>" in cmd for cmd in check.details["recommended_commands"])
    assert password not in check.details["error"]
    assert "postgresql+asyncpg://sidar:" not in check.details["error"]


async def test_run_coro_sync_works_inside_running_event_loop() -> None:
    async def _value() -> int:
        return 7

    assert doctor._run_coro_sync(_value()) == 7


def test_database_connectivity_warns_when_pgvector_extension_missing(monkeypatch):
    class _Conn:
        async def fetchval(self, query):
            if "pg_extension" in query:
                return False
            return 1

        async def close(self):
            return None

    async def _connect(dsn):
        return _Conn()

    monkeypatch.setitem(sys.modules, "asyncpg", types.SimpleNamespace(connect=_connect))
    monkeypatch.setenv("DATABASE_URL", "postgresql://sidar:" + "a" * 24 + "@localhost:5432/sidar")
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "pgvector")

    check = doctor.check_database_connectivity()

    assert check.status == "warn"
    assert "pgvector extension is not installed" in check.message


def test_pgvector_ready_warns_when_database_url_is_missing(monkeypatch):
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "pgvector")
    monkeypatch.setattr(doctor, "_resolved_database_urls", lambda: ("", "", False, False))

    check = doctor.check_pgvector_ready()

    assert check.status == "warn"
    assert check.message == "DATABASE_URL could not be resolved"


def test_pgvector_ready_warns_for_non_postgres_url(monkeypatch):
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "pgvector")
    monkeypatch.setattr(
        doctor, "_resolved_database_urls", lambda: ("sqlite:///sidar.db", "", True, False)
    )

    check = doctor.check_pgvector_ready()

    assert check.status == "warn"
    assert "DATABASE_URL is not PostgreSQL" in check.message


def test_pgvector_ready_reports_probe_errors_without_leaking_credentials(monkeypatch):
    database_url = "postgresql://sidar:secret-value@localhost:5432/sidar"
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "pgvector")
    monkeypatch.setattr(doctor, "_resolved_database_urls", lambda: (database_url, "", True, False))

    def _raise_probe_error(awaitable):
        awaitable.close()
        raise RuntimeError(f"cannot connect to {database_url}")

    monkeypatch.setattr(doctor, "_run_coro_sync", _raise_probe_error)

    check = doctor.check_pgvector_ready()

    assert check.status == "warn"
    assert check.details["error_type"] == "RuntimeError"
    assert "secret-value" not in check.details["error"]


def test_pgvector_ready_passes_when_extension_probe_succeeds(monkeypatch):
    database_url = "postgresql://sidar:secret-value@localhost:5432/sidar"
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "pgvector")
    monkeypatch.setattr(doctor, "_resolved_database_urls", lambda: (database_url, "", True, False))

    def _successful_probe(awaitable):
        awaitable.close()
        return {"pgvector_extension_installed": True}

    monkeypatch.setattr(doctor, "_run_coro_sync", _successful_probe)

    check = doctor.check_pgvector_ready()

    assert check.status == "pass"
    assert check.message == "pgvector extension is installed"


def test_rag_readiness_warns_for_missing_index_with_auto_fix(monkeypatch, tmp_path):
    rag_dir = tmp_path / "rag"
    rag_dir.mkdir()
    monkeypatch.setenv("RAG_DIR", str(rag_dir))

    check = doctor.check_rag_readiness()

    assert check.status == "warn"
    assert check.details["document_count"] == 0
    assert check.details["index_exists"] is False
    assert check.details["auto_fix"] == "uv run python -m scripts.seed_rag"
    assert "index file is missing" in check.message
    assert "entity memory is empty" in check.message
    assert "uv run python -m scripts.seed_rag" in check.details["recommended_commands"]
    assert any("belge ekle <url>" in cmd for cmd in check.details["recommended_commands"])
    assert check.as_dict()["details"]["auto_fix"] == "uv run python -m scripts.seed_rag"


def test_rag_readiness_warns_for_existing_empty_index(monkeypatch, tmp_path):
    rag_dir = tmp_path / "rag"
    rag_dir.mkdir()
    (rag_dir / "index.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("RAG_DIR", str(rag_dir))

    check = doctor.check_rag_readiness()

    assert check.status == "warn"
    assert check.details["index_exists"] is True
    assert "no indexed documents" in check.message
    assert "index file is missing" not in check.message


def test_rag_readiness_is_blocked_when_pgvector_env_parity_fails(monkeypatch, tmp_path):
    rag_dir = tmp_path / "rag"
    rag_dir.mkdir()
    (rag_dir / "index.json").write_text('{"doc": {"title": "ok"}}', encoding="utf-8")
    (rag_dir / "entity_graph.json").write_text(
        '{"nodes": {"brand:x": {"label": "Brand"}}, "edges": []}',
        encoding="utf-8",
    )
    monkeypatch.setenv("RAG_DIR", str(rag_dir))
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "pgvector")
    monkeypatch.setenv("POSTGRES_PASSWORD", "a" * 24)
    monkeypatch.setenv("DATABASE_URL", "postgresql://sidar:" + "b" * 24 + "@localhost:5432/sidar")

    check = doctor.check_rag_readiness()

    assert check.status == "warn"
    assert "blocked until database_env is fixed" in check.message
    assert check.details["database_env_status"] == "fail"
    assert check.details["blocked_by"] == "database_env"
    assert (
        check.details["auto_fix"]
        == "uv run python -m scripts.sync_database_passwords --remove-explicit-urls"
    )
    assert check.details["auto_fix_steps"] == [
        "uv run python -m scripts.sync_database_passwords --remove-explicit-urls"
    ]
    assert (
        "uv run python -m scripts.sync_database_passwords --remove-explicit-urls"
        in check.details["recommended_commands"]
    )
    assert "uv run python -m scripts.seed_rag" not in check.details["recommended_commands"]
    assert "uv run python -m scripts.seed_rag" in check.details["follow_up_commands"]


def test_rag_readiness_pgvector_env_snapshot_does_not_reenter_database_check(monkeypatch, tmp_path):
    rag_dir = tmp_path / "rag"
    rag_dir.mkdir()
    (rag_dir / "index.json").write_text('{"doc": {"title": "ok"}}', encoding="utf-8")
    (rag_dir / "entity_graph.json").write_text(
        '{"nodes": {"brand:x": {"label": "Brand"}}, "edges": []}',
        encoding="utf-8",
    )
    monkeypatch.setenv("RAG_DIR", str(rag_dir))
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "pgvector")
    monkeypatch.setenv("POSTGRES_PASSWORD", "a" * 24)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://sidar:" + "b" * 24 + "@localhost:5432/sidar",
    )

    def _unexpected_database_check():
        raise AssertionError("_rag_readiness_state must not call check_database_env")

    monkeypatch.setattr(doctor, "check_database_env", _unexpected_database_check)

    state = doctor._rag_readiness_state()

    assert state["details"]["database_env_status"] == "fail"
    assert state["details"]["blocked_by"] == "database_env"
    assert state["details"]["database_env_auto_fix"] == (
        "uv run python -m scripts.sync_database_passwords --remove-explicit-urls"
    )


def test_rag_readiness_prefers_database_sync_auto_fix_when_blocked_and_unseeded(
    monkeypatch, tmp_path
):
    rag_dir = tmp_path / "rag"
    rag_dir.mkdir()
    monkeypatch.setenv("RAG_DIR", str(rag_dir))
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "pgvector")
    monkeypatch.setenv("POSTGRES_PASSWORD", "a" * 24)
    monkeypatch.setenv("DATABASE_URL", "postgresql://sidar:" + "b" * 24 + "@localhost:5432/sidar")

    check = doctor.check_rag_readiness()

    assert check.status == "warn"
    assert check.details["blocked_by"] == "database_env"
    assert (
        check.details["auto_fix"]
        == "uv run python -m scripts.sync_database_passwords --remove-explicit-urls"
    )
    assert check.details["auto_fix_steps"] == [
        "uv run python -m scripts.sync_database_passwords --remove-explicit-urls",
        "uv run python -m scripts.seed_rag",
    ]
    assert check.details["recommended_commands"][:2] == [
        "uv run python -m scripts.sync_database_passwords --remove-explicit-urls",
        "uv run python -m scripts.seed_rag",
    ]
    assert "index file is missing" in check.message


def test_rag_index_ready_passes_with_documents_and_marks_empty_entity_memory(monkeypatch, tmp_path):
    rag_dir = tmp_path / "rag"
    rag_dir.mkdir()
    (rag_dir / "index.json").write_text('{"doc": {"title": "ok"}}', encoding="utf-8")
    monkeypatch.setattr(
        doctor,
        "_rag_readiness_state",
        lambda: {
            "details": {"rag_dir": str(rag_dir)},
            "blockers": [],
            "warnings": [],
            "document_count": 1,
            "entity_memory_empty": True,
        },
    )

    check = doctor.check_rag_index_ready()

    assert check.status == "pass"
    assert check.message == "RAG index readiness looks healthy"
    assert check.details["graphrag_entity_memory_warning"] is True
    assert check.details["auto_fix"] == ""


def test_graphrag_entity_memory_ready_reports_disabled_graph_and_store_mismatch(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(doctor, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        doctor,
        "_rag_readiness_state",
        lambda: {
            "details": {
                "graph_rag_enabled": False,
                "rag_dir": "relative-rag",
                "entity_node_count": 1,
            },
            "warnings": [],
            "entity_memory_empty": False,
        },
    )
    monkeypatch.setattr(
        doctor,
        "_query_entity_graph_counts_from_store",
        lambda rag_dir: {"ok": True, "entity_node_count": 2, "entity_edge_count": 1},
    )

    check = doctor.check_graphrag_entity_memory_ready()

    assert check.status == "warn"
    assert check.message == "GraphRAG is disabled by configuration"
    assert check.details["entity_count_mismatch"] is True
    assert check.details["entity_node_count_store"] == 2


def test_graphrag_entity_memory_ready_warns_when_store_probe_is_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(
        doctor,
        "_rag_readiness_state",
        lambda: {
            "details": {
                "graph_rag_enabled": True,
                "rag_dir": str(tmp_path),
                "entity_node_count": 1,
            },
            "warnings": [],
            "entity_memory_empty": False,
        },
    )
    monkeypatch.setattr(
        doctor,
        "_query_entity_graph_counts_from_store",
        lambda rag_dir: {"ok": True, "entity_node_count": 0, "entity_edge_count": 0},
    )

    check = doctor.check_graphrag_entity_memory_ready()

    assert check.status == "warn"
    assert "empty after store probe" in check.message
    assert check.details["auto_fix"] == "uv run python -m scripts.seed_rag --metadata-only"


def test_rag_readiness_aggregate_reports_fail_and_healthy_states(monkeypatch):
    monkeypatch.setattr(
        doctor,
        "_rag_readiness_state",
        lambda: {"details": {"document_count": 1, "index_exists": True}},
    )
    monkeypatch.setattr(
        doctor,
        "check_rag_index_ready",
        lambda: DoctorCheck("rag_index_ready", "fail", "bad", {"recommended_commands": []}),
    )
    monkeypatch.setattr(
        doctor,
        "check_graphrag_entity_memory_ready",
        lambda: DoctorCheck(
            "graphrag_entity_memory_ready", "pass", "ok", {"recommended_commands": []}
        ),
    )

    failed = doctor.check_rag_readiness()

    assert failed.status == "fail"
    assert failed.message == "rag_index_ready=fail; graphrag_entity_memory_ready=pass"


def test_environment_profile_passes_without_explicit_profile(monkeypatch):
    monkeypatch.delenv("SIDAR_ENV", raising=False)

    check = doctor.check_environment_profile()

    assert check.status == "pass"
    assert "profile is not set" in check.message


def test_environment_profile_warns_without_profile_or_template(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "BASE_DIR", tmp_path)
    monkeypatch.setenv("SIDAR_ENV", "staging")

    check = doctor.check_environment_profile()

    assert check.status == "warn"
    assert "no .env.staging or .env.staging.example" in check.message


def test_environment_profile_warns_when_development_file_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("SIDAR_ENV", "development")
    monkeypatch.setattr(doctor, "BASE_DIR", tmp_path)
    (tmp_path / ".env.development.example").write_text("SIDAR_ENV=development\n", encoding="utf-8")

    check = doctor.check_environment_profile()

    assert check.status == "warn"
    assert ".env.development is missing" in check.message
    assert (
        "uv run python -m scripts.bootstrap_env --profile development"
        in check.details["recommended_commands"]
    )


def test_environment_profile_passes_when_profile_file_exists_or_test_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "BASE_DIR", tmp_path)
    monkeypatch.setenv("SIDAR_ENV", "development")
    (tmp_path / ".env.development").write_text(
        "SIDAR_ENV=development\nPOSTGRES_DB=sidar_development\n", encoding="utf-8"
    )

    present = doctor.check_environment_profile()

    assert present.status == "pass"
    assert present.details["profile_env_exists"] is True

    monkeypatch.setenv("SIDAR_ENV", "test")
    test_profile = doctor.check_environment_profile()

    assert test_profile.status == "pass"
    assert "test fixtures" in test_profile.message


def test_environment_profile_warns_when_development_database_is_not_isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "BASE_DIR", tmp_path)
    monkeypatch.setenv("SIDAR_ENV", "development")
    (tmp_path / ".env.development").write_text(
        "SIDAR_ENV=development\nPOSTGRES_DB=sidar\n", encoding="utf-8"
    )

    check = doctor.check_environment_profile()

    assert check.status == "warn"
    assert "not isolated" in check.message
    assert check.details["profile_postgres_db"] == "sidar"
    assert "--force" in check.details["recommended_commands"][0]


def test_docker_image_exists_local_returns_false_without_docker(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)

    assert doctor._docker_image_exists_local("sidar:latest") is False


def test_docker_image_exists_local_uses_resolved_binary(monkeypatch):
    captured = {}

    def _run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(doctor.subprocess, "run", _run)

    assert doctor._docker_image_exists_local("sidar:latest") is True
    assert captured["command"] == ["/usr/bin/docker", "image", "inspect", "sidar:latest"]
    assert captured["kwargs"]["cwd"] == str(doctor.BASE_DIR)


def test_docker_image_exists_local_handles_empty_image_and_runtime_error(monkeypatch):
    assert doctor._docker_image_exists_local("") is False

    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(
        doctor.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("boom"))
    )

    assert doctor._docker_image_exists_local("sidar:latest") is False


def test_gpu_memory_config_warns_for_high_budget_profile_drift_and_missing_image(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(Config, "CODING_MODEL", "other-model")
    monkeypatch.setattr(Config, "ACCESS_LEVEL", "full")
    monkeypatch.setattr(Config, "USE_GPU", False)
    monkeypatch.setattr(Config, "DOCKER_IMAGE", "sidar-gpu:latest")
    monkeypatch.setattr(Config, "DOCKER_TEST_IMAGE", "sidar:latest")
    monkeypatch.setattr(Config, "GPU_MEMORY_FRACTION", 0.8)
    monkeypatch.setattr(Config, "LLM_GPU_MEMORY_FRACTION", 0.6)
    monkeypatch.setattr(Config, "RAG_GPU_MEMORY_FRACTION", 0.36)
    monkeypatch.setattr(doctor, "_docker_image_exists_local", lambda image: False)

    check = doctor.check_gpu_memory_config()

    assert check.status == "warn"
    assert "VRAM fractions are very high" in check.message
    assert "differs from the Sidar standard" in check.message
    assert "runtime is CPU mode" in check.message
    assert "access level is not sandbox" in check.message
    assert "local Docker daemon cannot find" in check.details["docker_test_image_hint"]
    assert "docker build -t sidar:latest ." in check.details["recommended_commands"]


def test_gpu_memory_config_warns_when_budget_is_normalized(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(Config, "CODING_MODEL", "qwen2.5-coder:7b")
    monkeypatch.setattr(Config, "ACCESS_LEVEL", "sandbox")
    monkeypatch.setattr(Config, "GPU_MEMORY_FRACTION", 0.9)
    monkeypatch.setattr(Config, "LLM_GPU_MEMORY_FRACTION", 0.9)
    monkeypatch.setattr(Config, "RAG_GPU_MEMORY_FRACTION", 0.4)

    check = doctor.check_gpu_memory_config()

    assert check.status == "warn"
    assert check.details["normalized"] is True
    assert check.details["effective_gpu_memory_fraction"] == pytest.approx(0.8)
    assert "normalize" in check.message


def test_gpu_memory_config_confirms_standard_local_model(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(Config, "CODING_MODEL", "qwen2.5-coder:7b")
    monkeypatch.setattr(Config, "ACCESS_LEVEL", "sandbox")
    monkeypatch.setattr(Config, "GPU_MEMORY_FRACTION", 0.8)
    monkeypatch.setattr(Config, "LLM_GPU_MEMORY_FRACTION", 0.6)
    monkeypatch.setattr(Config, "RAG_GPU_MEMORY_FRACTION", 0.3)
    monkeypatch.setattr(Config, "DOCKER_TEST_IMAGE", "sidar:latest")

    check = doctor.check_gpu_memory_config()

    assert check.status == "pass"
    assert check.details["coding_model"] == "qwen2.5-coder:7b"
    assert check.details["access_level"] == "sandbox"
    assert check.details["total_gpu_memory_fraction"] == pytest.approx(0.9)


def test_gpu_memory_config_warns_for_default_slim_test_image(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(Config, "CODING_MODEL", "qwen2.5-coder:7b")
    monkeypatch.setattr(Config, "ACCESS_LEVEL", "sandbox")
    monkeypatch.setattr(Config, "GPU_MEMORY_FRACTION", 0.8)
    monkeypatch.setattr(Config, "LLM_GPU_MEMORY_FRACTION", 0.6)
    monkeypatch.setattr(Config, "RAG_GPU_MEMORY_FRACTION", 0.3)
    monkeypatch.setattr(Config, "DOCKER_TEST_IMAGE", "python:3.11-slim")

    check = doctor.check_gpu_memory_config()

    assert check.status == "warn"
    assert "DOCKER_TEST_IMAGE currently points to python:3.11-slim" in check.message
    assert "docker build -t sidar:latest ." in check.details["recommended_commands"]
    assert "DOCKER_TEST_IMAGE=sidar:latest" in check.details["recommended_commands"][-1]


def test_migrations_fail_when_no_revisions(monkeypatch, tmp_path):
    versions = tmp_path / "migrations" / "versions"
    versions.mkdir(parents=True)
    monkeypatch.setattr(doctor, "migrations_path", lambda: tmp_path / "migrations")

    check = doctor.check_migrations()

    assert check.status == "fail"
    assert check.message == "no Alembic migration revisions found"


def test_parse_migration_revisions_ignores_files_without_revision(monkeypatch, tmp_path):
    versions = tmp_path / "migrations" / "versions"
    versions.mkdir(parents=True)
    (versions / "README.py").write_text("# helper without alembic metadata\n", encoding="utf-8")
    (versions / "0001.py").write_text("revision = 'base'\ndown_revision = None\n", encoding="utf-8")
    monkeypatch.setattr(doctor, "migrations_path", lambda: tmp_path / "migrations")

    revisions, down_revisions = doctor._parse_migration_revisions()

    assert revisions == ["base"]
    assert down_revisions == []


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


def test_gpu_check_falls_back_to_torch_when_nvidia_smi_is_unhealthy(monkeypatch):
    monkeypatch.setattr(
        doctor.shutil,
        "which",
        lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None,
    )
    monkeypatch.setattr(doctor, "_run_command", lambda cmd, timeout=20: (1, "driver offline"))
    original_import = __import__

    class Cuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def device_count():
            return 1

        @staticmethod
        def get_device_name(index):
            return f"Fallback-GPU-{index}"

    def torch_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "torch":
            return type("TorchModule", (), {"cuda": Cuda})()
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", torch_import)

    check = doctor.check_gpu()

    assert check.status == "pass"
    assert check.details["source"] == "torch"
    assert check.details["devices"] == ["Fallback-GPU-0"]
    assert check.details["run_gpu_stress"] is True


def test_gpu_check_reports_warn_when_torch_cuda_is_unavailable(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    original_import = __import__

    class Cuda:
        @staticmethod
        def is_available():
            return False

    def torch_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "torch":
            return type("TorchModule", (), {"cuda": Cuda})()
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", torch_import)

    check = doctor.check_gpu()

    assert check.status == "warn"
    assert check.details == {"detected": False, "run_gpu_stress": False}


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


def test_database_env_reports_database_url_override_source(monkeypatch, tmp_path):
    password = "a" * 24
    database_env = tmp_path / ".env.development"
    database_env.write_text(
        f"DATABASE_URL=postgresql://sidar:{'b' * 24}@localhost:5432/sidar\n",
        encoding="utf-8",
    )
    secret_env = tmp_path / "keys.env"
    secret_env.write_text(f"POSTGRES_PASSWORD={password}\n", encoding="utf-8")

    monkeypatch.setenv("POSTGRES_USER", "sidar")
    monkeypatch.setenv("POSTGRES_PASSWORD", password)
    monkeypatch.setenv("POSTGRES_DB", "sidar")
    monkeypatch.setenv("DATABASE_URL", f"postgresql://sidar:{'b' * 24}@localhost:5432/sidar")
    monkeypatch.delenv("SIDAR_CONTAINER_DATABASE_URL", raising=False)

    monkeypatch.setattr(
        doctor,
        "_dotenv_source_report",
        lambda _keys: {
            "sources": {
                "DATABASE_URL": {
                    "label": "environment:development",
                    "path": str(database_env),
                    "override": "True",
                },
                "POSTGRES_PASSWORD": {
                    "label": "secret:SIDAR_KEYS_FILE",
                    "path": str(secret_env),
                    "override": "True",
                },
            },
            "definitions": {
                "DATABASE_URL": [
                    {
                        "label": "environment:development",
                        "path": str(database_env),
                        "override": "True",
                    }
                ],
                "SIDAR_CONTAINER_DATABASE_URL": [],
                "POSTGRES_PASSWORD": [
                    {
                        "label": "secret:SIDAR_KEYS_FILE",
                        "path": str(secret_env),
                        "override": "True",
                    }
                ],
            },
        },
    )

    check = doctor.check_database_env()

    assert check.status == "fail"
    assert "DATABASE_URL password does not match POSTGRES_PASSWORD" in check.message
    assert f"DATABASE_URL is overridden in {database_env}" in check.message
    assert check.details["database_url_source"] == str(database_env)
    assert check.details["postgres_password_source"] == str(secret_env)


def test_check_pgvector_ready_fails_when_extension_missing(monkeypatch):
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "pgvector")
    monkeypatch.setenv("DATABASE_URL", "postgresql://sidar:" + "a" * 24 + "@localhost:5432/sidar")

    async def _fake_probe(database_url, timeout_seconds=0.25):
        return {"select_1": True, "pgvector_extension_installed": False}

    monkeypatch.setattr(doctor, "_probe_postgres_connectivity", _fake_probe)

    check = doctor.check_pgvector_ready()

    assert check.status == "fail"
    assert "extension is not installed" in check.message
    assert check.details["required"] is True
    assert (
        check.details["auto_fix"] == "docker compose pull postgres && docker compose up -d postgres"
    )


def test_prometheus_runtime_warns_when_optional_dependency_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda _name: None)

    check = doctor.check_prometheus_runtime()

    assert check.status == "warn"
    assert "not installed" in check.message


def test_dotenv_helpers_tolerate_unreadable_file_and_config_import_failure(
    monkeypatch, tmp_path
) -> None:
    import builtins

    unreadable = tmp_path / "missing.env"
    assert doctor._parse_env_file_values(unreadable) == {}

    original_import = builtins.__import__

    def _import(name, *args, **kwargs):
        if name == "config":
            raise ImportError("config unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)
    assert doctor._dotenv_source_report(("DATABASE_URL",)) == {
        "sources": {},
        "definitions": {"DATABASE_URL": []},
    }


def test_database_connectivity_skips_non_postgres_and_warns_when_asyncpg_is_missing(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///sidar.db")
    assert doctor.check_database_connectivity().status == "pass"

    monkeypatch.setenv("DATABASE_URL", "postgresql://sidar:secret@localhost/sidar")

    def _raise_missing_asyncpg(coro):
        coro.close()
        raise ModuleNotFoundError("asyncpg")

    monkeypatch.setattr(doctor, "_run_coro_sync", _raise_missing_asyncpg)
    check = doctor.check_database_connectivity()

    assert check.status == "warn"
    assert "asyncpg is unavailable" in check.message


@pytest.mark.asyncio
async def test_run_coro_sync_reraises_background_probe_failure() -> None:
    async def _failure() -> None:
        raise RuntimeError("probe failed")

    with pytest.raises(RuntimeError, match="probe failed"):
        doctor._run_coro_sync(_failure())


def test_rag_readiness_warns_when_graph_disabled_and_resolves_relative_path(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(doctor, "BASE_DIR", tmp_path)
    monkeypatch.setenv("RAG_DIR", str(tmp_path / "rag"))
    monkeypatch.setenv("ENABLE_GRAPH_RAG", "false")

    state = doctor._rag_readiness_state()
    assert "GraphRAG is disabled by ENABLE_GRAPH_RAG=false" in state["warnings"]

    monkeypatch.setattr(
        doctor,
        "_rag_readiness_state",
        lambda: {
            "details": {"rag_dir": "relative-rag"},
            "blockers": [],
            "warnings": [],
            "document_count": 0,
            "entity_memory_empty": False,
        },
    )
    check = doctor.check_rag_index_ready()

    assert check.details["index_path"] == str(tmp_path / "relative-rag" / "index.json")


def test_read_env_file_assignments_handles_missing_comments_and_empty_export_key(tmp_path) -> None:
    missing = tmp_path / "missing.env"
    assert doctor._read_env_file_assignments(missing) == {}

    env_file = tmp_path / ".env"
    env_file.write_text("# comment\ninvalid-line\nexport VALID=value\n", encoding="utf-8")

    assert doctor._read_env_file_assignments(env_file) == {"VALID": "value"}


def test_redact_exception_text_without_database_password_keeps_safe_text() -> None:
    assert (
        doctor._redact_exception_text(
            RuntimeError("connection refused"), database_url="postgresql://localhost/sidar"
        )
        == "connection refused"
    )


def test_rag_readiness_state_handles_pgvector_without_database_url(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "pgvector")
    monkeypatch.setenv("RAG_DIR", str(tmp_path / "rag"))

    state = doctor._rag_readiness_state()

    assert state["details"]["rag_backend_probe_path"] == "pgvector_database_env"
    assert "pgvector" in state["details"]["rag_backend_smoke_scope"]
    assert state["details"]["database_env_status"] == "fail"
    assert state["details"]["blocked_by"] == "database_env"


def test_rag_readiness_state_records_backend_probe_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RAG_DIR", str(tmp_path / "rag"))

    monkeypatch.setenv("RAG_VECTOR_BACKEND", "chroma")
    chroma_state = doctor._rag_readiness_state()
    assert chroma_state["details"]["rag_backend_probe_path"] == "chromadb_local_index"
    assert "ChromaDB/local index" in chroma_state["details"]["rag_backend_smoke_scope"]

    monkeypatch.setenv("RAG_VECTOR_BACKEND", "bm25")
    bm25_state = doctor._rag_readiness_state()
    assert bm25_state["details"]["rag_backend_probe_path"] == "bm25_keyword_fallback"
    assert bm25_state["details"]["rag_backend_smoke_scope"] == "BM25/keyword fallback only"


def test_ensure_rag_index_placeholder_preserves_existing_index(tmp_path) -> None:
    rag_dir = tmp_path / "rag"
    rag_dir.mkdir()
    index_path = rag_dir / "index.json"
    index_path.write_text('{"existing": true}', encoding="utf-8")

    assert doctor._ensure_rag_index_placeholder(rag_dir) == index_path
    assert index_path.read_text(encoding="utf-8") == '{"existing": true}'


def test_rag_index_ready_healthy_without_entity_warning(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        doctor,
        "_rag_readiness_state",
        lambda: {
            "details": {"rag_dir": str(tmp_path), "index_exists": True},
            "blockers": [],
            "warnings": [],
            "document_count": 1,
            "entity_memory_empty": False,
        },
    )

    check = doctor.check_rag_index_ready()

    assert check.status == "pass"
    assert "graphrag_entity_memory_warning" not in check.details


def test_graphrag_ready_handles_failed_store_probe(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        doctor,
        "_rag_readiness_state",
        lambda: {
            "details": {
                "rag_dir": str(tmp_path),
                "graph_rag_enabled": True,
                "entity_node_count": 1,
            },
            "warnings": [],
            "entity_memory_empty": False,
        },
    )
    monkeypatch.setattr(
        doctor, "_query_entity_graph_counts_from_store", lambda _rag_dir: {"ok": False}
    )

    check = doctor.check_graphrag_entity_memory_ready()

    assert check.status == "pass"
    assert check.details["entity_store_probe"] == {"ok": False}


def test_rag_readiness_aggregate_reports_warn_and_keeps_scalar_auto_fix(monkeypatch) -> None:
    monkeypatch.setattr(
        doctor,
        "_rag_readiness_state",
        lambda: {"details": {"document_count": 0, "index_exists": True}},
    )
    monkeypatch.setattr(
        doctor,
        "check_rag_index_ready",
        lambda: DoctorCheck(
            "rag_index_ready", "warn", "empty", {"auto_fix": "seed", "recommended_commands": []}
        ),
    )
    monkeypatch.setattr(
        doctor,
        "check_graphrag_entity_memory_ready",
        lambda: DoctorCheck("graph", "pass", "ok", {"recommended_commands": []}),
    )

    check = doctor.check_rag_readiness()

    assert check.status == "warn"
    assert check.details["auto_fix"] == "seed"


def test_gpu_memory_config_accepts_custom_test_image_without_missing_sidar_hint(
    monkeypatch,
) -> None:
    from config import Config

    monkeypatch.setattr(Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(Config, "CODING_MODEL", "qwen2.5-coder:7b")
    monkeypatch.setattr(Config, "ACCESS_LEVEL", "sandbox")
    monkeypatch.setattr(Config, "USE_GPU", False)
    monkeypatch.setattr(Config, "DOCKER_IMAGE", "")
    monkeypatch.setattr(Config, "DOCKER_TEST_IMAGE", "custom:test")
    monkeypatch.setattr(Config, "GPU_MEMORY_FRACTION", 0.8)
    monkeypatch.setattr(Config, "LLM_GPU_MEMORY_FRACTION", 0.6)
    monkeypatch.setattr(Config, "RAG_GPU_MEMORY_FRACTION", 0.3)
    monkeypatch.setattr(doctor, "_docker_image_exists_local", lambda _image: False)

    check = doctor.check_gpu_memory_config()

    assert check.status == "pass"
    assert "docker_test_image_hint" not in check.details


def test_rag_readiness_aggregate_reports_pass_when_split_checks_pass(monkeypatch) -> None:
    monkeypatch.setattr(
        doctor,
        "_rag_readiness_state",
        lambda: {"details": {"document_count": 1, "index_exists": True}},
    )
    monkeypatch.setattr(
        doctor,
        "check_rag_index_ready",
        lambda: DoctorCheck("rag_index_ready", "pass", "ok", {"recommended_commands": []}),
    )
    monkeypatch.setattr(
        doctor,
        "check_graphrag_entity_memory_ready",
        lambda: DoctorCheck("graph", "pass", "ok", {"recommended_commands": []}),
    )

    check = doctor.check_rag_readiness()

    assert check.status == "pass"
    assert check.message == "rag_index_ready=pass; graphrag_entity_memory_ready=pass"


def test_doctor_check_contract_rejects_invalid_status() -> None:
    bad = DoctorCheck("bad", "unknown", "message")
    with pytest.raises(ValueError, match="status must be one of"):
        doctor.validate_doctor_check_contract(bad)


def test_doctor_check_contract_rejects_missing_required_fields() -> None:
    def valid_as_dict() -> dict[str, object]:
        return {}

    with pytest.raises(TypeError, match="non-empty string name"):
        doctor.validate_doctor_check_contract(
            types.SimpleNamespace(
                name=" ", status="pass", message="ok", details={}, as_dict=valid_as_dict
            )
        )
    with pytest.raises(TypeError, match="string message"):
        doctor.validate_doctor_check_contract(
            types.SimpleNamespace(
                name="x", status="pass", message=None, details={}, as_dict=valid_as_dict
            )
        )
    with pytest.raises(TypeError, match="details must be a dict"):
        doctor.validate_doctor_check_contract(
            types.SimpleNamespace(
                name="x", status="pass", message="ok", details=[], as_dict=valid_as_dict
            )
        )
    with pytest.raises(TypeError, match="as_dict"):
        doctor.validate_doctor_check_contract(
            types.SimpleNamespace(name="x", status="pass", message="ok", details={})
        )


def test_validate_auto_fix_command_allows_known_commands_and_rejects_injection() -> None:
    assert doctor.validate_auto_fix_command(
        "uv run python -m scripts.sync_database_passwords --remove-explicit-urls"
    ) == ["uv", "run", "python", "-m", "scripts.sync_database_passwords", "--remove-explicit-urls"]
    assert doctor.validate_auto_fix_command("docker compose up -d postgres") == [
        "docker",
        "compose",
        "up",
        "-d",
        "postgres",
    ]
    with pytest.raises(ValueError, match="not allowlisted|not safe"):
        doctor.validate_auto_fix_command("uv run python -m scripts.seed_rag; rm -rf / --force")
    with pytest.raises(ValueError, match="not allowlisted"):
        doctor.validate_auto_fix_command("bash -lc 'echo pwnd'")
    with pytest.raises(ValueError, match="empty"):
        doctor.validate_auto_fix_command("   ")
    with pytest.raises(ValueError, match="not safe"):
        doctor.validate_auto_fix_command("uv run python -m scripts.seed_rag bad;arg")


def test_doctor_as_dict_masks_passwords_in_nested_details() -> None:
    check = DoctorCheck(
        "db",
        "warn",
        "password=secret-token postgresql://sidar:secret-token@localhost/sidar",
        {
            "error": "password=secret-token postgresql://sidar:secret-token@localhost/sidar",
            "nested": ["api_key=abc12345", {"token": "token=my-token"}],
            "tuple_secret": ("password=tuple-secret",),
        },
    )

    payload = check.as_dict()
    serialized = json.dumps(payload, ensure_ascii=False)

    assert "secret-token" not in serialized
    assert "abc12345" not in serialized
    assert "my-token" not in serialized
    assert "tuple-secret" not in serialized
    assert "postgresql://sidar:***@localhost/sidar" in serialized

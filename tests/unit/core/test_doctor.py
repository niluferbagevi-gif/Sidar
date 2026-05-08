from __future__ import annotations

import json

from core import doctor
from core.doctor import DoctorCheck


def test_run_doctor_report_writes_json_and_aggregates_warn(monkeypatch, tmp_path):
    checks = [
        DoctorCheck("uv", "pass", "ok"),
        DoctorCheck("gpu", "warn", "no gpu", {"run_gpu_stress": False}),
    ]
    monkeypatch.setattr(doctor, "check_uv", lambda: checks[0])
    monkeypatch.setattr(doctor, "check_database_env", lambda: DoctorCheck("db", "pass", "ok"))
    monkeypatch.setattr(doctor, "check_migrations", lambda: DoctorCheck("migrations", "pass", "ok"))
    monkeypatch.setattr(doctor, "check_agent_catalog", lambda: DoctorCheck("catalog", "pass", "ok"))
    monkeypatch.setattr(doctor, "check_supervisor_routing", lambda: DoctorCheck("routing", "pass", "ok"))
    monkeypatch.setattr(doctor, "check_websocket_routes", lambda: DoctorCheck("ws", "pass", "ok"))
    monkeypatch.setattr(doctor, "check_gpu", lambda: checks[1])
    monkeypatch.setattr(doctor, "check_model", lambda smoke=True: DoctorCheck("model", "pass", "ok"))

    output = tmp_path / "doctor.json"
    report = doctor.run_doctor_report(output_path=output)

    assert report["overall_status"] == "warn"
    assert report["run_gpu_stress"] is False
    assert json.loads(output.read_text(encoding="utf-8"))["overall_status"] == "warn"


def test_gpu_check_requests_stress_when_nvidia_smi_detected(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None)
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
    (versions / "0001_first.py").write_text("revision = 'a'\ndown_revision = None\n", encoding="utf-8")
    (versions / "0002_second.py").write_text("revision = 'b'\ndown_revision = 'a'\n", encoding="utf-8")
    monkeypatch.setattr(doctor, "migrations_path", lambda: tmp_path / "migrations")

    revisions, down_revisions = doctor._parse_migration_revisions()

    assert revisions == ["a", "b"]
    assert down_revisions == ["a"]

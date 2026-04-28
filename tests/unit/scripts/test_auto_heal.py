from __future__ import annotations

import json
from pathlib import Path

import scripts.auto_heal as auto_heal


def test_auto_heal_returns_1_for_missing_log(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["auto_heal.py", "--log-file", "artifacts/missing.log"],
    )
    assert auto_heal.main() == 1


def test_auto_heal_returns_0_on_success(monkeypatch, tmp_path: Path):
    log_file = tmp_path / "mypy_errors.log"
    log_file.write_text(
        "core/x.py:1: error: Incompatible types in assignment [assignment]",
        encoding="utf-8",
    )
    output_file = tmp_path / "heal_out.json"

    async def _fake_run_local_remediation_loop(**kwargs):
        Path(kwargs["output_path"]).write_text(
            json.dumps({"status": "ok", "execution": {"status": "applied"}}),
            encoding="utf-8",
        )
        return {"status": "ok", "execution": {"status": "applied"}}

    monkeypatch.setattr(auto_heal, "run_local_remediation_loop", _fake_run_local_remediation_loop)
    monkeypatch.setattr(
        "sys.argv",
        [
            "auto_heal.py",
            "--log-file",
            str(log_file),
            "--stage",
            "static_mypy",
            "--command",
            "uv run mypy .",
            "--output",
            str(output_file),
        ],
    )
    assert auto_heal.main() == 0

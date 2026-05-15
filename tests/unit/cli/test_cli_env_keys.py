from __future__ import annotations

import sys

import cli


def test_parse_init_command_creates_env_by_default(monkeypatch, tmp_path):
    calls: list[dict[str, object]] = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(cli, "_run_env_keys_command", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sidar",
            "init",
            "--env",
            str(tmp_path / ".env"),
            "--example",
            str(tmp_path / ".env.example"),
        ],
    )

    assert cli._parse_env_keys_command("init") == 0
    assert calls == [
        {
            "env_path": str(tmp_path / ".env"),
            "example_path": str(tmp_path / ".env.example"),
            "force": False,
            "create": True,
        }
    ]


def test_parse_generate_keys_supports_force_and_no_create(monkeypatch, tmp_path):
    calls: list[dict[str, object]] = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(cli, "_run_env_keys_command", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sidar",
            "generate-keys",
            "--env",
            str(tmp_path / ".env"),
            "--force",
            "--no-create",
        ],
    )

    assert cli._parse_env_keys_command("generate-keys") == 0
    assert calls == [
        {
            "env_path": str(tmp_path / ".env"),
            "example_path": ".env.example",
            "force": True,
            "create": False,
        }
    ]

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.integration
@pytest.mark.parametrize(
    ("provider", "provider_key", "provider_value"),
    [
        ("openai", "OPENAI_API_KEY", "sk-from-explicit-dotenv"),
        ("gemini", "GEMINI_API_KEY", "gemini-from-explicit-dotenv"),
        ("anthropic", "ANTHROPIC_API_KEY", "anthropic-from-explicit-dotenv"),
        ("litellm", "LITELLM_GATEWAY_URL", "https://litellm.example.test"),
    ],
)
def test_production_explicit_dotenv_satisfies_critical_keys_when_sidar_keys_file_missing(
    tmp_path: Path,
    provider: str,
    provider_key: str,
    provider_value: str,
) -> None:
    """Production config must not rely on SIDAR_KEYS_FILE when explicit dotenv has secrets."""

    explicit_env = tmp_path / "production.env"
    missing_keys_file = tmp_path / "missing-sidar-keys.env"
    explicit_env.write_text(
        "\n".join(
            [
                "SIDAR_ENV=production",
                "JWT_SECRET_KEY=jwt-from-explicit-dotenv",
                "API_KEY=api-from-explicit-dotenv",
                "MEMORY_ENCRYPTION_KEY=memory-key-from-explicit-dotenv",
                f"AI_PROVIDER={provider}",
                f"{provider_key}={provider_value}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import json
import config

print(json.dumps({
    "missing": config.Config.get_missing_critical_runtime_keys(),
    "provider": config.Config.AI_PROVIDER,
    "provider_value": getattr(config.Config, "PROVIDER_PLACEHOLDER"),
    "report": config.get_dotenv_load_report(),
}, ensure_ascii=False))
""".replace("PROVIDER_PLACEHOLDER", provider_key),
        ],
        check=True,
        capture_output=True,
        env={
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(Path.cwd()),
            "SIDAR_SKIP_DEFAULT_DOTENV": "1",
            "DOTENV_FILE": str(explicit_env),
            "SIDAR_KEYS_FILE": str(missing_keys_file),
        },
        text=True,
    )

    payload = json.loads(probe.stdout.strip().splitlines()[-1])
    assert payload["missing"] == []
    assert payload["provider"] == provider
    assert payload["provider_value"] == provider_value

    report_by_label = {event["label"]: event for event in payload["report"]}
    assert report_by_label["explicit:DOTENV_FILE"]["loaded"] is True
    assert report_by_label["secret:SIDAR_KEYS_FILE"]["loaded"] is False
    assert report_by_label["secret:SIDAR_KEYS_FILE"]["reason"] == "missing"


@pytest.mark.integration
def test_reload_dotenv_chain_applies_full_five_layer_precedence(
    monkeypatch, tmp_path: Path
) -> None:
    """Exercise base -> advanced -> environment -> explicit -> secret dotenv precedence."""

    import config

    (tmp_path / ".env").write_text(
        "CHAIN_VALUE=base\nSIDAR_ENV=development\nBASE_ONLY=base-only\n", encoding="utf-8"
    )
    (tmp_path / ".env.advanced").write_text(
        "CHAIN_VALUE=advanced\nADVANCED_ONLY=advanced-only\n", encoding="utf-8"
    )
    (tmp_path / ".env.development").write_text(
        "CHAIN_VALUE=environment\nENV_ONLY=environment-only\n", encoding="utf-8"
    )
    explicit_env = tmp_path / "explicit.env"
    explicit_env.write_text("CHAIN_VALUE=explicit\nEXPLICIT_ONLY=explicit-only\n", encoding="utf-8")
    secret_env = tmp_path / "secret.env"
    secret_env.write_text("CHAIN_VALUE=secret\nSECRET_ONLY=secret-only\n", encoding="utf-8")

    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    for key in (
        "CHAIN_VALUE",
        "BASE_ONLY",
        "ADVANCED_ONLY",
        "ENV_ONLY",
        "EXPLICIT_ONLY",
        "SECRET_ONLY",
        "SIDAR_ENV",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DOTENV_FILE", str(explicit_env))
    monkeypatch.setenv("SIDAR_KEYS_FILE", str(secret_env))
    monkeypatch.delenv("SIDAR_SKIP_DEFAULT_DOTENV", raising=False)

    config._reload_dotenv_chain()

    assert os.environ["CHAIN_VALUE"] == "secret"
    assert os.environ["BASE_ONLY"] == "base-only"
    assert os.environ["ADVANCED_ONLY"] == "advanced-only"
    assert os.environ["ENV_ONLY"] == "environment-only"
    assert os.environ["EXPLICIT_ONLY"] == "explicit-only"
    assert os.environ["SECRET_ONLY"] == "secret-only"
    loaded_labels = [event["label"] for event in config.get_dotenv_load_report() if event["loaded"]]
    assert loaded_labels == [
        "base",
        "advanced",
        "environment:development",
        "explicit:DOTENV_FILE",
        "secret:SIDAR_KEYS_FILE",
    ]
    assert config.get_dotenv_key_source_report()["CHAIN_VALUE"]["label"] == "secret:SIDAR_KEYS_FILE"

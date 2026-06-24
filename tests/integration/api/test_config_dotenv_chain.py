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

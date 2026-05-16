from __future__ import annotations

import subprocess
from pathlib import Path


def _mask_function_source() -> str:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
    start = script.index("mask_install_log_stream() {")
    end = script.index("\n}\n\nSCRIPT_DIR=", start) + len("\n}\n")
    return script[start:end]


def test_install_log_masking_redacts_common_secret_shapes() -> None:
    shell = f"""
{_mask_function_source()}
printf '%s\n' \\
  'DATABASE_URL=postgresql+asyncpg://sidar:supersecret@localhost:5432/sidar' \\
  'generated_password=generated-secret-123' \\
  '{{"API_KEY": "api-secret-123"}}' \\
  'Authorization: Bearer bearer-secret-123' \\
  'sed -i s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=postgres-secret-123| .env' \\
  | mask_install_log_stream
"""

    result = subprocess.run(["bash", "-c", shell], check=True, text=True, capture_output=True)

    assert "supersecret" not in result.stdout
    assert "generated-secret-123" not in result.stdout
    assert "api-secret-123" not in result.stdout
    assert "bearer-secret-123" not in result.stdout
    assert "postgres-secret-123" not in result.stdout
    assert "DATABASE_URL=****" in result.stdout
    assert "generated_password=****" in result.stdout
    assert '"API_KEY": "****"' in result.stdout
    assert "Authorization: Bearer ****" in result.stdout
    assert "POSTGRES_PASSWORD=****" in result.stdout

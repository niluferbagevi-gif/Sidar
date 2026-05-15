from __future__ import annotations

import base64

from env_keys import initialize_env_file


def _env_values(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_initialize_env_file_copies_example_and_generates_local_secrets(tmp_path):
    example = tmp_path / ".env.example"
    env = tmp_path / ".env"
    example.write_text(
        "POSTGRES_PASSWORD=\n"
        "SIDAR_API_KEY=\n"
        "SIDAR_JWT_SECRET_KEY=\n"
        "SIDAR_MEMORY_ENCRYPTION_KEY=\n"
        "AUTONOMY_WEBHOOK_SECRET=\n"
        "SWARM_FEDERATION_SHARED_SECRET=\n"
        "GITHUB_WEBHOOK_SECRET=\n"
        "GRAFANA_ADMIN_PASSWORD=admin\n"
        "SIDAR_METRICS_TOKEN=\n"
        "OPENAI_API_KEY=\n",
        encoding="utf-8",
    )

    result = initialize_env_file(env_path=env, example_path=example)
    values = _env_values(env)

    assert result.created is True
    for key in (
        "POSTGRES_PASSWORD",
        "SIDAR_API_KEY",
        "SIDAR_JWT_SECRET_KEY",
        "SIDAR_MEMORY_ENCRYPTION_KEY",
        "AUTONOMY_WEBHOOK_SECRET",
        "SWARM_FEDERATION_SHARED_SECRET",
        "GITHUB_WEBHOOK_SECRET",
        "GRAFANA_ADMIN_PASSWORD",
        "SIDAR_METRICS_TOKEN",
    ):
        assert key in result.updated
        assert len(values[key]) >= 24
    assert len(base64.urlsafe_b64decode(values["SIDAR_MEMORY_ENCRYPTION_KEY"])) == 32
    assert values["OPENAI_API_KEY"] == ""


def test_initialize_env_file_preserves_existing_strong_values_without_force(tmp_path):
    example = tmp_path / ".env.example"
    env = tmp_path / ".env"
    example.write_text("SIDAR_API_KEY=\n", encoding="utf-8")
    env.write_text(
        "SIDAR_API_KEY=existing-api-key-value-with-more-than-24-chars\n"
        "SIDAR_JWT_SECRET_KEY=\n",
        encoding="utf-8",
    )

    result = initialize_env_file(env_path=env, example_path=example)
    values = _env_values(env)

    assert "SIDAR_API_KEY" in result.skipped
    assert values["SIDAR_API_KEY"] == "existing-api-key-value-with-more-than-24-chars"
    assert values["SIDAR_JWT_SECRET_KEY"]


def test_initialize_env_file_force_rotates_existing_values(tmp_path):
    example = tmp_path / ".env.example"
    env = tmp_path / ".env"
    example.write_text("SIDAR_API_KEY=\n", encoding="utf-8")
    env.write_text("SIDAR_API_KEY=existing-api-key-value-with-more-than-24-chars\n", encoding="utf-8")

    result = initialize_env_file(env_path=env, example_path=example, force=True)
    values = _env_values(env)

    assert "SIDAR_API_KEY" in result.updated
    assert values["SIDAR_API_KEY"] != "existing-api-key-value-with-more-than-24-chars"


def test_initialize_env_file_copies_strong_legacy_alias_to_namespaced_key(tmp_path):
    example = tmp_path / ".env.example"
    env = tmp_path / ".env"
    example.write_text("SIDAR_API_KEY=\n", encoding="utf-8")
    env.write_text("API_KEY=legacy-api-key-value-with-more-than-24-chars\n", encoding="utf-8")

    result = initialize_env_file(env_path=env, example_path=example)
    values = _env_values(env)

    assert "SIDAR_API_KEY" in result.updated
    assert values["SIDAR_API_KEY"] == "legacy-api-key-value-with-more-than-24-chars"

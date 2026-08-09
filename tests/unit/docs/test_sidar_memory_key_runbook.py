from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_sidar_runbook_documents_memory_encryption_key_recovery_risks() -> None:
    """Ensure the operator runbook covers Fernet key persistence and loss risks."""
    sidar_doc = (REPO_ROOT / "docs" / "SIDAR.md").read_text(encoding="utf-8")

    assert "MEMORY_ENCRYPTION_KEY Runbook" in sidar_doc
    assert "yeniden üretilmedi" in sidar_doc
    assert "`.env` dosyasını siler" in sidar_doc
    assert "önceki anahtarla şifrelenmiş geçmiş hafıza kayıtları" in sidar_doc
    assert "kurtarılamaz" in sidar_doc


def test_production_secret_rotation_runbook_covers_all_shared_secrets() -> None:
    """Ensure production cutover documents rotation for every shared installer secret."""
    runbook = (REPO_ROOT / "docs" / "runbooks" / "production-secret-rotation.md").read_text(
        encoding="utf-8"
    )
    sidar_doc = (REPO_ROOT / "docs" / "SIDAR.md").read_text(encoding="utf-8")
    env_doc = (REPO_ROOT / "docs" / "ENVIRONMENT_CONFIGURATION.md").read_text(encoding="utf-8")

    required_keys = (
        "API_KEY",
        "JWT_SECRET_KEY",
        "MEMORY_ENCRYPTION_KEY",
        "AUTONOMY_WEBHOOK_SECRET",
        "SWARM_FEDERATION_SHARED_SECRET",
        "GITHUB_WEBHOOK_SECRET",
        "GRAFANA_ADMIN_PASSWORD",
        "METRICS_TOKEN",
    )
    for key in required_keys:
        assert key in runbook
        assert key in sidar_doc
        assert key in env_doc

    assert "Production secret rotation" in env_doc
    assert "docs/runbooks/production-secret-rotation.md" in sidar_doc
    assert "dev/test/local" in runbook
    assert "Fernet.generate_key" in runbook
    assert "python -m scripts.rotate_production_secrets" in runbook
    assert "--ack-memory-key-impact" in runbook

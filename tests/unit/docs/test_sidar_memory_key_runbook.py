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

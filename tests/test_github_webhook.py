from pathlib import Path


def test_config_exposes_github_webhook_secret_setting():
    src = Path("config.py").read_text(encoding="utf-8")
    assert "GITHUB_WEBHOOK_SECRET" in src
    assert 'os.getenv("GITHUB_WEBHOOK_SECRET", "")' in src


def test_web_server_has_webhook_endpoint_and_hmac_validation():
    src = Path("web_server.py").read_text(encoding="utf-8")
    assert '"/api/webhook"' in src
    assert "x_hub_signature_256" in src
    assert "hmac.new(secret, payload_body, hashlib.sha256).hexdigest()" in src
    assert "hmac.compare_digest(expected_signature, x_hub_signature_256)" in src
    assert "HTTPException(status_code=401" in src


def test_webhook_events_are_logged_into_memory_context():
    src = Path("web_server.py").read_text(encoding="utf-8")
    assert "[GITHUB BİLDİRİMİ]" in src
    assert "await asyncio.to_thread(agent.memory.add, \"user\", msg)" in src
    assert "GitHub bildirimini kayıtlarıma aldım" in src
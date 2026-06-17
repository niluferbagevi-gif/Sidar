import pytest
import os

@pytest.fixture(autouse=True)
def _isolate_webhook_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    # Remove webhook secret environment variables for test isolation
    for key in (
        "GITHUB_WEBHOOK_SECRET",
        "AUTONOMY_WEBHOOK_SECRET",
        "SIDAR_GITHUB_WEBHOOK_SECRET",
        "SIDAR_AUTONOMY_WEBHOOK_SECRET",
    ):
        monkeypatch.delenv(key, raising=False)
    try:
        import web_server
        monkeypatch.setattr(web_server.cfg, "GITHUB_WEBHOOK_SECRET", "", raising=False)
        monkeypatch.setattr(web_server.cfg, "AUTONOMY_WEBHOOK_SECRET", "", raising=False)
    except Exception:
        pass

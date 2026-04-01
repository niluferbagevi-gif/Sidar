import pytest


@pytest.fixture
def mock_config(monkeypatch):
    """config.Config için test bazlı güvenli varsayılanlar sağlar."""
    monkeypatch.setattr("config.Config.AI_PROVIDER", "ollama", raising=False)
    monkeypatch.setattr("config.Config.ACCESS_LEVEL", "full", raising=False)
    monkeypatch.setattr("config.Config.WEB_HOST", "0.0.0.0", raising=False)
    monkeypatch.setattr("config.Config.WEB_PORT", 7860, raising=False)
    monkeypatch.setattr("config.Config.BASE_DIR", ".", raising=False)
    monkeypatch.setattr("config.Config.initialize_directories", staticmethod(lambda: True), raising=False)

from pathlib import Path



def test_config_exposes_api_key_setting():
    src = Path("config.py").read_text(encoding="utf-8")
    assert 'API_KEY: str = os.getenv("API_KEY", "")' in src

def test_config_supports_sidar_env_override():
    src = Path("config.py").read_text(encoding="utf-8")
    assert 'sidar_env = os.getenv("SIDAR_ENV"' in src
    assert "load_dotenv(dotenv_path=specific_env_path, override=True)" in src


def test_config_has_github_webhook_secret():
    src = Path("config.py").read_text(encoding="utf-8")
    assert "GITHUB_WEBHOOK_SECRET" in src
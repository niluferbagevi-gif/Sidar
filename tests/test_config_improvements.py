from pathlib import Path



def test_config_exposes_api_key_setting():
    src = Path("config.py").read_text(encoding="utf-8")
    assert 'API_KEY: str = os.getenv("API_KEY", "")' in src
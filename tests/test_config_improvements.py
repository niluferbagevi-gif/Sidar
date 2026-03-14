# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

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

def test_config_has_zero_trust_docker_limits():
    src = Path("config.py").read_text(encoding="utf-8")
    assert 'DOCKER_RUNTIME: str = os.getenv("DOCKER_RUNTIME", "")' in src
    assert 'DOCKER_MEM_LIMIT: str = os.getenv("DOCKER_MEM_LIMIT", "256m")' in src
    assert 'DOCKER_NETWORK_DISABLED: bool = get_bool_env("DOCKER_NETWORK_DISABLED", True)' in src
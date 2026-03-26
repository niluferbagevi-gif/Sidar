from pathlib import Path


def test_config_supports_sidar_env_specific_dotenv_override():
    src = Path("config.py").read_text(encoding="utf-8")
    assert 'sidar_env = os.getenv("SIDAR_ENV", "").strip().lower()' in src
    assert 'specific_env_path = BASE_DIR / f".env.{sidar_env}"' in src
    assert 'load_dotenv(dotenv_path=specific_env_path, override=True)' in src


def test_config_loads_base_env_before_specific_profile():
    src = Path("config.py").read_text(encoding="utf-8")
    assert 'base_env_path = BASE_DIR / ".env"' in src
    assert 'if base_env_path.exists():' in src
    assert 'load_dotenv(dotenv_path=base_env_path)' in src
from pathlib import Path


def test_get_bool_env_handles_empty_and_whitespace_values():
    src = Path("config.py").read_text(encoding="utf-8")
    assert "raw_val = os.getenv(key)" in src
    assert "if raw_val is None or not raw_val.strip():" in src
    assert "val = raw_val.strip().lower()" in src
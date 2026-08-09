from __future__ import annotations

import stat

from scripts.update_dotenv_value import update_dotenv_value


def test_update_dotenv_value_clamps_existing_secret_file_mode(tmp_path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("TOKEN=old\n", encoding="utf-8")
    dotenv.chmod(0o644)

    update_dotenv_value(dotenv, "TOKEN", "new")

    assert dotenv.read_text(encoding="utf-8") == "TOKEN=new\n"
    assert stat.S_IMODE(dotenv.stat().st_mode) == 0o600


def test_update_dotenv_value_replaces_spaced_assignment_without_duplicate(tmp_path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("TOKEN = old\nOTHER=value\n", encoding="utf-8")

    update_dotenv_value(dotenv, "TOKEN", "new")

    assert dotenv.read_text(encoding="utf-8") == "TOKEN=new\nOTHER=value\n"

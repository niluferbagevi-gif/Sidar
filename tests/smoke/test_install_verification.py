import os
import sys


def test_dark_mode_assets_exist() -> None:
    assert os.path.exists("web_ui/style.css")
    with open("web_ui/style.css", "r", encoding="utf-8") as f:
        assert "background-color" in f.read()  # Dark mode class kontrolü


def test_python_version() -> None:
    assert sys.version_info >= (3, 11)

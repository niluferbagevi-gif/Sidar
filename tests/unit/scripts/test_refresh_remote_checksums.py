"""Remote installer checksum refresh contract tests."""

from __future__ import annotations

import runpy
from pathlib import Path

SCRIPT_PATH = Path("scripts/install_modules/refresh_remote_checksums.py")
CHECKSUM_FILE = Path("scripts/install_modules/remote_checksums.env")


def _managed_pins() -> tuple[object, ...]:
    namespace = runpy.run_path(str(SCRIPT_PATH), run_name="refresh_remote_checksums_test")
    return namespace["REMOTE_SCRIPT_PINS"]


def test_refresh_tool_manages_every_declared_remote_checksum() -> None:
    pins = _managed_pins()
    managed_names = {pin.env_var for pin in pins}
    declared_names = {
        line.partition(":=")[0].removeprefix(': "${')
        for line in CHECKSUM_FILE.read_text(encoding="utf-8").splitlines()
        if line.startswith(': "${') and "_INSTALL_SHA256:=" in line
    }

    assert (
        managed_names
        == declared_names
        == {
            "OLLAMA_INSTALL_SHA256",
            "UV_INSTALL_SHA256",
            "VOLTA_INSTALL_SHA256",
            "NVM_INSTALL_SHA256",
        }
    )


def test_node_installer_pins_match_runtime_download_urls() -> None:
    pins = {pin.env_var: pin.url for pin in _managed_pins()}
    system_phase = Path("scripts/install_modules/phases/03_system.sh").read_text(encoding="utf-8")

    assert pins["VOLTA_INSTALL_SHA256"] == "https://get.volta.sh"
    assert pins["NVM_INSTALL_SHA256"] == (
        "https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh"
    )
    assert pins["VOLTA_INSTALL_SHA256"] in system_phase
    assert pins["NVM_INSTALL_SHA256"] in system_phase

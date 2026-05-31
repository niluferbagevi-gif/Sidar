import os
import subprocess
import textwrap
from pathlib import Path


def test_repo_phase_copies_dark_mode_css_into_htmlcov_assets(tmp_path):
    repo_root = Path(os.getcwd())
    source_dark_css = repo_root / "assets" / "dark_mode.css"
    assert source_dark_css.exists(), (
        f"Smoke test precondition failed: missing source asset {source_dark_css}. "
        "Expected repository asset assets/dark_mode.css to exist."
    )

    script_dir = tmp_path / "sidar"
    assets_dir = script_dir / "assets"
    assets_dir.mkdir(parents=True)
    dark_css = assets_dir / "dark_mode.css"
    dark_css.write_text(source_dark_css.read_text(encoding="utf-8"), encoding="utf-8")

    repo_phase_script = textwrap.dedent(
        """
        set -euo pipefail
        source scripts/install_modules/phases/02_repo.sh

        step(){ :; }
        info(){ :; }
        warn(){ :; }
        ok(){ :; }
        install_system_dependencies(){ :; }
        sync_repo(){ :; }

        export SCRIPT_DIR="$1"
        sidar_phase_bootstrap_repo_system
        test -f "$SCRIPT_DIR/htmlcov/assets/dark_mode.css"
        test -f "$SCRIPT_DIR/artifacts/htmlcov/assets/dark_mode.css"
        cmp "$SCRIPT_DIR/assets/dark_mode.css" "$SCRIPT_DIR/htmlcov/assets/dark_mode.css"
        cmp "$SCRIPT_DIR/assets/dark_mode.css" "$SCRIPT_DIR/artifacts/htmlcov/assets/dark_mode.css"
        """
    )

    subprocess.run(
        ["bash", "-lc", repo_phase_script, "sidar-smoke", str(script_dir)],
        cwd=os.getcwd(),
        check=True,
    )

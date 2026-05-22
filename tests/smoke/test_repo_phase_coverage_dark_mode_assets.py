import os
import subprocess
import textwrap


def test_repo_phase_copies_dark_mode_css_into_htmlcov_assets(tmp_path):
    script_dir = tmp_path / "sidar"
    assets_dir = script_dir / "assets"
    assets_dir.mkdir(parents=True)
    dark_css = assets_dir / "dark_mode.css"
    dark_css.write_text("body { color: #e6edf3; }\n", encoding="utf-8")

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

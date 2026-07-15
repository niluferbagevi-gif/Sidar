from __future__ import annotations

from pathlib import Path

from tests._helpers.source_contracts import expanded_bash_source, shell_function_body


def test_expanded_bash_source_inlines_script_dir_sources(tmp_path: Path) -> None:
    source = tmp_path / "entry.sh"
    module = tmp_path / "helpers.sh"
    source.write_text(
        '#!/usr/bin/env bash\nsource "${SCRIPT_DIR}/helpers.sh"\nafter_source\n',
        encoding="utf-8",
    )
    module.write_text("helper_function() {\n  echo helper\n}\n", encoding="utf-8")

    expanded = expanded_bash_source(source, root=tmp_path)

    assert '# --- expanded from ' in expanded
    assert "helper_function() {" in expanded
    assert expanded.index('source "${SCRIPT_DIR}/helpers.sh"') < expanded.index(
        "helper_function() {"
    )
    assert expanded.index("helper_function() {") < expanded.index("after_source")


def test_shell_function_body_extracts_only_requested_function() -> None:
    script = "first() {\n  echo one\n}\n\nsecond() {\n  echo two\n}\n"

    assert shell_function_body(script, "first") == "first() {\n  echo one\n}\n"

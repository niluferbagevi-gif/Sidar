from __future__ import annotations

from pathlib import Path

import tomllib


def test_pytest_filters_include_sentence_transformers_invalid_escape_rules() -> None:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    filters = data["tool"]["pytest"]["ini_options"]["filterwarnings"]

    assert (
        "ignore:invalid escape sequence '\\\\g':DeprecationWarning:sentence_transformers.evaluation.SentenceEvaluator"
        in filters
    )
    assert (
        "ignore:invalid escape sequence.*:DeprecationWarning:sentence_transformers.*"
        in filters
    )

from __future__ import annotations

import tomllib
from pathlib import Path


def test_pytest_filters_include_sentence_transformers_invalid_escape_rules() -> None:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    filters = data["tool"]["pytest"]["ini_options"]["filterwarnings"]

    assert (
        "ignore:invalid escape sequence '\\\\g':DeprecationWarning:sentence_transformers.evaluation.SentenceEvaluator"
        in filters
    )
    assert "ignore:invalid escape sequence.*:DeprecationWarning:sentence_transformers.*" in filters


def test_pytest_pydantic_warning_filter_avoids_config_time_pydantic_import() -> None:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    filters = data["tool"]["pytest"]["ini_options"]["filterwarnings"]

    assert "ignore::pydantic.warnings.PydanticDeprecatedSince20" not in filters
    assert "ignore::DeprecationWarning:pydantic.*" in filters

    testing_doc = (pyproject.parent / "docs" / "TESTING.md").read_text(encoding="utf-8")
    assert "Pydantic ve pytest warning filtresi" in testing_doc
    assert "ignore::DeprecationWarning:pydantic.*" in testing_doc

from __future__ import annotations

from pathlib import Path

from scripts import repo_contract_report as report


def test_role_contract_report_has_no_current_builtin_drift() -> None:
    role_report = report.build_role_contract_report()

    assert role_report["status"] == "ok"
    assert role_report["drift"] == []
    assert {"role_file", "roles_init_export", "bootstrap_import", "tests"}.issubset(
        set(role_report["checklist_items"])
    )
    assert {item["role_name"] for item in role_report["roles"]} == {
        "coder",
        "researcher",
        "reviewer",
        "poyraz",
        "coverage",
        "qa",
    }


def test_scan_repo_standards_flags_direct_pip_legacy_name_and_low_model_default(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "README.md"
    doc.write_text(
        "Install with pip install sidar\n"
        "OldProduct is visible here\n"
        "Default model: qwen2.5-coder:3b\n"
        "Allowed command: uv pip install sidar-extra\n",
        encoding="utf-8",
    )

    violations = report.scan_repo_standards([doc], legacy_product_names=["OldProduct"])

    assert [item.code for item in violations] == [
        "direct-pip-install",
        "legacy-product-name",
        "low-hardware-model-default",
    ]
    assert all(item.path.endswith("README.md") for item in violations)


def test_build_report_marks_selected_standards_violations_as_fail(tmp_path: Path) -> None:
    doc = tmp_path / "guide.md"
    doc.write_text("python -m pip install bad-example\n", encoding="utf-8")

    built = report.build_report(standards_paths=[doc])

    assert built["status"] == "fail"
    assert built["role_contracts"]["status"] == "ok"
    assert built["repo_standards"]["violations"][0]["code"] == "direct-pip-install"

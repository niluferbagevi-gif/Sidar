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


def test_dependency_profile_plan_sync_current_repo_is_ok() -> None:
    status = report.check_dependency_profile_plan_sync()

    assert status.status == "ok"
    assert status.missing_pyproject_markers == []
    assert status.missing_plan_markers == []
    assert status.pyproject_markers["legacy_full_install_note"] is True
    assert status.pyproject_markers["planned_profile_groups_declared"] is True
    assert status.plan_markers["mentions_tool_plan_table"] is True
    assert status.plan_markers["mentions_planned_profile_groups"] is True


def test_dependency_profile_plan_sync_reports_drift_for_unsynced_docs(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    plan = tmp_path / "docs" / "DEPENDENCY_PROFILE_PLAN.md"
    plan.parent.mkdir()
    pyproject.write_text(
        "[tool.sidar.dependency_profile_plan]\n"
        "current_install_standard = \"uv sync --all-extras\"\n"
        "owner_doc = \"docs/DEPENDENCY_PROFILE_PLAN.md\"\n"
        "preserve_all_extras_standard = false\n"
        "planned_profile_groups = [\"base\", \"web\"]\n"
        "[[tool.sidar.dependency_profile_plan.profiles]]\n"
        "name = \"runtime\"\n",
        encoding="utf-8",
    )
    plan.write_text("# Plan\nUse uv sync only.\n", encoding="utf-8")

    status = report.check_dependency_profile_plan_sync(pyproject, plan)

    assert status.status == "drift"
    assert "legacy_full_install_note" in status.missing_pyproject_markers
    assert "production_profile_declared" in status.missing_pyproject_markers
    assert "preserves_all_extras_standard" in status.missing_pyproject_markers
    assert "planned_profile_groups_declared" in status.missing_pyproject_markers
    assert "mentions_production_minimal" in status.missing_plan_markers
    assert "mentions_planned_profile_groups" in status.missing_plan_markers
    assert "mentions_tool_plan_table" in status.missing_plan_markers

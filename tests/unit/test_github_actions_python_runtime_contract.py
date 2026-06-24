from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
PYTHON_MAJOR_MINOR = "3.11"
PINNED_WORKFLOWS = [
    "ci.yml",
    "migration-cutover-checks.yml",
    "nightly-auth-benchmark.yml",
    "nightly-flaky-scan.yml",
    "nightly-gpu-performance.yml",
    "release-db-benchmark-trend.yml",
    "release-quality.yml",
    "weekly-mutation-and-critical-tests.yml",
]


def _setup_python_versions(text: str) -> list[str | None]:
    versions: list[str | None] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "uses: actions/setup-python@v" not in line:
            continue

        version: str | None = None
        for candidate in lines[index + 1 : index + 7]:
            stripped = candidate.strip()
            if stripped.startswith("python-version:"):
                _, raw_version = stripped.split(":", 1)
                version = raw_version.split("#", 1)[0].strip().strip("'\"")
                break
        versions.append(version)
    return versions


def test_required_workflows_pin_setup_python_to_311():
    for workflow in PINNED_WORKFLOWS:
        path = WORKFLOW_DIR / workflow
        assert path.exists(), workflow
        versions = _setup_python_versions(path.read_text())
        assert versions, workflow
        assert versions == [PYTHON_MAJOR_MINOR] * len(versions)


def test_workflows_do_not_reintroduce_python_312_or_multi_version_matrix():
    for workflow_path in WORKFLOW_DIR.glob("*.yml"):
        text = workflow_path.read_text()
        assert "3.12" not in text, workflow_path.name
        assert "python-version: [" not in text, workflow_path.name
        assert "python-version: '[" not in text, workflow_path.name
        assert 'python-version: "[' not in text, workflow_path.name


def test_all_setup_python_steps_in_workflows_use_311():
    workflow_paths = sorted(WORKFLOW_DIR.glob("*.yml"))
    assert workflow_paths

    for workflow_path in workflow_paths:
        versions = _setup_python_versions(workflow_path.read_text())
        assert all(version == PYTHON_MAJOR_MINOR for version in versions), workflow_path.name


def test_weekly_mutation_workflow_uses_balanced_mutmut_parallelism():
    workflow = (WORKFLOW_DIR / "weekly-mutation-and-critical-tests.yml").read_text()

    assert "mutmut run --max-children 4" in workflow
    assert "MUTMUT_MAX_CHILDREN" not in workflow
    assert "os.cpu_count" not in workflow


def test_nightly_auth_benchmark_requires_cached_baseline_compare():
    workflow = (WORKFLOW_DIR / "nightly-auth-benchmark.yml").read_text()

    assert 'BENCHMARK_COMPARE_REQUIRED: "1"' in workflow
    assert 'BENCHMARK_ENFORCE_COMPARE: "1"' in workflow
    assert "Restore auth benchmark baseline cache" in workflow
    assert "auth-benchmark-baseline-${{ runner.os }}-py311-" in workflow
    assert '--benchmark-compare="${compare_file}"' in workflow
    assert '--benchmark-compare-fail="${BENCHMARK_COMPARE_FAIL}"' in workflow
    assert "BENCHMARK_COMPARE_REQUIRED=1 ancak .benchmarks" in workflow


def test_ci_has_required_installer_manifest_smoke_gate() -> None:
    workflow = (WORKFLOW_DIR / "ci.yml").read_text(encoding="utf-8")
    docs = Path("docs/CI_REQUIRED_CHECKS.md").read_text(encoding="utf-8")

    assert "installer-smoke:" in workflow
    assert "name: Installer manifest and smoke gate" in workflow
    assert "Branch protection should mark this job name as required" in workflow
    assert "uv sync --frozen --extra dev" in workflow
    assert (
        "tests/smoke/test_install_verification.py::"
        "test_install_sidar_embedded_manifests_in_sync"
    ) in workflow
    assert "sha256sum -c .sidar_manifest.txt" in workflow
    assert "uv run python scripts/tools/update_core_install_manifest.py --check" in workflow
    assert (
        "uv run python scripts/tools/update_install_module_hash_manifest.py "
        "--target install_sidar.sh --check"
    ) in workflow
    assert "Treat raw GitHub installer as release artifact" in workflow
    assert "bash -n install_sidar.sh" in workflow
    assert (
        "SIDAR_INSTALL_TEST_MODE=1 SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY=1 "
        "bash install_sidar.sh"
    ) in workflow
    assert "raw installer as a release artifact" in docs
    assert "main/install_sidar.sh" in docs
    assert "test_install_sidar_wget_raw_bootstrap_clone_smoke" in docs
    assert "wget-style clean-install simulation" in docs
    for protected_path in (
        "install_sidar.sh",
        ".sidar_manifest.txt",
        "core/memory.py",
        "core/multimodal.py",
        "scripts/install_modules/**",
    ):
        assert protected_path in workflow
        assert protected_path in docs
    assert "Installer manifest and smoke gate" in docs


def test_installer_security_chain_is_visible_in_pr_review_metadata() -> None:
    template = Path(".github/PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")
    codeowners = Path(".github/CODEOWNERS").read_text(encoding="utf-8")
    docs = Path("docs/CI_REQUIRED_CHECKS.md").read_text(encoding="utf-8")

    assert "Installer manifest checklist" in template
    assert "scripts/sync_install_manifest.sh" in template
    assert "scripts/sync_install_module_hashes.sh" in template
    assert "uv run python scripts/tools/update_core_install_manifest.py --check" in template
    assert (
        "uv run python scripts/tools/update_install_module_hash_manifest.py "
        "--target install_sidar.sh --check"
    ) in template
    assert "Install manifest synced" in template
    assert "Installer manifest and smoke gate" in template
    assert "installer security chain" in template
    for protected_path in (
        "/core/memory.py",
        "/core/multimodal.py",
        "/install_sidar.sh",
        "/.sidar_manifest.txt",
        "/scripts/install_modules/",
    ):
        assert protected_path in codeowners
    assert "PR visibility for core installer files" in docs
    assert "installer-impacting" in docs


def test_installer_docs_scope_unverified_script_bypass_to_non_core_checks() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    modularization_note = Path("docs/module-notes/install_sidar_modularization.md").read_text(
        encoding="utf-8"
    )

    for content in (readme, modularization_note):
        assert "ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1" in content
        assert "çekirdek manifest" in content
        assert "çözüm değildir" in content
        assert "scripts/sync_install_manifest.sh" in content
        assert "belirli bir commit/tag" in content
    assert "Sorun giderme (çekirdek kurulum manifest uyuşmazlığı)" in readme
    assert "Güncellenmiş installer/release" in readme
    assert "core/memory.py" in readme
    assert "core/multimodal.py" in readme


def test_release_quality_runs_benchmark_coverage_trend_gate():
    workflow = (WORKFLOW_DIR / "release-quality.yml").read_text()

    assert "benchmark-coverage-trend:" in workflow
    assert "Restore benchmark coverage trend history" in workflow
    assert "artifacts/benchmark-coverage-trend/history.json" in workflow
    assert "scripts/ci/check_benchmark_coverage_trend.py" in workflow
    assert "--benchmark-json artifacts/benchmark-coverage-trend/benchmark.json" in workflow
    assert "--coverage-xml artifacts/benchmark-coverage-trend/coverage.xml" in workflow
    assert "--history-json artifacts/benchmark-coverage-trend/history.json" in workflow
    assert "--max-regression-pct 15" in workflow

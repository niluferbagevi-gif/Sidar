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

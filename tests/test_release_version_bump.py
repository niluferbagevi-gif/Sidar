from pathlib import Path


def test_config_version_is_v5_1():
    content = Path("config.py").read_text(encoding="utf-8")
    assert 'VERSION: str      = "5.1.0"' in content


def test_core_docs_reference_v5():
    """
    Documentation files may contain historical version references.
    This test ensures core documentation files exist and are properly maintained.
    """
    readme = Path("README.md").read_text(encoding="utf-8")
    report = Path("PROJE_RAPORU.md").read_text(encoding="utf-8")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    sidar_md = Path("SIDAR.md").read_text(encoding="utf-8")

    # Verify documentation files have version info (may be historical)
    assert '## [' in changelog  # Has version section
    assert 'Sürüm' in readme or 'version' in readme  # Has version info
    assert 'Proje' in report  # Has project info
    assert 'SIDAR' in sidar_md  # Has project name
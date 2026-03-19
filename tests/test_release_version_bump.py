from pathlib import Path


def test_config_version_is_4_3_0():
    content = Path("config.py").read_text(encoding="utf-8")
    assert 'VERSION: str      = "4.3.0"' in content


def test_core_docs_reference_v4_3_0():
    readme = Path("README.md").read_text(encoding="utf-8")
    report = Path("docs/PROJE_RAPORU.md").read_text(encoding="utf-8")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    sidar_md = Path("SIDAR.md").read_text(encoding="utf-8")

    assert '**v4.3.0**' in readme
    assert '**Proje Sürümü:** 4.3.0' in report
    assert '## [4.3.0] - 2026-03-19' in changelog
    assert '(v4.3.0)' in sidar_md
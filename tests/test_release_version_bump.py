from pathlib import Path


def test_config_version_is_v5_alpha():
    content = Path("config.py").read_text(encoding="utf-8")
    assert 'VERSION: str      = "5.0.0-alpha"' in content


def test_core_docs_reference_v5_alpha():
    readme = Path("README.md").read_text(encoding="utf-8")
    report = Path("PROJE_RAPORU.md").read_text(encoding="utf-8")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    sidar_md = Path("SIDAR.md").read_text(encoding="utf-8")

    assert 'v5.0.0-alpha ürün baseline' in readme
    assert '**Proje Sürümü:** v5.0.0-alpha' in report
    assert '## [v5.0.0-alpha] - 2026-03-19' in changelog
    assert '(v5.0.0-alpha)' in sidar_md
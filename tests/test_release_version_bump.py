from pathlib import Path


def test_config_version_is_3_0_0():
    content = Path('config.py').read_text(encoding='utf-8')
    assert 'VERSION: str      = "3.0.0"' in content


def test_core_docs_reference_v3_0_0():
    readme = Path('README.md').read_text(encoding='utf-8')
    report = Path('PROJE_RAPORU.md').read_text(encoding='utf-8')
    changelog = Path('CHANGELOG.md').read_text(encoding='utf-8')
    sidar_md = Path('SIDAR.md').read_text(encoding='utf-8')

    assert '**v3.0.0**' in readme
    assert '**Proje Sürümü:** 4.2.0' in report
    assert '## [v3.0.0] - 2026-03-11' in changelog
    assert '(v3.0.0)' in sidar_md
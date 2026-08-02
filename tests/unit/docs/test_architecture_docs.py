from __future__ import annotations

from pathlib import Path


def test_project_report_is_a_small_index_over_topic_sections() -> None:
    index_path = Path("docs/PROJE_RAPORU.md")
    index = index_path.read_text(encoding="utf-8")
    sections = sorted(Path("docs/project-report").glob("*.md"))

    assert index_path.stat().st_size < 10_000
    assert len(sections) == 6
    assert "yeniden monolitik rapora dönüştürülmemelidir" in index
    for section in sections:
        assert section.name in index
        assert section.stat().st_size < 50_000


def test_v52_architecture_is_canonical_and_versioned_reports_are_historical() -> None:
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    report_index = Path("docs/PROJE_RAPORU.md").read_text(encoding="utf-8")
    v50 = Path("docs/SIDAR_v5_0_MIMARI_RAPORU.md").read_text(encoding="utf-8")
    v51 = Path("docs/SIDAR_v5_1_MIMARI_RAPORU.md").read_text(encoding="utf-8")

    assert "Aktif mimari doğruluk kaynağı" in architecture
    assert "v5.2.0" in architecture
    assert "agent/self_heal/orchestrator.py" in architecture
    assert "scripts/autonomous_modules/" in architecture
    assert "web_ui_react/src/lib/api.ts" in architecture
    assert "ARCHITECTURE.md" in report_index
    assert "Tarihsel v5.0 vizyon/faz kaydıdır" in v50
    assert "Tarihsel Faz C–E evrim kaydıdır" in v51


def test_project_report_distinguishes_debt_from_future_product_phases() -> None:
    """The report must not hide tracked campaigns behind an absolute zero-debt claim."""
    debt = Path("docs/project-report/04-teknik-borc-ve-yapilandirma.md").read_text(encoding="utf-8")
    roadmap = Path("docs/project-report/05-mimari-evrim-ve-yol-haritasi.md").read_text(
        encoding="utf-8"
    )

    assert "Açık Kritik Teknik Borç | **0" in debt
    assert "İzlenen Mühendislik Kampanyaları | **Var" in debt
    assert "mutlak “zero debt” iddiası kullanılmıyor" in debt
    assert "TypeScript migrasyonu" in debt
    assert "D100-D107" in debt
    assert "yol haritası kalemleri açık teknik kusur sayılmaz" in roadmap
    assert "Harici graph backend'i" in roadmap
    assert "RLHF/DPO orkestrasyonu" in roadmap
    assert "fail_under = 100" in roadmap
    assert "%90" not in roadmap

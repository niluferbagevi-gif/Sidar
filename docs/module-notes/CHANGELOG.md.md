# CHANGELOG.md

- **Kaynak dosya:** `CHANGELOG.md`
- **Not dosyası:** `docs/module-notes/CHANGELOG.md.md`
- **Amaç:** Sürüm geçmişi. Yalnızca sürümler arası farkları, kısa düzeltme
  notlarını ve teknik borç kapanışı özetlerini içerir; ayrıntılı çözüm
  geçmişi `docs/archive/` altında tutulur (bkz. dosyanın kendi başındaki not).
- **Madde bütçesi (P3):** `[Unreleased]` altındaki her madde 2-3 cümleyle
  (madde başına ~70 kelime) sınırlıdır; `scripts/ci/check_changelog_entry_budget.py`
  (CI'nın `Base quality gates` job'ı, `scripts/ci/changelog-entry-budget-baseline.json`)
  bunu tek yönlü olarak zorlar — `web_server.py` boyut bütçesiyle aynı desen
  (`--update` yok, elle/incelenmiş bir azaltım gerekir). 2026-09-10'da mevcut
  `[Unreleased]` maddelerinin tam kök-neden detayı (o zamanki 1256 satır/331 KB
  hâliyle) `docs/archive/unreleased_root_cause_detail.md`'ye taşındı; dosya
  120 KB'ye indi. Yeni maddelerin ayrıntısı doğrudan aynı arşiv dosyasına
  (veya sürüm kapanışında `docs/archive/resolved_issues_v3.md`'nin bir
  sonraki fazına) eklenmelidir.
- **Durum:** İncelendi ve `docs/module-notes` altında dokümante edildi.

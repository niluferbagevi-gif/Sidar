# 3.7f `agent/roles/` — Uzman Ajan Rolleri (Coder, Researcher, Reviewer, Poyraz, QA & Coverage)

## Rapor İçeriği (Taşınan Bölüm)

**Amaç:** Uzman ajanların görev paylaşımıyla kod üretimi, araştırma, kalite kontrol, pazarlama, QA ve coverage döngülerini yürütür.

**Alt Roller ve Yetenekler:**
- `__init__.py` — 6 yerleşik rol sınıfını (`CoderAgent`, `ResearcherAgent`, `ReviewerAgent`, `PoyrazAgent`, `QAAgent`, `CoverageAgent`) sıralı, korumasız `from .X import Y` satırlarıyla dışa aktarır. Bu liste kasıtlı olarak `agent/registry.py::BUILTIN_ROLE_MODULES`/`BUILTIN_ROLE_CONTRACTS` ile birebir örtüşür ve `tests/unit/agent/test_registry.py::test_builtin_role_contract_static_exports_match_import_bootstrap_literal` bunu statik AST karşılaştırmasıyla kilitler — bağımlılık eklemeden drift tespiti sağlar.
  - **Bilinen mimari ödünleşim:** Bu paketin `__init__.py`'ı korumasız olduğundan (try/except yok), herhangi bir alt modülün (örn. `coverage_agent.py`) eksik bir bağımlılığı nedeniyle importu patlarsa Python paketin tamamını (dolayısıyla `agent.roles` altındaki diğer tüm rolleri) yükleyemez — tek bir rolün sorunu, birbiriyle ilgisiz diğer roller için de domino etkisi yaratabilir. `agent/registry.py::_import_builtin_roles()` her modülü ayrı ayrı `importlib` ile içe aktarıp hatayı modül bazında yakalasa da, bu koruma bu paket init'inin tamamen çalışmasına bağlı olduğu için devre dışı kalır. Bu yüzden her yerleşik rolün gerçekten kullandığı bağımlılıkların `pyproject.toml`'da **çekirdek runtime `dependencies`** altında (yalnızca `dev` extra'sında değil) tanımlı olması kritik önemdedir — bkz. `agent/roles/coverage_agent.py` (`defusedxml`) vakası ve `docs/DEPENDENCY_PROFILE_PLAN.md`.
- `coder_agent.py` — kod/dosya odaklı uzman ajan; `read_file`, `write_file`, `patch_file`, `execute_code`, `list_directory`, `glob_search`, `grep_search`, `audit_project`, `get_package_info`, `scan_project_todos` dahil 10 araç kaydıyla çalışır.
- `researcher_agent.py` — araştırma odaklı uzman ajan; `web_search`, `fetch_url`, `search_docs`, `docs_search` araçlarıyla web + RAG keşfi yapar.
- `reviewer_agent.py` — QA uzmanı; `_build_dynamic_test_content` ile dinamik test üretir, `_extract_changed_paths` ile değişen dosyaları hedefler, regresyon komutlarını çalıştırır ve sonucu `delegate_to("coder", ...)` ile P2P geri bildirim olarak kodlayıcıya iletir.
- `poyraz_agent.py` — pazarlama uzmanı; SEO analizi, kampanya metni ve audience-ops görevlerini yürütür.
- `qa_agent.py` — CI/kalite kapısı uzmanı; test üretimi ve CI remediation görevlerini yürütür.
- `coverage_agent.py` — coverage açığını kapatan otonom test üretim ajanı; pytest'in JUnit XML çıktısını `defusedxml.ElementTree` ile ayrıştırır (bkz. yukarıdaki mimari ödünleşim notu).

**Mimari Not:** Coder ↔ Reviewer etkileşimi yalnızca merkezî supervisor döngüsüyle sınırlı değildir; reviewer tarafından üretilen `qa_feedback|decision=...` çıktıları coder tarafında ayrıştırılıp yeniden çalışma (rework) akışı tetiklenebilir.

---

# 3.7f `agent/roles/` — Uzman Ajan Rolleri (Coder, Researcher & Reviewer)

**Amaç:** Uzman ajanların görev paylaşımıyla kod üretimi, araştırma ve kalite kontrol döngüsünü yürütür.

> Not (Doğrulama): Güncel depoda `wc -l` çıktıları: `agent/roles/coder_agent.py=134`, `agent/roles/researcher_agent.py=75`, `agent/roles/reviewer_agent.py=181`, `agent/roles/__init__.py=6`.

**Alt Roller ve Yetenekler:**
- `__init__.py` — rol sınıflarını (`CoderAgent`, `ResearcherAgent`, `ReviewerAgent`) dışa aktarır.
- `coder_agent.py` — kod/dosya odaklı uzman ajan; `read_file`, `write_file`, `patch_file`, `execute_code`, `list_directory`, `glob_search`, `grep_search`, `audit_project`, `get_package_info`, `scan_project_todos` dahil 10 araç kaydıyla çalışır.
- `researcher_agent.py` — araştırma odaklı uzman ajan; `web_search`, `fetch_url`, `search_docs`, `docs_search` araçlarıyla web + RAG keşfi yapar.
- `reviewer_agent.py` — QA uzmanı; `_build_dynamic_test_content` ile dinamik test üretir, `_extract_changed_paths` ile değişen dosyaları hedefler, regresyon komutlarını çalıştırır ve sonucu `delegate_to("coder", ...)` ile P2P geri bildirim olarak kodlayıcıya iletir.

**Mimari Not:** Coder ↔ Reviewer etkileşimi yalnızca merkezî supervisor döngüsüyle sınırlı değildir; reviewer tarafından üretilen `qa_feedback|decision=...` çıktıları coder tarafında ayrıştırılıp yeniden çalışma (rework) akışı tetiklenebilir.

---

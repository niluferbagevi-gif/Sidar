# `uploader/files.py` — Yüklenecek Dosya Seçimi

- **Kaynak dosya:** `uploader/files.py`
- **Not dosyası:** `docs/module-notes/uploader/files.py.md`

**Amaç:** Yüklenmemesi gereken yolların filtrelenmesi ve güvenli dosya listesinin toplanması.

**Özellikler:**
- `FORBIDDEN_PATHS`, `GENERATED_ARTIFACT_PATHS`, `CONFLICT_MARKER_RE` (`github_upload` re-export eder).
- `normalize_path`, `is_forbidden_path`, `get_file_content`, `has_conflict_markers`.
- `collect_safe_files(...)` — `git status` çıktısından yasaklı, üretilmiş, okunamayan veya çakışma işaretli dosyaları eleyerek yüklenecek listeyi çıkarır.

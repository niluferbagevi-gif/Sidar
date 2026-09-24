# `uploader/gates.py` — Yükleme Kalite Kapıları

- **Kaynak dosya:** `uploader/gates.py`
- **Not dosyası:** `docs/module-notes/uploader/gates.py.md`

**Amaç:** Commit öncesi hızlı kapı, commit sonrası bütünlük kapısı, push öncesi kapı ve doğrudan `main` hazırlık kapısı.

**Özellikler:**
- `run_quality_steps`, `run_pre_commit_fast_gate`, `run_post_commit_integrity_gate`, `run_pre_push_quality_gate`.
- `describe_post_commit_gate_failure` — commit sonrası başarısızlıkta elle geri dönüş talimatı.
- `run_direct_main_readiness_gate`.

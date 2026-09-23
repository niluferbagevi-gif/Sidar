# `launcher/session.py` — Sihirbaz Oturum Cache'i

- **Kaynak dosya:** `launcher/session.py`
- **Not dosyası:** `docs/module-notes/launcher/session.py.md`

**Amaç:** Son sihirbaz seçimlerini `.sidar_session.json` dosyasına atomik yazar ve
güvenle geri okur. `main.py`'den taşındı; `main._save_launcher_session` /
`_load_launcher_session` sarmalayıcıları normalizer, sürüm ve logger'ı enjekte eder.

**Özellikler:**
- `session_lock(path, *, exclusive)` — eşzamanlı terminal süreçleri için
  `fcntl.flock` tabanlı paylaşımlı/özel kilit (kilit dosyası `0600`).
- `save_session(...)` — geçici dosyaya yazıp `replace` ile atomik değiştirir;
  dosya izinleri `0600`.
- `load_session(...)` — dosya yoksa, JSON bozuksa, sürüm farklıysa veya seçim
  alanı yoksa `None` döner.

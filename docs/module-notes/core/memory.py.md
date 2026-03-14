# 3.9 `core/memory.py` — Konuşma Belleği (DB tabanlı, v3.0)

## Rapor İçeriği (Taşınan Bölüm)

**Amaç:** Çok kullanıcılı, thread-safe ve DB kalıcılığı kullanan konuşma belleği katmanı sağlar.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l core/memory.py` çıktısına göre **316** olarak ölçülmüştür.

**v3.0 Mimari Değişim:**
- Eski JSON dosya temelli kalıcılık yerine `core/db.py` üzerinden **asenkron veritabanı** kalıcılığı kullanılır.
- Oturum ve mesaj işlemleri kullanıcı kimliği (`user_id`) ile izole edilir.
- Kimliği doğrulanmamış kullanım `MemoryAuthError` ile **fail-closed** engellenir (`_require_active_user`).

**Öne Çıkan API'ler:**
- Async çekirdek: `acreate_session`, `aload_session`, `adelete_session`, `aget_all_sessions`, `aadd`, `aget_history`, `aupdate_title`, `aset_active_user`
- Sync uyumluluk katmanı: `create_session`, `load_session`, `delete_session`, `add`, `get_history` (içeride async çağrıları `_run_coro_sync` köprüsü ile güvenli biçimde çalıştırır)

**Davranış Notları:**
- DB schema başlangıçta otomatik hazırlanır (`connect` + `init_schema`).
- Token bazlı akıllı özetleme aktiftir: `tiktoken` ile token tahmini yapılır; `max_turns` penceresi veya `6000` token eşiği aşılırsa `needs_summarization` tetiklenir.
- `apply_summary`, geçmiş konuşmayı `[KONUŞMA ÖZETİ]` mesajına sıkıştırır, son `keep_last` turları korur ve DB oturumunu özetlenmiş içerikle yeniden yazar.
- Legacy uyumluluk için `_save()` ve `_cleanup_broken_files()` DB modunda no-op olarak korunur.

---

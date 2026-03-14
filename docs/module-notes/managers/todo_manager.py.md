# 3.17 `managers/todo_manager.py` — Görev Takip Yöneticisi (451 satır)

**Amaç:** Claude Code'daki `TodoWrite/TodoRead` araçlarına eşdeğer görev listesi.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l managers/todo_manager.py` çıktısına göre **451** olarak ölçülmüştür.

**Görev Durumları:** `pending` ⬜ → `in_progress` 🔄 → `completed` ✅

**Özellikler:**
- Thread-safe `RLock` ile korunur (multi-agent eşzamanlı yazma/okuma yarışlarını azaltır)
- `@dataclass` tabanlı `TodoTask` modeli ile tip güvenliği (`id`, `content`, `status`, `created_at`, `updated_at`)
- `created_at` / `updated_at` timestamp alanlarıyla görev yaşam döngüsü takibi
- `todo_write("görev1:::pending|||görev2:::in_progress")` formatı
- `_ensure_single_in_progress()`: aynı anda yalnızca 1 aktif görev; diğerleri `pending`'e döner
- `set_tasks()`: toplu görev yenileme (TodoWrite style)
- `_normalize_limit()`: limit değeri 1–200 arasına sıkıştırılır
- Kalıcı: `data/todo.json` dosyasına kaydedilir

**`scan_project_todos()` (v2.9.0 — §14.7.5):**
Proje dizinini gezer; `.py`, `.md`, `.js`, `.ts` dosyalarındaki `TODO` ve `FIXME` yorumlarını tarar. Güvenlik kontrolü: `base_dir` dışı tarama engellenir.

---

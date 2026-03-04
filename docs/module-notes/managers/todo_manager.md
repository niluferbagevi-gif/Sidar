# managers/todo_manager.py Teknik Notu

`TodoManager`, Claude Code benzeri görev listesi (todo) takibini sağlar.

## Sorumluluklar
- Görev ekleme/güncelleme/listeleme/silme
- Durum yönetimi: `pending`, `in_progress`, `completed`
- Thread-safe bellek içi görev saklama (`RLock`)

## Bağlantılar
- Tüketen: `SidarAgent`, `web_server.py`, `web_ui/index.html`

## Not
- Mevcut tasarım process-memory tabanlıdır; yeniden başlatmada görevler sıfırlanır.
- Kalıcılık istenirse JSON/SQLite tabanlı persistence katmanı eklenmelidir.

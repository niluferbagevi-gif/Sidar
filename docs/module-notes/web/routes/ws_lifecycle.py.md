# `web/routes/ws_lifecycle.py` — Paylaşılan WebSocket Yaşam Döngüsü

- **Kaynak dosya:** `web/routes/ws_lifecycle.py`
- **Not dosyası:** `docs/module-notes/web/routes/ws_lifecycle.py.md`

**Amaç:** `ws_chat.py` ve `ws_voice.py`'nin ikisinin de kullandığı, bağlantı
kabul öncesi rate-limit reddi ve temizlik (cleanup) yardımcılarını barındırır.

**Özellikler:**
- `reject_rate_limited_connection(websocket, deps)` (async) — paylaşımlı
  WebSocket guard'ı doymuşsa bağlantıyı `accept()` öncesi (kod 1013 ile)
  reddeder.
- `WebSocketLifecycle` — bağlantı açma/kapama etrafındaki ortak temizlik
  mantığını kapsülleyen sınıf.

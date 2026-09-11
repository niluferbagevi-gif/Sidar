# `web/routes/ws_voice.py` — WebSocket Ses Rotası

- **Kaynak dosya:** `web/routes/ws_voice.py`
- **Not dosyası:** `docs/module-notes/web/routes/ws_voice.py.md`

**Amaç:** `/ws/voice` WebSocket uç noktasını barındırır; `core/voice.py`'nin
gerçek zamanlı ses yüzeyi. `ws_chat.py`'deki gönderim/bağlantı yardımcılarını
ve `web/security.py`'deki `SIDAR_WS_VOICE_PROTOCOL`'ü yeniden kullanır.

**Özellikler:**
- `build_ws_voice_router(deps_factory)` — `WS /ws/voice` rotasını kaydeder.
- `websocket_voice(websocket, deps)` (async) — ses akışı bağlantı/mesaj
  döngüsünü yönetir.

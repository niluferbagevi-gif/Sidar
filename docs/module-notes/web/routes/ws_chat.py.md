# `web/routes/ws_chat.py` — WebSocket Sohbet Rotası

- **Kaynak dosya:** `web/routes/ws_chat.py`
- **Not dosyası:** `docs/module-notes/web/routes/ws_chat.py.md`

**Amaç:** Ana `/ws/chat` WebSocket uç noktasını ve ajan yanıtlarını gerçek
zamanlı akıtma yardımcılarını barındırır; `web/routes/ws_lifecycle.py`'deki
`WebSocketLifecycle` ve rate-limit reddini kullanır.

**Özellikler:**
- `websocket_is_connected(websocket)`,
  `send_json_if_connected(websocket, payload)` (async) — bağlantı durumuna
  duyarlı güvenli gönderim (kapanmış soket'e yazma hatasını önler).
- `build_ws_chat_router(deps_factory)` — `WS /ws/chat` rotasını kaydeder.
- `ws_stream_agent_text_response(websocket, agent, prompt)` (async) — ajan
  metin yanıtını parça parça soket'e akıtır.
- `websocket_chat(websocket, deps)` (async) — bağlantı kabul/mesaj
  döngüsü/kapanış yaşam döngüsünü yönetir.

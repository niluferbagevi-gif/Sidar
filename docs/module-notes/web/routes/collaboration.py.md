# `web/routes/collaboration.py` — Gerçek Zamanlı İşbirliği Odaları

- **Kaynak dosya:** `web/routes/collaboration.py`
- **Not dosyası:** `docs/module-notes/web/routes/collaboration.py.md`

**Amaç:** WebSocket tabanlı çok kullanıcılı işbirliği odalarının (kod
inceleme/pair-programming benzeri) durum yönetimini ve mesaj/telemetri
yayınını barındırır; yazma niyeti taşıyan mesajları (`COLLAB_WRITE_INTENT_RE`)
tespit ederek rol bazlı yazma iznine (`collaboration_write_scopes_for_role`)
göre kısıtlar.

**Özellikler:**
- `COLLAB_ROOM_RE` — oda kimliği format doğrulaması (path traversal'a kapalı
  karakter kümesi).
- `CollaborationParticipant`, `CollaborationRoom` — oda/katılımcı durum
  modelleri.
- `normalize_room_id(...)`, `socket_key(websocket)`,
  `serialize_collaboration_participant(...)`,
  `normalize_collaboration_role(role)` — normalizasyon/serileştirme.
- `collaboration_write_scopes_for_role(role, room_id, *, base_dir)`,
  `collaboration_command_requires_write(command)` — rol bazlı yazma
  kapsamı ve komutun yazma gerektirip gerektirmediği.
- `mask_collaboration_text(...)` — hassas metni maskeler.
- `append_room_message(...)`, `append_room_telemetry(...)`,
  `build_room_message(...)`, `broadcast_room_payload(...)` (async),
  `emit_control_room_event(...)` (async) — oda mesaj/telemetri akışı.
- `join_collaboration_room(...)` (async), `leave_collaboration_room(...)` (async)
  — katılım yaşam döngüsü.
- `is_sidar_mention(message)`, `strip_sidar_mention(message)` — `@sidar`
  bahsini tespit/temizler.

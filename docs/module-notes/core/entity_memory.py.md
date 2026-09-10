# `core/entity_memory.py` — Varlık/Persona Belleği

- **Kaynak dosya:** `core/entity_memory.py`
- **Not dosyası:** `docs/module-notes/core/entity_memory.py.md`

**Amaç:** Kullanıcının uzun vadeli kodlama stilini, dil tercihlerini ve
etkileşim örüntülerini Mem0/Zep benzeri bir yapıda SQLite'ta saklar;
`web/routes/memory_feedback.py`'nin `/api/memory/entity/*` rotalarının
arkasındaki servis katmanı.

**Kullanım:**
```python
em = EntityMemory(database_url="sqlite+aiosqlite:///data/sidar.db", config=cfg)
await em.initialize()
await em.upsert(user_id="u1", key="coding_style", value="functional, type-hinted")
style = await em.get(user_id="u1", key="coding_style")
profile = await em.get_profile(user_id="u1")
```

**Özellikler:**
- `EntityMemory` — `upsert`/`get`/`get_profile` gibi async CRUD metodları;
  opsiyonel TTL (`ttl_days`) ile geçici kayıt desteği.
- `get_entity_memory(config=None)` — process-wide singleton erişimi.

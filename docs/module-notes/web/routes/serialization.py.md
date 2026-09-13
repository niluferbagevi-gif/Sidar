# `web/routes/serialization.py` — Yan Etkisiz Serileştiriciler

- **Kaynak dosya:** `web/routes/serialization.py`
- **Not dosyası:** `docs/module-notes/web/routes/serialization.py.md`

**Amaç:** Route fabrikalarının paylaştığı, DB kayıtlarını JSON-uyumlu
sözlüklere çeviren saf (side-effect-free) serileştiriciler.

**Özellikler:**
- `serialize_prompt(record)` — prompt registry kaydını serileştirir; legacy
  sayısal olmayan id'leri korur (`int` denenir, olmazsa `str`'ye düşer).
- `serialize_swarm_result(record)` — swarm görev sonucunu serileştirir.

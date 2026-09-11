# `web/collaboration_service.py` — İşbirliği Streaming Yardımcısı

- **Kaynak dosya:** `web/collaboration_service.py`
- **Not dosyası:** `docs/module-notes/web/collaboration_service.py.md`

**Amaç:** Monolitik web sunucu modülünün dışında tutulan, işbirliği (collab)
asistan yanıtlarını streaming için sabit boyutlu parçalara bölen tek
fonksiyonluk yardımcı.

**Özellikler:**
- `iter_stream_chunks(text, *, size=180)` — metni `size` karakterlik kararlı
  parçalara böler; boş girdide boş liste döner.

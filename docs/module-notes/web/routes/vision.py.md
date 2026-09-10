# `web/routes/vision.py` — Görüntü Analizi Rotaları

- **Kaynak dosya:** `web/routes/vision.py`
- **Not dosyası:** `docs/module-notes/web/routes/vision.py.md`

**Amaç:** Base64 kodlu görüntüleri analiz eden ve mockup → kod dönüşümü
yapan HTTP rotalarını kaydeder; `core/vision.py`'nin HTTP yüzeyi.

**Özellikler:**
- `VisionAnalyzeRequest`, `VisionMockupRequest` (BaseModel) — görüntü/MIME/
  analiz türü/opsiyonel prompt payload'ları.
- `_decode_image_payload(image_base64)` — base64'ü doğrulayıp byte'a çevirir.
- `build_vision_router(...)` — `POST /api/vision/analyze`,
  `POST /api/vision/mockup` rotalarını kaydeder.

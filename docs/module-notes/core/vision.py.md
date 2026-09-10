# `core/vision.py` — Multimodal Vision (UI Mockup → Frontend Kodu)

- **Kaynak dosya:** `core/vision.py`
- **Not dosyası:** `docs/module-notes/core/vision.py.md`

**Amaç:** Görsel (PNG/JPEG/WebP/GIF) veya ekran görüntüsünden LLM tabanlı
frontend kodu üretir; Gemini, OpenAI GPT-4o-vision, Anthropic Claude vision
sağlayıcılarını destekler. `web/routes/vision.py`'nin arkasındaki
implementasyon.

**Kullanım:**
```python
pipeline = VisionPipeline(llm_client, config)
result = await pipeline.mockup_to_code(image_path="ui.png", framework="React")
print(result["code"])
```

**Özellikler:**
- `load_image_as_base64(...)` (async), `load_image_from_bytes(...)` —
  görsel yükleme/kodlama.
- `build_vision_messages(...)`, `build_mockup_prompt(...)`,
  `build_analyze_prompt(analysis_type="general")` — sağlayıcıya özel vision
  mesaj/prompt kurulumu.
- `VisionPipeline` — `mockup_to_code()`/`analyze()` gibi üst düzey async
  metodlar taşıyan ana sınıf.

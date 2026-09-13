# `core/voice.py` — Voice/TTS Yardımcıları

- **Kaynak dosya:** `core/voice.py`
- **Not dosyası:** `docs/module-notes/core/voice.py.md`

**Amaç:** Text-to-Speech adaptörlerini ve WebSocket üzerinden kademeli
(streaming) ses yanıtı üretmek için ortak yardımcı sınıfları barındırır;
`web/routes/ws_voice.py`'nin arkasındaki implementasyon.

**Özellikler:**
- `_BaseTTSAdapter`, `_MockTTSAdapter(_BaseTTSAdapter)`,
  `_Pyttsx3Adapter(_BaseTTSAdapter)` — TTS sağlayıcı adaptör hiyerarşisi
  (test/gerçek `pyttsx3` motoru ayrımı).
- `_build_tts_adapter(provider)` — sağlayıcı adına göre adaptör seçer.
- `VoicePipeline` — ses işleme/TTS akışının ana orkestratörü.
- `BrowserAudioPacket` (dataclass), `WebRTCAudioIngress` — tarayıcıdan
  gelen ham ses paketlerini karşılayan giriş katmanı.

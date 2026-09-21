# `core/config_multimodal.py` — Multimodal Vision/Ses Ayarları

- **Kaynak dosya:** `core/config_multimodal.py`
- **Not dosyası:** `docs/module-notes/core/config_multimodal.py.md`

**Amaç:** `config.py`'deki `# ─── Multimodal Vision (v6.0) ───` bloğunun 15
alanını `MultimodalSettings` frozen dataclass'ı olarak yükler; `config.Config`
bunu `multimodal_settings` olarak expose eder ve aynı alanları geriye dönük
uyumlu `Config.FOO` class attribute'larına delege eder
(`docs/REFACTOR_PLAN.md`'nin `config.py` maddesinde sürekli öğrenme
diliminden sonra işaretlenen sıradaki düşük riskli dilim). Bu ayarlar
`AGENTS.md` §2.7 (Çoklu modalite: görüş ve ses yetenekleri) içinde
dokümante edilen feature-flag/limit sözleşmesinin doğrudan kaynağıdır ve
`core/vision.py`, `core/multimodal.py`, `core/voice.py` ile
`web/routes/ws_voice.py` tarafından mevcut alan adlarıyla `getattr(config,
"FOO", default)` üzerinden tüketilmeye devam eder. `core/voice.py`'nin
ayrıca okuduğu `VOICE_ENABLED`, `config.py`'de hiç tanımlı olmadığı için
kapsam dışı bırakıldı; yalnız opsiyonel runtime `getattr` yüzeyi
(varsayılan `True`). Genel websocket kimlik doğrulama zaman aşımı olan
`WS_AUTH_TIMEOUT_SECONDS` de kapsam dışı bırakıldı — `ws_voice.py` ve
`ws_chat.py` tarafından ortak kullanılan, multimodal'e özgü olmayan ayrı
bir alan.

**Özellikler:**
- `MultimodalSettings` — `enable_vision`, `vision_max_image_bytes`,
  `enable_multimodal`, `multimodal_max_file_bytes`, `voice_stt_provider`,
  `voice_tts_provider`, `voice_tts_voice`, `voice_tts_segment_chars`,
  `voice_tts_buffer_chars`, `voice_vad_enabled`,
  `voice_vad_min_speech_bytes`, `voice_duplex_enabled`,
  `voice_vad_interrupt_min_bytes`, `whisper_model`, `voice_ws_max_bytes`.
- `load_multimodal_settings()` — her alanı kendi ortam değişkeninden okur;
  sayısal alanlar (`get_int_env()`) malformed girdilerde uyarı loglayıp
  varsayılana düşer, boolean alanlar (`get_bool_env()`) katı
  "true"/"false" ayrıştırması kullanır.

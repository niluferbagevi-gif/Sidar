# `core/multimodal.py` — Çoklu Medya (Video/Ses) İşleme Yardımcıları

- **Kaynak dosya:** `core/multimodal.py`
- **Not dosyası:** `docs/module-notes/core/multimodal.py.md`

**Amaç:** v5.0 yol haritasındaki video/ses algı katmanının MVP temeli;
video dosyalarından frame çıkarma, ses kanalı ayırma, Whisper benzeri STT
akışıyla transkript üretme ve bunları ortak bir LLM bağlamına dönüştürme.
Alt süreç çağrıları (`ffmpeg` vb.) bu session'da `core/utils/trusted_subprocess.py`
merkezileştirmesinin kapsamına girdi (yalnızca hash-only installer manifest
etkisi vardı, davranış değişmedi).

**Özellikler:**
- `ExtractedFrame`, `DownloadedMedia` (dataclass) — çıkarılan frame/indirilen
  medya sonuç tipleri.
- `detect_media_kind(*, mime_type=None, path=None)` — medya türünü
  (video/ses/görüntü) belirler.
- `is_remote_media_source(value)`, `detect_video_platform(value)`,
  `extract_youtube_video_id(value)` — uzak medya kaynağı tespiti.
- `fetch_youtube_transcript(...)` (async) — YouTube transkriptini çeker,
  `_normalize_youtube_transcript_events(...)` ile normalize eder.
- `download_remote_media(...)`, `resolve_remote_media_stream(...)`,
  `materialize_remote_media_for_ffmpeg(...)` (hepsi async) — uzak medyayı
  indirir/`ffmpeg` ile işlenebilir hale getirir.

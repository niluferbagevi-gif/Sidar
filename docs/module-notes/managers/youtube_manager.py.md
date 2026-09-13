# `managers/youtube_manager.py` — YouTube Transcript ve Video Analiz Yöneticisi

- **Kaynak dosya:** `managers/youtube_manager.py`
- **Not dosyası:** `docs/module-notes/managers/youtube_manager.py.md`

**Amaç:** YouTube transcript çıkarımı ve video kare (frame) analizi için
manager katmanı; `core/multimodal.py`'deki düşük seviyeli medya
yardımcılarını bir video URL'sinden uçtan uca içerik özetine bağlar.

**Özellikler:**
- `extract_video_id(value)` — bir YouTube URL'sinden/ID metninden video
  kimliğini çıkarır.
- `_timedtext_url()` / `_normalize_transcript_events()` — YouTube'un
  zaman damgalı altyazı (timedtext) API'sinin URL'sini kurar ve ham olay
  listesini normalize eder.
- `fetch_transcript(...)` (async) — bir video için transcript
  metnini/olaylarını getirir.
- `analyze_video_file(...)` (async) — indirilmiş bir video dosyasından
  kare çıkarıp görsel analiz pipeline'ına (`core/vision.py`) besler.
- `build_video_analysis(...)` (async) — transcript + kare analizini
  birleştirip tek bir video analiz sonucu üretir.

## İlgili modüller

`core/multimodal.py`, `core/vision.py`, `managers/browser_manager.py`.

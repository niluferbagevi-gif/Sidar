# pyproject.toml

- **Kaynak dosya:** `pyproject.toml`
- **Not dosyası:** `docs/module-notes/pyproject.toml.md`
- **Amaç:** Projenin ana paket ve metadata kaynağıdır (Single Source of Truth).
- **Not:** `core/`, `managers/` ve ses/RAG akışlarının çalışması için gerekli AI/medya paketleri (`openai`, `anthropic`, `litellm`, `chromadb`, `pgvector`, `SpeechRecognition`, `pyaudio`, `openai-whisper`, `yt-dlp`) ana `dependencies` altında tutulur; ek profiller (`extras`) isteğe bağlı genişletmeler için korunur.
- **Dev optimizasyonu:** `dev` grubunda `ruff` standart lint/format aracı olarak bırakılmış, `black` ve `flake8` kaldırılmıştır.
- **Lock üretimi:** `requirements*.txt` dosyaları bu dosyadan `uv pip compile` ile üretilir.
- **Durum:** UV tabanlı modern paket mimarisiyle uyumlu.
- **2026-08-15 torch reminder:** `torch 2.11.0` lock/policy penceresi için takip metadata'sı `pyproject.toml` içindeki `[tool.sidar.dependency_profile_plan.torch_upgrade_reminder]` bloğunda ve takvim girdisi `docs/reminders/torch-cve-review-2026-08-15.ics` dosyasında tutulur.
- **Production-minimal doğrulama:** CI `production-profile-dry-run` job'ı `uv sync --frozen --extra production-minimal --no-dev` ile no-dev profilini kurar ve temel runtime import smoke doğrulamasını çalıştırır.
- **Ruff E501 borcu:** `line-length=100` korunur; global E501 ignore geçici legacy uyumluluk borcu olarak `[tool.sidar.ruff_debt]` altında tarihli takip edilir.

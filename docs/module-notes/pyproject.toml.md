# pyproject.toml

- **Kaynak dosya:** `pyproject.toml`
- **Not dosyası:** `docs/module-notes/pyproject.toml.md`
- **Amaç:** Projenin ana paket ve metadata kaynağıdır (Single Source of Truth).
- **Not:** `core/`, `managers/` ve ses/RAG akışlarının çalışması için gerekli AI/medya paketleri (`openai`, `anthropic`, `litellm`, `chromadb`, `pgvector`, `SpeechRecognition`, `pyaudio`, `openai-whisper`, `yt-dlp`) ana `dependencies` altında tutulur; ek profiller (`extras`) isteğe bağlı genişletmeler için korunur.
- **Dev optimizasyonu:** `dev` grubunda `ruff` standart lint/format aracı olarak bırakılmış, `black` ve `flake8` kaldırılmıştır.
- **Lock üretimi:** `requirements*.txt` dosyaları bu dosyadan `uv pip compile` ile üretilir.
- **Durum:** UV tabanlı modern paket mimarisiyle uyumlu.
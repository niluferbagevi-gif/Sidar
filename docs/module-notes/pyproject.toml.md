# pyproject.toml

- **Kaynak dosya:** `pyproject.toml`
- **Not dosyası:** `docs/module-notes/pyproject.toml.md`
- **Amaç:** Projenin ana paket ve metadata kaynağıdır (Single Source of Truth).
- **Not:** `core/`, `managers/` ve ses/RAG akışlarının çalışması için gerekli AI/medya paketleri (`openai`, `anthropic`, `litellm`, `chromadb`, `pgvector`, `SpeechRecognition`, `pyaudio`, `openai-whisper`, `yt-dlp`) ana `dependencies` altında tutulur; ek profiller (`extras`) isteğe bağlı genişletmeler için korunur.
- **Dev optimizasyonu:** `dev` grubunda `ruff` standart lint/format aracı olarak bırakılmış, `black` ve `flake8` kaldırılmıştır.
- **Lock üretimi:** `requirements*.txt` dosyaları bu dosyadan `uv pip compile` ile üretilir.
- **Durum:** UV tabanlı modern paket mimarisiyle uyumlu.
- **Torch CVE çözüm kaydı:** 2026-08-15 hedefli inceleme 2026-08-09'da tamamlandı;
  `torch 2.13.0` patched lock kanıtı ve kaldırılan policy istisnası
  `[tool.sidar.dependency_profile_plan.torch_upgrade_reminder]` bloğunda `status=resolved`
  olarak tutulur.
- **Production-minimal doğrulama:** CI `production-profile-dry-run` job'ı artık release-blocking runtime validation kapısıdır; installer sync, FastAPI web boot smoke, Alembic DB migration smoke ve `production-minimal-runtime-evidence` artifact'ini doğrular.
- **Ruff E501 / docstring / ASYNC borcu:** `line-length=100` korunur; sıfıra ulaşan E501, D200-D417 ve ASYNC240 global ignore'ları 2026-08-02'de kaldırılmıştır. Kurallar artık normal Ruff kapısında doğrudan uygulanır; `[tool.sidar.ruff_debt]` içindeki sıfır baseline ve `scripts/ci/check_ruff_debt_baseline.py` kapanış incelemesine kadar savunma katmanı olarak korunur.

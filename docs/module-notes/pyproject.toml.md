# pyproject.toml

- **Kaynak dosya:** `pyproject.toml`
- **Not dosyası:** `docs/module-notes/pyproject.toml.md`
- **Amaç:** Projenin ana paket ve metadata kaynağıdır (Single Source of Truth).
- **Not:** `core/`, `managers/` ve ses/RAG akışlarının çalışması için gerekli AI/medya paketleri (`openai`, `anthropic`, `litellm`, `chromadb`, `pgvector`, `SpeechRecognition`, `pyaudio`, `openai-whisper`, `yt-dlp`) ana `dependencies` altında tutulur; ek profiller (`extras`) isteğe bağlı genişletmeler için korunur.
- **Dev optimizasyonu:** `dev` grubunda `ruff` standart lint/format aracı olarak bırakılmış, `black` ve `flake8` kaldırılmıştır.
- **Lock üretimi:** `requirements*.txt` dosyaları bu dosyadan `uv pip compile` ile üretilir.
- **Durum:** UV tabanlı modern paket mimarisiyle uyumlu.
- **2026-08-15 torch reminder:** `torch 2.11.0` lock/policy penceresi için takip metadata'sı `pyproject.toml` içindeki `[tool.sidar.dependency_profile_plan.torch_upgrade_reminder]` bloğunda ve takvim girdisi `docs/reminders/torch-cve-review-2026-08-15.ics` dosyasında tutulur.
- **Production-minimal doğrulama:** CI `production-profile-dry-run` job'ı artık release-blocking runtime validation kapısıdır; installer sync, FastAPI web boot smoke, Alembic DB migration smoke ve `production-minimal-runtime-evidence` artifact'ini doğrular.
- **Ruff E501 / docstring / ASYNC borcu:** `line-length=100` korunur; global E501, D200-D417 ve ASYNC240 ignore'ları geçici legacy uyumluluk borcu olarak `[tool.sidar.ruff_debt]` altında tarihli takip edilir, E501 için `e501_debt_baseline` üst sınırı tutulur ve `scripts/ci/check_ruff_debt_baseline.py` baseline kapısıyla büyütülmez.

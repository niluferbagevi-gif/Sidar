# pyproject.toml

- **Kaynak dosya:** `pyproject.toml`
- **Not dosyası:** `docs/module-notes/pyproject.toml.md`
- **Amaç:** Projenin ana paket ve metadata kaynağıdır (Single Source of Truth).
- **Not:** AI/RAG sağlayıcıları (`openai`, `anthropic`, `gemini`, `litellm`, `rag`, `postgres`) ve dev araçları (`dev`) extras olarak buradan yönetilir.
- **Lock üretimi:** `requirements*.txt` dosyaları bu dosyadan `uv pip compile` ile üretilir.
- **Durum:** UV tabanlı modern paket mimarisiyle uyumlu.
# requirements.txt

- **Kaynak dosya:** `requirements.txt`
- **Not dosyası:** `docs/module-notes/requirements.txt.md`
- **Amaç:** `pyproject.toml` dosyasındaki ana bağımlılıkların `uv` ile derlenmiş, sürüm sabitlenmiş çıktı dosyasıdır.
- **Single Source of Truth:** Paket ekleme/silme işlemleri doğrudan `pyproject.toml` üzerinden yapılır; bu dosya elle düzenlenmez.
- **Üretim komutu:** `uv pip compile pyproject.toml --extra openai --extra anthropic --extra gemini --extra litellm --extra rag --extra postgres -o requirements.txt`
- **Durum:** UV mimarisiyle senkronize edildi ve `docs/module-notes` altında güncellendi.
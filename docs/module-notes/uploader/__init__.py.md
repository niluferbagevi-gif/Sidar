# `uploader/__init__.py` — Upload Aracı Paketi

- **Kaynak dosya:** `uploader/__init__.py`
- **Not dosyası:** `docs/module-notes/uploader/__init__.py.md`

**Amaç:** `github_upload.py`'nin yapı taşları. `github_upload.py` giriş noktası olarak kalır ve aynı adlı ince sarmalayıcılar işbirlikçileri (`run_command` ve kardeş yardımcılar) çağrı anında geçirir; testlerin `github_upload.*` üzerindeki monkeypatch'leri etkisini korur.

**Özellikler:**
- Yalnız paket docstring'i; mantık alt modüllerdedir.

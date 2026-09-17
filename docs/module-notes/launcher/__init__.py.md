# `launcher/__init__.py` — Sidar CLI Launcher Paketi

- **Kaynak dosya:** `launcher/__init__.py`
- **Not dosyası:** `docs/module-notes/launcher/__init__.py.md`

**Amaç:** `main.py`'nin giriş noktası kalmaya devam ettiği, ancak alttaki
mantığın (`launcher.process`, `launcher.selection`, `launcher.ui`,
`launcher.doctor`) odaklı modüllere bölündüğü paket kökü. `main.py`
geriye dönük uyumluluk için bu modüllere ince, monkeypatch-stabil
sarmalayıcılar tutar.

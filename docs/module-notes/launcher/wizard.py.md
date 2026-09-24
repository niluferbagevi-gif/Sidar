# `launcher/wizard.py` — Sihirbaz Seçenek Tabloları

- **Kaynak dosya:** `launcher/wizard.py`
- **Not dosyası:** `docs/module-notes/launcher/wizard.py.md`

**Amaç:** `main.run_wizard`'ın seçenek tabloları ve varsayılan menü anahtarı çözümü.
Soruların kendisi (`ask_choice`/`ask_text`) testler `main` üzerinde patch ettiği
için `main.py`'de kaldı.

**Özellikler:**
- `MODE_OPTIONS`, `PROVIDER_OPTIONS`, `LEVEL_OPTIONS`, `LOG_OPTIONS`.
- `wizard_default_keys(last_selection, *, cfg)` — son seçim varsa onu, yoksa
  config değerlerini (`AI_PROVIDER`, `ACCESS_LEVEL`) güvenli varsayılanlarla kullanır.
- `last_extra_args(last_selection)` — kayıtlı `extra_args` sözlüğü ya da `{}`.

# `launcher/ui.py` — Interaktif Terminal UI

- **Kaynak dosya:** `launcher/ui.py`
- **Not dosyası:** `docs/module-notes/launcher/ui.py.md`

**Amaç:** İnce launcher giriş noktasının kullandığı, başlatma orkestrasyonuna
sahip olmayan (rengi/metni parametre olarak alan) interaktif terminal UI
yardımcıları.

**Özellikler:**
- `print_banner(*, cyan, bold, reset, green)` — Sidar ASCII banner'ını basar.
- `ask_choice(...)`, `ask_text(...)`, `confirm(...)` — kullanıcıdan seçim/
  serbest metin/onay alan interaktif prompt yardımcıları.

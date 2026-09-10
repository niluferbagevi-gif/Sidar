# `launcher/selection.py` — Launch Seçimi Normalizasyon/Birleştirme

- **Kaynak dosya:** `launcher/selection.py`
- **Not dosyası:** `docs/module-notes/launcher/selection.py.md`

**Amaç:** `main.py`'den çıkarılan, kullanıcı/CLI/env kökenli başlatma
seçimlerini güvenli biçimde normalize eden yardımcılar. `cfg` parametre
olarak (import edilmek yerine) thread edilir — çağıranlar kendi güncel
config'ini (env reload'da yeniden atanan ve testlerde doğrudan monkeypatch
edilen `main.py`'nin `cfg` global'i dahil) çağrı anında çözer.

**Özellikler:**
- `safe_choice(value, default, allowed)`, `safe_text(...)`, `safe_port(...)`,
  `safe_host(...)` — geçersiz/tip-dışı girdilerde sessizce default'a düşen
  normalizasyon yardımcıları.
- `normalize_launch_selection(selection, *, cfg)`, `default_launch_selection(*, cfg)`,
  `apply_cli_overrides(...)` — kullanıcı seçimi + config + CLI override'larını
  tek bir tutarlı launch selection sözlüğünde birleştirir.

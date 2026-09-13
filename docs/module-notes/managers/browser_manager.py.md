# `managers/browser_manager.py` — Tarayıcı Otomasyon Yöneticisi

- **Kaynak dosya:** `managers/browser_manager.py`
- **Not dosyası:** `docs/module-notes/managers/browser_manager.py.md`

**Amaç:** Playwright öncelikli, Selenium fallback'li dinamik web
etkileşim katmanı (1217 satır); ajanların sayfa gezinme/tıklama/form
doldurma gibi görevlerinin altyapısı.

**Özellikler:**
- `BrowserSession` (dataclass) — tek bir tarayıcı oturumunun (sayfa,
  context, sürücü, mevcut URL) durumu.
- `BaseBrowserProvider` (ABC) — `start_session`/`goto`/`click` gibi
  soyut arayüz; `PlaywrightBrowserProvider` ve `SeleniumBrowserProvider`
  bunu somutlaştırır (Playwright kurulu değilse Selenium'a düşer).
- `BrowserManager` — oturum yaşam döngüsünü yönetir; yazma etkili
  aksiyonlar (`click_element`, `fill_form`, `select_option`) senkron
  çağrıda `_sync_hitl_guard()` ile bloklanır ve yalnızca `core/hitl.py`
  onay kapısından geçen async varyantları (`click_element_hitl`,
  `fill_form_hitl`, `select_option_hitl`, `_request_hitl_approval()`)
  üzerinden yürütülebilir — riskli tarayıcı etkileşimleri için
  fail-closed bir HITL zorunluluğu.

## İlgili modüller

`core/hitl.py`, `managers/youtube_manager.py`,
`managers/social_media_manager.py`.

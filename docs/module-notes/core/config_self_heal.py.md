# `core/config_self_heal.py` — Self-Heal Varsayılanları

- **Kaynak dosya:** `core/config_self_heal.py`
- **Not dosyası:** `docs/module-notes/core/config_self_heal.py.md`

**Amaç:** Otonom remediation/self-heal döngüsünün sınırlarını (`SELF_HEAL_MAX_PATCHES`,
`SELF_HEAL_PLAN_MAX_RETRIES`, batch boyutu, HITL eşiği vb.) ortam değişkenlerinden
okur; `config.py` sonucu `Config.self_heal_settings` olarak expose eder. Eski adı kök
`config_autonomy.py` idi; otonomi webhook ayarlarını tutan `core/config_autonomy.py`
ile çakışmaması için bu adla `core/` altına taşındı.

**Özellikler:**
- `load_self_heal_settings()` — `SIDAR_` önekli değişkenleri öncelikli okuyup
  önek olmayan legacy adlara düşen sözlük döndürür.

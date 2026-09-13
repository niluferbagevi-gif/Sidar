# `plugins/crypto_price_agent.py` — Kripto Fiyat Marketplace Eklentisi

- **Kaynak dosya:** `plugins/crypto_price_agent.py`
- **Not dosyası:** `docs/module-notes/plugins/crypto_price_agent.py.md`

**Amaç:** Basit bir kripto fiyat sorgulama ajanı (marketplace plugin
demosu); kimlik doğrulama gerektirmeyen, salt-okuma dış servis çağrısı
örneği.

**Özellikler:**
- `SYMBOL_MAP` — desteklenen sembol takma adlarını (`btc`, `eth`, `sol`
  ve tam adları) CoinGecko coin id'lerine eşler.
- `run_task(task_prompt)` — prompt'tan sembolü çıkarır
  (`_extract_symbol`), desteklenmiyorsa desteklenen listeyi döner,
  aksi halde CoinGecko `simple/price` uç noktasına `httpx.AsyncClient`
  ile (8sn zaman aşımı) istek atıp güncel USD fiyatını döner.
- `_extract_symbol(task_prompt)` — basit bir regex ile prompt'taki ilk
  alfabetik token'ı sembol adayı olarak alır, bulunamazsa `"btc"`'ye
  düşer.

## İlgili modüller

`plugins/manifest.py` (`crypto_price` manifesti, `external_services=("coingecko",)`).

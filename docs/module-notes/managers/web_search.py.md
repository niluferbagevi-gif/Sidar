# 3.15 `managers/web_search.py` — Web Arama Yöneticisi (387 satır)

**Amaç:** Tavily → Google → DuckDuckGo kademeli motor desteğiyle asenkron web araması.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l managers/web_search.py` çıktısına göre **387** olarak ölçülmüştür.

**Akıllı Motor Şelalesi (`auto`):** Tavily → Google Custom Search → DuckDuckGo sırasıyla denenir; anahtar eksikliği, kota/hata veya yanıt başarısızlığında sistem bir sonraki motora düşerek kesintisiz arama davranışı sağlar.

**Desteklenen Operasyonlar:**
- `search(query)`: Genel web araması
- `fetch_url(url)`: URL içerik çekme + BeautifulSoup HTML temizleme
- `search_docs(library, topic)`: Resmi dokümantasyon araması
- `search_stackoverflow(query)`: Stack Overflow araması

**Metin Sanitizasyonu (Token hijyeni):**
- Sonuç/snippet içerikleri `html.unescape` ile normalize edilerek HTML entity/artıklarının (`&amp;`, vb.) LLM bağlamını kirletmesi azaltılır.

**v2.8.0 DuckDuckGo Güvenlik İyileştirmeleri (Madde #10 Çözümü):**

`_search_duckduckgo()` içinde üç katmanlı güvenlik uygulandı:

```python
# 1. Dinamik AsyncDDGS kontrolü (versiyon değişikliği koruması)
if hasattr(duckduckgo_search, "AsyncDDGS"):
    results = await asyncio.wait_for(_async_search(), timeout=FETCH_TIMEOUT)
else:
    # AsyncDDGS yoksa (gelecek sürümler için) sync+thread fallback
    results = await asyncio.wait_for(
        asyncio.to_thread(_sync_search), timeout=FETCH_TIMEOUT)

# 2. Timeout koruması — her iki yol da wait_for ile sınırlı
# 3. Except sırası: asyncio.TimeoutError > Exception (Python best practice)
except asyncio.TimeoutError:  # Spesifik önce
    ...
except Exception as exc:       # Genel sonra
    ...
```

| Güvenlik Katmanı | Açıklama |
|---|---|
| Versiyon pinleme | `environment.yml`: `duckduckgo-search~=6.2.13` |
| `AsyncDDGS` dinamik kontrol | `hasattr()` ile mevcut sürümde async yol, gelecek sürümlerde sync yol |
| `asyncio.wait_for()` | Her iki arama yolu için `FETCH_TIMEOUT` sınırı (sessiz takılma engeli) |
| `asyncio.TimeoutError` handler | Spesifik timeout mesajı + `logger.warning` |

**Konfigürasyon:** `WEB_SEARCH_MAX_RESULTS` (5), `WEB_FETCH_TIMEOUT` (15sn), `WEB_SCRAPE_MAX_CHARS` (12000)

---

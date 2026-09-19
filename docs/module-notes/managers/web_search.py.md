# 3.15 `managers/web_search.py` — Web Arama Yöneticisi (387 satır)

## Rapor İçeriği (Taşınan Bölüm)

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
# 1. Yeni adıyla desteklenen DDGS istemcisi
from ddgs import DDGS

# 2. Senkron SDK event loop'u bloklamadan thread'de çalışır
thread_task = asyncio.create_task(asyncio.to_thread(_sync_search))
results = await asyncio.wait_for(thread_task, timeout=FETCH_TIMEOUT)

# 3. Except sırası: TimeoutError > Exception
except TimeoutError:  # Spesifik önce
    ...
except Exception as exc:       # Genel sonra
    ...
```

| Güvenlik Katmanı | Açıklama |
|---|---|
| Versiyon pinleme | `pyproject.toml`: `ddgs>=9.16.0,<10.0.0` |
| SDK geçişi | Yeniden adlandırılan `ddgs` paketi ve `DDGS` API'si kullanılır |
| `asyncio.to_thread()` | Senkron SDK çağrısı event loop'u bloklamaz |
| `asyncio.wait_for()` | `FETCH_TIMEOUT` sınırı sessiz takılmayı engeller |
| `TimeoutError` handler | Spesifik timeout mesajı + `logger.warning` |

**Konfigürasyon:** `WEB_SEARCH_MAX_RESULTS` (5), `WEB_FETCH_TIMEOUT` (15sn), `WEB_SCRAPE_MAX_CHARS` (12000)

---

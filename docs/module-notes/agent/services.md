# agent/services/

- **Kaynak dizini:** `agent/services/` (`__init__.py`, `response_service.py`,
  `tool_service.py`)
- **Not dosyası:** `docs/module-notes/agent/services.md`

## Amaç

`agent/sidar_agent.py`'nin geriye dönük uyumlu facade'ı için ayrıştırılmış,
duruma bağımlı olmayan iki saf yardımcı fonksiyon.

- **`response_service.py::parse_tool_call(raw)`:** LLM yanıtını legacy
  `{"tool": ..., "argument": ...}` sözlük sözleşmesine normalize eder. Önce
  yanıt gövdesindeki bir ```` ```json ... ``` ```` blok kalıbını ayıklar, sonra
  `json.loads` dener; ayrıştırma başarısız olursa veya sonuç `dict` değilse
  yanıtın tamamını `final_answer` argümanı olarak geri döner (asla istisna
  fırlatmaz). `tool` alanı eksikse varsayılan `final_answer` atanır.
- **`tool_service.py::execute_tool(tool, argument, *, resolve_handler)`:**
  Araç adını `_tool_{ad}` biçiminde bir handler adına çevirip
  `resolve_handler` callback'i üzerinden çözer (agent'ın kendi metot çözümleme
  mantığından bağımsız, test edilebilir bir dolaylama katmanı). Handler hem
  senkron hem `async` olabilir (`inspect.isawaitable` ile algılanır); sonuç
  her zaman `str`'e çevrilir. Boş araç adı veya bilinmeyen/çağrılamaz handler
  için `ValueError`/`TypeError` fırlatır.

İkisi de `agent/services/__init__.py` üzerinden re-export edilir;
`agent/sidar_agent.py` bu iki fonksiyonu doğrudan import edip kendi
`_parse_tool_call`/`_execute_tool` metotlarının gövdesinde çağırır.

## Test kapısı

`tests/unit/agent/test_sidar_agent.py`, `SidarAgent`'ın ilgili metotları
üzerinden bu iki servisi dolaylı olarak kapsıyor; ayrı bir
`agent/services/` test dosyası yok.

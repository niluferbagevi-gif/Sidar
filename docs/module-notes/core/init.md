# core/llm_client.py Teknik Notu

`LLMClient`, Sidar’ın LLM sağlayıcı soyutlama katmanıdır. Ollama ve Gemini için asenkron çağrı, stream ve JSON-modu davranışını tek API altında toplar.

## 1) Sorumluluklar

- `chat(...)` ile sağlayıcıya göre doğru backend’i seçmek (`ollama` / `gemini`).
- Stream ve non-stream çağrıları yönetmek.
- ReAct akışı için JSON mode kullanmak; özet gibi durumlarda düz metin moduna düşebilmek.
- Bağlantı hatalarında kullanıcıya anlamlı hata mesajı döndürmek.

## 2) Mimari Özellikler

- **Provider abstraction:** Üst katman `self.provider` dışında sağlayıcı detayı bilmez.
- **Structured output desteği:** Ollama payload’ında şema bazlı format zorlaması kullanılır.
- **Streaming dayanıklılığı:** akışta parçalı/eksik JSON satırlarına karşı decoder toleransı bulunur.
- **GPU farkındalığı:** Ollama çağrısında `USE_GPU` durumuna göre options alanı ayarlanır.

## 3) Bağlantılı Dosyalar

- Tüketen: `agent/sidar_agent.py`
- Ayar kaynağı: `config.py`
- Dolaylı tüketici: `web_server.py` (ajan üzerinden)

## 4) İyileştirme Alanı

- Sağlayıcı başına gözlemlenebilirlik metrikleri (request latency, token/s, hata sınıfı) artırılabilir.
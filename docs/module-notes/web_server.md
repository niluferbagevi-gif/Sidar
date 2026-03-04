# web_server.py Teknik Notu

`web_server.py`, Sidar’ın FastAPI tabanlı HTTP/SSE servis katmanıdır. Web arayüzü, oturum yönetimi, repo işlemleri, RAG işlemleri ve todo görünümü bu modül üzerinden sunulur.

## 1) Sorumluluklar

- FastAPI uygulamasını ve middleware zincirini kurmak.
- CORS kısıtları ve statik/vendor servislerini sağlamak.
- SSE üzerinden `/chat` akışını yayınlamak.
- Session, dosya, git/repo, RAG, todo ve metrik endpoint’lerini sunmak.

## 2) Runtime Modeli

- `cfg = Config()` ile config alınır.
- Ajan örneği lazy-init mantığıyla `get_agent()` içinde tekil (singleton benzeri) üretilir.
- `/chat` endpoint’i ajan yanıtlarını stream ederek frontend’e parça parça iletir.

## 3) Güvenlik/Dayanıklılık Özellikleri

- **Rate limit middleware:** `/chat`, mutating endpoint’ler ve ağır GET endpoint’ler için ayrı limit profilleri uygulanır.
- **TOCTOU koruması:** rate-limit sayaç güncellemesi `asyncio.Lock` içinde atomik yapılır.
- **Branch doğrulama:** `/set-branch` endpoint’inde regex doğrulaması ile branch adı kısıtlanır.
- **SSE hata dayanıklılığı:** istemci bağlantı kopmalarında `CancelledError`/`ClosedResourceError` beklenen akış olarak yönetilir.

## 4) Bilinen İyileştirme Alanları

- `/rag/search` içinde `agent.docs.search(...)` çağrısı doğrudan senkron çalışır; yoğun yükte event-loop gecikmesi üretebilir.
- Rate-limit sözlüğünde boşalan bucket anahtarları için ek eviction stratejisi değerlendirilebilir.

## 5) Bağlantılı Dosyalar

- `config.py`: host/port/provider/access-level/operasyon ayarları
- `agent/sidar_agent.py`: tüm iş mantığı ve araç çağrıları
- `web_ui/index.html`: endpoint tüketicisi (chat, todo, rag, repo)
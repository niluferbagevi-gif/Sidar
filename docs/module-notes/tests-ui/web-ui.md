# web_ui/index.html Teknik Notu

`web_ui/index.html`, Sidar’ın tek dosya tabanlı istemci arayüzüdür (chat, session, repo/branch, todo paneli, RAG modalı).

## 1) Sorumluluklar

- SSE üzerinden ajan yanıtlarını stream etmek ve mesaj geçmişini görselleştirmek.
- Session ve repo/branch seçim modallarını yönetmek.
- Todo paneli ve RAG belge/arama akışlarını backend endpoint’lerine bağlamak.
- Tema, kısayol, durum paneli gibi UX yardımcılarını sağlamak.

## 2) Teknik Özellikler

- `marked` + `highlight.js` ile markdown/code render.
- `escHtml(...)` ile bir çok kullanıcı verisi escape edilerek DOM’a yazılır.
- Polling (todo) + fetch tabanlı endpoint etkileşimi (`/todo`, `/rag/*`, `/status`, `/chat`).

## 3) Risk/İyileştirme Alanı

- Bazı render yolları `innerHTML` kullandığından sanitize katmanı (örn. DOMPurify) ile sertleştirme önerilir.
- UI script dosyası oldukça büyüktür; modüler JS yapısına ayrılması bakım ve test edilebilirliği artırır.

## 4) Bağlantılı Dosyalar

- `web_server.py`: endpoint sağlayıcısı
- `agent/sidar_agent.py`: davranış motoru (dolaylı)
- `managers/todo_manager.py`, `core/rag.py`: todo/rag backend davranışı

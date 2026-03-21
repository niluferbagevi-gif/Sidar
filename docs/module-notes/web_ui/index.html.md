# 3.18 `web_ui/` — Web Arayüzü (Toplam ~4.715 satır)

## Rapor İçeriği (Taşınan Bölüm)

> Not (Doğrulama): Güncel depoda `wc -l` ölçümü: `index.html=664`, `style.css=1806`, `app.js=827`, `chat.js=875`, `rag.js=131`, `sidebar.js=412` (**toplam 4.715**).

**Mimari Yapı (Modüler Vanilla JS SPA):**
- Monolitik tek-dosya yaklaşımı yerine sorumluluklar `app.js`, `chat.js`, `sidebar.js`, `rag.js` modüllerine ayrılmıştır.
- `index.html` sadece iskelet + modal katmanları + script yükleme sırasını taşır; davranış mantığı modüllerde tutulur.

**Dosya Yapısı:**

| Dosya | Satır | Sorumluluk |
|-------|------:|-----------|
| `index.html` | 664 | HTML iskeleti, auth overlay, modal/board container'lar, script yükleme noktaları |
| `style.css` | 1.806 | Tema (dark/light), layout sistemi, bileşen stilleri |
| `chat.js` | 875 | WebSocket chat akışı, event render, markdown + kod çıktısı işleme |
| `sidebar.js` | 412 | Oturum listesi, filtreleme, başlık düzenleme/silme |
| `rag.js` | 131 | RAG belge ekleme/listeleme/arama/silme UI |
| `app.js` | 827 | Auth flow, global state, tema/yardımcı kontroller, uygulama orkestrasyonu |
| **Toplam** | **4.715** | Modüler ve ayrışmış web istemcisi |

**Kimlik Doğrulama ve Oturum Koruması:**
- `AUTH_TOKEN_KEY` / `AUTH_USER_KEY` ile token + kullanıcı bağlamı istemci tarafında yönetilir.
- Auth overlay (`login/register`) akışı olmadan chat oturumu başlatılmaz; token olmayan istemci WebSocket tarafında yetkisiz kapatmayı tetikler.

**Gerçek Zamanlı Event Stream ve UX:**
- `chat.js` WebSocket üzerinden ajan olaylarını/araç adımlarını JSON event olarak işler; kullanıcının işlem durumunu canlı görmesini sağlar.
- Bağlantı kopmaları için yeniden bağlanma ve auth-hata ayrımı yapılır (ör. auth kaynaklı kapanış vs geçici kesinti).

**Güvenli Render ve Metin İşleme:**
- `marked` tabanlı markdown render + güvenli HTML temizleme (`sanitizeRenderedHtml`) ile çıktı yüzeyi korunur.
- Kod blokları ve uzun yanıtlar UI tarafında kontrollü biçimde parse edilip gösterilir.

**Yükleme Sırası (index.html → script tags):**
```html
<script src="/static/chat.js"></script>
<script src="/static/sidebar.js"></script>
<script src="/static/rag.js"></script>
<script src="/static/app.js"></script>
```

---

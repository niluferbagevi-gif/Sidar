# `web_ui/rag.js`

- **Kaynak dosya:** `web_ui/rag.js`
- **Not dosyası:** `docs/module-notes/web_ui/rag.js.md`
- **Kategori:** RAG belge deposu modal yönetimi
- **Çalışma tipi:** Tarayıcı tarafı JavaScript

## 1) Ne işe yarar?

`rag.js`, RAG modalının tüm kullanıcı akışını yönetir:

- Modal aç/kapat (`openRagModal`, `closeRagModal`)
- Tab geçişi (`ragTab`)
- Belge listeleme/filtreleme (`ragLoadDocs`)
- Belge silme (`ragDeleteDoc`)
- Dosya yolundan belge ekleme (`ragAddFile`)
- URL’den belge ekleme (`ragAddUrl`)
- RAG arama (`ragSearch`)
- Sonuç mesaj kutuları (`ragShowResult`)

## 2) Endpoint kullanımı

- `GET /rag/docs`
- `DELETE /rag/docs/{docId}`
- `POST /rag/add-file`
- `POST /rag/add-url`
- `GET /rag/search?q=...`

Tüm çağrılar auth-aware `fetchAPI` üzerinden yapılır.

## 3) Çalışma mantığı

- Modal açıldığında varsayılan sekme `belgeler` yapılır ve doküman listesi çekilir.
- Liste ekranında metin filtreleme başlık/kaynak alanına göre client-side uygulanır.
- Add-file ve add-url akışlarında butonlar işlem süresince disabled yapılır.
- Silme işlemi kullanıcı onayı (`confirm`) sonrası gerçekleştirilir.

## 4) Kullanım örnekleri

```js
openRagModal();
ragLoadDocs('migration');
ragSearch();
```

## 5) Bağımlılıklar

- Global yardımcılar: `fetchAPI`, `escHtml`
- DOM bileşenleri: `#rag-modal`, `#rag-doc-list`, `#rag-filter`, `#rag-add-result`, `#rag-search-out`

## 6) Dikkat edilmesi gerekenler

1. `onclick` string tabanlı event kullanımı (`ragDeleteDoc(...)`) id escaping hassasiyeti yaratabilir.
2. Büyük doküman listelerinde client-side filtreleme maliyeti artabilir.
3. Hata mesajları kullanıcıya doğrudan gösterildiğinden backend mesaj formatı önemlidir.

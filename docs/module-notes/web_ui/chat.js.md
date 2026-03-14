# `web_ui/chat.js`

- **Kaynak dosya:** `web_ui/chat.js`
- **Not dosyası:** `docs/module-notes/web_ui/chat.js.md`
- **Kategori:** Sohbet motoru + streaming + activity/todo panel
- **Çalışma tipi:** Tarayıcı tarafı JavaScript

## 1) Ne işe yarar?

`chat.js`, kullanıcı mesajının gönderiminden model yanıtının streaming olarak işlenmesine kadar sohbet akışının merkezidir.

Başlıca görevler:

- Görev girişinden mesaj üretimi (`startTask`, `sendMessage`, `sendText`)
- WebSocket bağlantısı (`/ws/chat`) ve canlı chunk işleme
- Streaming yanıtın UI’da güncellenmesi (`updateStreaming`, `finishStreaming`)
- Tool-call adımlarının görselleştirilmesi (`appendToolStep`)
- Activity Panel (ajan düşünce/araç/todo canlı akışı)
- Todo panel polling (`/todo`)
- Mesaj render/güvenlik yardımcıları (`escHtml`, `sanitizeRenderedHtml`)
- Dosya attach önizleme ve gönderim payload’ına ekleme

## 2) Ağ ve endpoint kullanımı

- WebSocket: `/ws/chat`
- HTTP (fetchAPI üzerinden):
  - `/chat` (metin gönderimi)
  - `/todo` (görev listesi/aktif görev sayısı)

Bağlantı kapanması, auth hatası ve reconnect davranışı dosya içinde yönetilir.

## 3) Çalışma akışı (özet)

1. Kullanıcı metin girer (`startTask`/`sendMessage`).
2. `sendText(...)` kullanıcı mesajını UI’a ekler ve model yanıtı için placeholder oluşturur.
3. WebSocket’ten gelen `chunk` parçaları `updateStreaming(...)` ile birleştirilir.
4. `tool_call`, `thought`, `status` alanları Activity Panel’e yansıtılır.
5. `done` sinyali ile `finishStreaming()` çağrılır ve mesaj finalize edilir.

## 4) Activity Panel ve Todo entegrasyonu

- Activity panel fonksiyonları: `apShow`, `apHide`, `apToggle`, `apDone`, `apSetThought`, `apAddTool`.
- Todo fonksiyonları: `fetchTodo`, `renderTodoPanel`, `updateTodoIndicator`, `startTodoPoll`.
- Sayfa `load` event’inde WebSocket bağlantısı ve todo polling başlatılır.

## 5) Kullanım örnekleri

### Örnek A — Programatik gönderim

```js
sendText('Bu repodaki son değişiklikleri özetle');
```

### Örnek B — Streaming iptali

```js
stopStreaming();
```

### Örnek C — Todo panel aç/kapat

```js
toggleTodoPanel();
```

## 6) Bağımlılıklar

- Harici JS: `marked`, `hljs` (render/highlight akışı)
- Diğer global fonksiyonlar/değişkenler:
  - `fetchAPI`, `showAuthOverlay`, `clearAuthState`, `showChatPanel`, `loadSessions`
- DOM: `#messages`, `#input-area`, `#activity-panel`, `#todo-panel` ve ilgili alt bileşenler

## 7) Dikkat edilmesi gerekenler

1. Bu dosya global değişken/state yoğunluğu taşır; modül sınırları gevşektir.
2. WebSocket auth kapanışlarında UI fallback davranışı (`handleExpiredSession`) kritik önemdedir.
3. `sanitizeRenderedHtml(...)` katmanı XSS risklerini azaltmak için render pipeline’ın parçasıdır.
4. Uzun süren stream/çok sayıda tool-call durumunda DOM büyümesi performansı etkileyebilir.
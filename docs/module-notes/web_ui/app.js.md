# `web_ui/app.js`

- **Kaynak dosya:** `web_ui/app.js`
- **Not dosyası:** `docs/module-notes/web_ui/app.js.md`
- **Kategori:** Web UI çekirdek bootstrap + auth + dashboard/telemetri
- **Çalışma tipi:** Tarayıcı tarafı JavaScript

## 1) Ne işe yarar?

`app.js`, Web UI’nin üst seviye orkestrasyon katmanıdır. Özellikle şu sorumlulukları üstlenir:

- Kimlik doğrulama state’i (`localStorage`) yönetimi
- Yetkili API çağrıları için ortak `fetchAPI(...)` yardımcı fonksiyonu
- Login/Register overlay akışı
- Kullanıcı profili ve admin tab görünürlüğü
- Admin istatistikleri ve LLM budget dashboard yükleme/gösterim
- Tema yönetimi (dark/light)
- Sistem sağlık/telemetri şeridi (`/health`, `/api/budget`) yenilemesi
- Git/model durum bilgisi ve status modal içeriği
- Global klavye kısayolları ve başlangıç (`DOMContentLoaded`) bootstrap
- Drag&drop RAG upload ve sohbeti Markdown indirme yardımcıları

## 2) Nerede / nasıl kullanılıyor?

- `web_ui/index.html` içinde script olarak yüklenir ve üst bar/overlay/modal butonlarının çoğu bu dosyadaki fonksiyonlara bağlıdır.
- `chat.js`, `sidebar.js`, `rag.js` gibi dosyalarla birlikte aynı global scope’u paylaşır.
- `window.fetchAPI = fetchAPI` ile diğer modüllere auth-aware HTTP çağrısı sağlar.

## 3) Önemli fonksiyon grupları

### A) Auth ve oturum yönetimi

- `getAuthToken`, `setAuthState`, `clearAuthState`, `getAuthUser`
- `showAuthOverlay`, `hideAuthOverlay`, `switchAuthTab`
- `syncCurrentUserFromAPI()` (`/auth/me`)

### B) Ortak API katmanı

- `fetchAPI(url, options)`:
  - Bearer token’ı otomatik header’a ekler
  - 401 durumunda oturum overlay’ini açar

### C) Dashboard/Admin

- `loadAdminStats()` / `renderAdminStats(...)` (`/admin/stats`)
- `loadBudgetDashboard()` / `renderBudgetDashboard(...)` (`/api/budget`)

### D) UI state ve yardımcılar

- Tema: `toggleTheme()`, `applyStoredTheme()`
- Sağlık şeridi: `refreshHealthStrip()`, `refreshLlmBudgetStrip()`
- Durum/model/git: `openStatus()`, `loadModelInfo()`, `loadGitInfo()`

### E) Etkileşim ve utility

- Bellek temizleme: `clearMemory()` (`/clear`)
- Kısayol modalı: `openShortcuts()`
- Drag&drop dosya upload: `uploadFileToRAG(file)` (`/api/rag/upload`)
- Sohbet indirme: `downloadChat()`

## 4) Kullanım örnekleri

### Örnek A — Token ile yetkili istek

```js
const res = await fetchAPI('/health');
const data = await res.json();
```

### Örnek B — Oturum düşürme

```js
clearAuthState();
showAuthOverlay('Oturum süresi doldu. Lütfen tekrar giriş yapın.');
```

### Örnek C — Sohbeti markdown indirme

```js
downloadChat();
```

## 5) Bağımlılıklar

- Tarayıcı API’leri: `fetch`, `localStorage`, `FormData`, `Blob`, DOM API
- Diğer global fonksiyonlar/değişkenler:
  - `escHtml`, `showTaskPanel`, `loadSessions`, `loadSessionHistory`
  - `isStreaming`, `stopStreaming`, `currentSessionId`, `apiUrl`
- Backend endpoint’leri:
  - `/auth/me`, `/admin/stats`, `/api/budget`, `/health`, `/clear`, `/api/rag/upload` vb.

## 6) Dikkat edilmesi gerekenler

1. `fetchAPI` global olarak dışa açıldığı için modüller arası coupling yüksektir.
2. `localStorage` state’i bozulursa (`sidar_user` parse hatası gibi) fallback ile `null` döner.
3. Bazı fonksiyonlar diğer JS dosyalarındaki global state’e bağımlıdır; script yükleme sırası önemlidir.
4. Dashboard/Admin render adımları ilgili DOM düğümleri yoksa sessizce no-op davranır.
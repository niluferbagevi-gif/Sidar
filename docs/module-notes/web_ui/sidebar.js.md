# `web_ui/sidebar.js`

- **Kaynak dosya:** `web_ui/sidebar.js`
- **Not dosyası:** `docs/module-notes/web_ui/sidebar.js.md`
- **Kategori:** Oturum/Repo/Branch sidebar ve panel geçişleri
- **Çalışma tipi:** Tarayıcı tarafı JavaScript

## 1) Ne işe yarar?

`sidebar.js`, Web UI’nin sol panel ve üst tab etkileşimlerini yönetir.

Ana sorumluluklar:

- Oturumları yükleme/listeleme/seçme/silme/yeni oturum oluşturma
- Oturum geçmişini çekip sohbet ekranına yükleme
- Görev/Sohbet/Dashboard/Admin panel geçişleri
- Repo seçimi modalı (`/repo-list`, `/set-repo`)
- Branch seçimi modalı (`/git-branches`, `/set-branch`)
- PR bar güncelleme ve akıllı PR tetikleme (`createSmartPR`)
- Oturum export (`md` / `json`)
- Mobil sidebar toggle

## 2) Endpoint kullanımı

- Session:
  - `GET /sessions`
  - `GET /sessions/{id}`
  - `POST /sessions/new`
  - `DELETE /sessions/{id}`
- Repo/Branch:
  - `GET /repo-list`
  - `POST /set-repo`
  - `GET /git-branches`
  - `POST /set-branch`

## 3) Önemli akışlar

### A) Oturum yönetimi

1. `loadSessions()` aktif oturum ve listeyi çeker.
2. `renderSessionList(...)` UI kartlarını basar.
3. `selectSession(id)` geçmişi yükler ve chat paneline geçer.

### B) Repo/branch değişimi

1. `openRepoModal()` / `openBranchModal()` listeleri yükler.
2. `selectRepo(name)` ve `selectBranch(name)` backend’e değişim isteği gönderir.
3. Başarılı sonuçta UI etiketleri + PR bar güncellenir.

### C) Export

- `exportSession('md'|'json')` aktif oturumu dosya olarak indirir.

## 4) Kullanım örnekleri

```js
await loadSessions();
await openRepoModal();
await selectBranch('feature/improve-docs');
exportSession('json');
```

## 5) Bağımlılıklar

- Global state/fonksiyonlar: `fetchAPI`, `currentSessionId`, `showTaskPanel`, `showChatPanel`, `quickTask`
- DOM: session listesi, repo/branch modal düğümleri, PR bar, nav tablar

## 6) Dikkat edilmesi gerekenler

1. Bu dosya, `app.js`/`chat.js` ile paylaşılan global değişkenlere bağımlıdır.
2. Repo/branch cache (`_cachedRepos`, `_cachedBranches`) stale veri riski taşıyabilir.
3. Export başlık üretimi DOM’daki aktif item text’ine bağlıdır.
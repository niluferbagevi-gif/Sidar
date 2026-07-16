# Sidar React UI

Mevcut `web_ui/` (vanilla JS) ile paralel çalışan React/Vite tabanlı modern frontend.
FastAPI `web_server.py`'nin WebSocket API'si ile tam uyumludur.

## Başlatma

```bash
cd web_ui_react
npm install
npm run dev         # http://localhost:5173 — FastAPI'ye proxy
```

## Production Build

```bash
npm run build       # web_ui_react/dist/ dizinine derler
npm run test        # Vitest watch modu
npm run test:run    # CI için tek seferlik test koşumu
npm run test:coverage # Coverage raporu üretir
npm run test:e2e    # Playwright ile WebSocket uçtan uca senaryoları
```

`web_server.py` otomatik olarak `web_ui_react/dist/` varsa onu, yoksa legacy `web_ui/` dizinini sunar.

## Proje Yapısı

```
src/
├── App.jsx                    # Kök bileşen — WS + store bağlantısı
├── main.jsx                   # ReactDOM giriş noktası
├── index.css                  # Global stiller (koyu tema)
├── hooks/
│   ├── useWebSocket.js        # WS bağlantı + akış yönetimi
│   └── useChatStore.js        # Zustand mesaj durumu
└── components/
    ├── ChatWindow.jsx          # Mesaj listesi + akış tamponu
    ├── ChatMessage.jsx         # Tek mesaj (Markdown + kod vurgulaması)
    ├── ChatInput.jsx           # Giriş alanı (Enter/Shift+Enter)
    └── StatusBar.jsx           # WS durum + yeni oturum butonu
```

## Teknoloji Seçimleri

| Paket | Neden |
|-------|-------|
| Vite | Hızlı HMR, sıfır config |
| React 18 | Concurrent rendering, Strict Mode |
| Zustand | Minimal global state (Redux olmadan) |
| react-markdown | Güvenli Markdown render |
| rehype-highlight | Kod blokları sözdizim renklendirme |

## Test Altyapısı

- `Vitest` + `@testing-library/react`: React SPA bileşenleri için native birim testleri.
- `jsdom`: Tarayıcı DOM API'lerini emüle ederek `App`, `ChatPanel` ve `AgentManagerPanel` gibi bileşenlerin davranışını doğrular.
- `Playwright`: `e2e/chat-websocket.spec.js` içinde token kaydetme, gerçek WebSocket handshake, presence güncellemesi ve stream yanıtını browser seviyesinde doğrular.
- Legacy `web_ui/` tarafındaki sesli durum yardımcıları `voice_live_utils.js` içine ayrıştırılmıştır; böylece fallback arayüzü için de saf JS birim testleri yazılabilir.

### CI tarayıcı smoke kapısı ve coverage görünürlüğü

- `run_tests.sh`, CI profilinde `RUN_FRONTEND_E2E=1` varsayılanıyla Playwright WebSocket smoke
  senaryolarını coverage sonrasında çalıştırır. Yerel hızlı akışta varsayılan `auto` değeridir:
  Node Playwright'ın beklediği Chromium executable cache'de hazırsa smoke kapısı otomatik çalışır;
  hazır değilse `run_tests.sh`, frontend bağımlılıkları kurulduktan sonra
  `npx --no-install playwright install chromium` ile cache'i bir kez hazırlamayı dener. Ubuntu 25+
  hostlarda bu çağrı sentetik `OS_RELEASE_PATH` ve `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64`
  fallback'iyle çalışır; diğer dağıtımlar koşulsuz override edilmez. Kurulum başarılıysa doğrulanan executable yolunu ve `package-lock.json` parmak izini git dışında tutulan
  `.playwright-installed` sentinel dosyasına yazar. Sonraki çalıştırmalar sentinel içindeki executable hâlâ
  mevcutsa ve bağımlılık kilidi değişmemişse Node cache çözümlemesini atlar ve smoke kapısını doğrudan
  etkinleştirir; stale sentinel otomatik silinir. Bu yerel otomatik indirmeyi kapatmak için
  `RUN_FRONTEND_E2E_AUTO_INSTALL=0 bash run_tests.sh`, manuel hazırlık için
  `cd web_ui_react && npx playwright install chromium`, açıkça zorlamak için
  `RUN_FRONTEND_E2E=1 bash run_tests.sh` kullanın. CI, HTML raporunu
  `web_ui_react/playwright-report/` altında artefakt olarak saklar.
- Vitest coverage kapsamı `src/**/*.{js,jsx}` olarak açıkça tanımlıdır. Terminal raporu tam kapsanan
  dosyaları da listeler (`skipFull: false`); böylece `%100` özetinin hangi dosyalardan oluştuğu görünürdür.
- Bundle budget kapısı CI profilinde varsayılan olarak `FRONTEND_BUNDLE_BUDGET=1` ile
  `npm run build:budget` çalıştırır; yerel hızlı frontend stage'inde opt-in kullanmak için
  `FRONTEND_BUNDLE_BUDGET=1 bash run_tests.sh --stage frontend` çalıştırın. Bu kapı
  Vite build sonrası React DOM chunk büyümesini, toplam JS boyutunu ve toplam gzip JS
  boyutunu izler. React DOM varsayılan limiti `SIDAR_REACT_DOM_CHUNK_BUDGET_KB=220` değeridir;
  opsiyonel toplam limitler için `SIDAR_TOTAL_JS_BUDGET_KB` ve `SIDAR_TOTAL_GZIP_BUDGET_KB`
  verilebilir. `SIDAR_BUNDLE_GZIP_TREND_WARN_KB` varsayılan `5` KB artış eşiğiyle önceki
  bundle raporuna göre toplam gzip büyümesini uyarı olarak raporlar; önceki rapor yolu
  `SIDAR_BUNDLE_BUDGET_PREVIOUS_REPORT_PATH` ile verilebilir. Her koşu en büyük 5 JS chunk'ı
  terminalde listeler ve makinece okunabilir raporu `artifacts/frontend-bundle-budget.json`
  dosyasına yazar. Chat markdown renderer ana chat mesajından lazy import edilir;
  `highlight.js/lib/core` ve sınırlı dil modülleri yalnız bu markdown chunk'ına dahildir.
- CI, backend `htmlcov/` artefaktıyla aynı görünürlük seviyesinde `frontend-coverage-report` artefaktını
  uyarı modunda yükler; `web_ui_react/coverage/`, HTML `lcov-report/`, `lcov.info` ve
  `coverage-final.json` dosyaları tek artefakt altında saklanır.


## Kimlik doğrulama ve admin görünürlüğü

- Bearer token girişi varsayılan olarak yalnızca sekme belleğinde tutulur; `localStorage` kullanımı XSS etkisini
  büyütebildiği için sadece kullanıcı "Bu cihazda kalıcı sakla" seçeneğini işaretlediğinde etkinleşir.
- API istemcisi `credentials: "include"` ile istek atar; backend HttpOnly cookie tabanlı kısa ömürlü oturum
  modeline geçtiğinde SPA aynı çağrı yolunu kullanabilir.
- Admin sekmeleri JWT içindeki `role=admin` veya `username=default_admin` bilgisiyle görünür olur. Aynı panel
  rotaları doğrudan açıldığında da UI guard gösterilir; gerçek yetkilendirme backend `require_admin_user` ve
  access-policy kontrollerinde kalır.

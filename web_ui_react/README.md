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
  `npx --no-install playwright install chromium` ile cache'i bir kez hazırlamayı dener ve başarılıysa
  doğrulanan executable yolunu ve `package-lock.json` parmak izini git dışında tutulan
  `.playwright-installed` sentinel dosyasına yazar. Sonraki çalıştırmalar sentinel içindeki executable hâlâ
  mevcutsa ve bağımlılık kilidi değişmemişse Node cache çözümlemesini atlar ve smoke kapısını doğrudan
  etkinleştirir; stale sentinel otomatik silinir. Bu yerel otomatik indirmeyi kapatmak için
  `RUN_FRONTEND_E2E_AUTO_INSTALL=0 bash run_tests.sh`, manuel hazırlık için
  `cd web_ui_react && npx playwright install chromium`, açıkça zorlamak için
  `RUN_FRONTEND_E2E=1 bash run_tests.sh` kullanın. CI, HTML raporunu
  `web_ui_react/playwright-report/` altında artefakt olarak saklar.
- Vitest coverage kapsamı `src/**/*.{js,jsx}` olarak açıkça tanımlıdır. Terminal raporu tam kapsanan
  dosyaları da listeler (`skipFull: false`); böylece `%100` özetinin hangi dosyalardan oluştuğu görünürdür.

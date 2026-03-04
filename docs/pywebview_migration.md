# PyWebView + Vite/React + GSAP/Three.js Geçiş Notu

Bu proje için geçiş **mümkün** ve teknik olarak sağlıklı bir yol.

## Önerilen Mimari

- **Backend (Python/FastAPI):** `web_server.py` çalışmaya devam eder.
- **Desktop Shell (Python/PyWebView):** `desktop_app.py` backend'i process olarak başlatır ve pencereyi açar.
- **Frontend (Vite/React):** Ayrı repo veya alt klasör olarak çalışır (`npm run dev` veya `dist` çıktısı).
- **Animasyon/3D:** GSAP ve Three.js doğrudan React tarafında kullanılır.

## Çalışma Modları

1. **Geliştirme modu**
   - Vite dev server: `http://127.0.0.1:5173`
   - `desktop_app.py` bu URL'yi PyWebView içinde açar.
2. **Üretim modu**
   - Vite build çıktısı: `dist/index.html`
   - `desktop_app.py --frontend-dist ...` ile dosya tabanlı açılış yapılır.

## Avantajlar

- UI bağımsız geliştirilir (React ekosistemi, HMR, modern tooling).
- Python iş mantığı korunur (agent/managers/core aynen kalır).
- İleride Electron/Tauri gibi alternatif shell'lere geçiş kolaylaşır.

## Riskler ve Dikkat

- CORS ve API base URL yönetimi frontend tarafında net olmalı.
- PyWebView paketleme hedefleniyorsa (tek exe/app), platform bazlı test gerekir.
- Three.js ağır sahneleri için GPU/driver farklılıkları masaüstünde test edilmelidir.

## Bu repoda yapılan başlangıç adımı

- `desktop_app.py` eklendi.
- `main.py` içindeki başlatıcıya `desktop` modu eklendi.
- README'ye desktop kullanım notları eklendi.


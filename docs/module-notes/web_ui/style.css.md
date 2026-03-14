# `web_ui/style.css`

- **Kaynak dosya:** `web_ui/style.css`
- **Not dosyası:** `docs/module-notes/web_ui/style.css.md`
- **Kategori:** Web UI stil sistemi (tema + layout + bileşen stilleri)
- **Çalışma tipi:** CSS

## 1) Ne işe yarar?

`style.css`, Web UI’nin görsel tasarım katmanını uçtan uca tanımlar.

Öne çıkan kapsam:

- Tema tokenları (`:root`, `data-theme="light"`) ve renk sistemi
- Ana sayfa layout’u (topbar, sidebar, içerik alanları)
- Sohbet bileşenleri (message bubble, code block, toolbar, streaming görünümü)
- Modal stilleri (repo/branch/status/shortcuts/rag)
- Dashboard/Admin tabloları ve metrik kartları
- Activity panel, todo panel, notice/pill bileşenleri
- RAG modalı ve doküman listesi
- Responsive kırılımlar (mobil sidebar, taşan alanlar)

## 2) Nerede kullanılır?

- `web_ui/index.html` içinde `/static/style.css` olarak yüklenir.
- `app.js`, `chat.js`, `rag.js`, `sidebar.js` dosyalarının class/id manipülasyonları bu dosyadaki selector’larla çalışır.

## 3) Stil organizasyonu (yüksek seviye)

1. Tema değişkenleri ve reset benzeri temel kurallar
2. Topbar + nav + yardımcı buton stilleri
3. Sidebar ve session item görünümleri
4. Chat panel + composer + mesaj render stilleri
5. Modal ve özel paneller (RAG, Activity, Todo)
6. Dashboard/Admin bileşenleri
7. Responsive medya sorguları

## 4) Kullanım örnekleri

- Tema değişimi `document.documentElement.setAttribute('data-theme', 'light')` ile tetiklenir; light theme override’ları devreye girer.
- `.open`, `.active`, `.visible` gibi class’lar JS tarafından eklenip çıkarılarak panel/modal durumları yönetilir.

## 5) Bağımlılıklar

- HTML class/id sözleşmesi (`index.html`)
- JS tarafındaki class toggle davranışları (`app.js`, `chat.js`, `rag.js`, `sidebar.js`)
- Highlight.js/Markdown render çıktılarındaki element yapısı

## 6) Dikkat edilmesi gerekenler

1. Dosya büyük bir monolitik CSS yapısında; değişikliklerde selector çakışması riski vardır.
2. Tema override blokları ile ana tokenların tutarlılığı korunmalıdır.
3. JS tarafında kullanılan state class’larının (`active/open/visible`) CSS karşılıkları bozulmamalıdır.
4. Performans için çok derin selector’lardan kaçınmak ve ortak utility sınıflarını tercih etmek önerilir.

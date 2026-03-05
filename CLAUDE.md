# CLAUDE.md

Bu dosya, Sidar ile Claude Code benzeri çalışma biçimleri arasında uyum kurmak için
**rehber** niteliğinde notlar içerir. Mutlak araç adı garantisi vermez.

## Uyumluluk Notları (Referans Eşleme)

Aşağıdaki eşlemeler birebir zorunlu değildir; çalışma ortamındaki araç setine göre
**en yakın karşılık** seçilmelidir.

- Görev takibi (`todo_*`) → Claude Code `Todo*` akışı
- Desen/içerik arama (`rg`, dosya tarama araçları) → `Glob` / `Grep`
- Kabuk komutu yürütme (`exec_command` vb.) → `Bash`
- Dosya okuma/yazma/düzenleme araçları → `Read` / `Write` / `Edit`
- Web arama/URL çekme araçları → `WebSearch` / `WebFetch`
- PR oluşturma araçları (varsa) → akıllı PR akışı

> Not: Opsiyonel yetenekler (ör. PR otomasyonu) her dağıtımda bulunmayabilir.

## Hiyerarşi

- `SIDAR.md` → proje-geneli ana çalışma sözleşmesi
- `CLAUDE.md` → Claude ekosistemiyle zihinsel model eşleme notları
- Daha alt klasördeki talimat dosyaları, kapsam dahilinde daha yüksek önceliklidir.

## İzin ve Güvenlik Modeli

- Sidar'da yetkiler `.env` içindeki `ACCESS_LEVEL` üzerinden belirlenir.
- `full` → yazma + shell dahil geniş yetki
- `sandbox` → sınırlı yazma, kısıtlı çalıştırma
- `restricted` → yalnızca okuma/analiz

## Bakım İlkesi

- Bu dosyada yalnızca **genel eşleme prensipleri** tutulmalı.
- Ortama özel kesin araç adları/prosedürler `SIDAR.md` içinde tutulmalı.
- Yeni araç eklendiğinde bu dosyada "zorunlu birebir eşleme" dili yerine
  "yakın karşılık" dili korunmalı.
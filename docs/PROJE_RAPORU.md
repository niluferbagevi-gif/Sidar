# Sidar Projesi — Rapor İndeksi

> **Aktif ürün/runtime baseline:** v5.2.0
>
> **Belge durumu:** Güncel giriş noktası
>
> **Son yapısal güncelleme:** 2026-08-01

Bu dosya artık 150 KB üzerindeki tek parça raporun navigasyon indeksidir. Ayrıntılı
bölümler konu bazında `docs/project-report/` altında tutulur. Yeni katkı sağlayanlar
güncel sistem mimarisi için önce [`ARCHITECTURE.md`](ARCHITECTURE.md), operasyonel
sözleşmeler için [`TEKNIK_REFERANS.md`](TEKNIK_REFERANS.md) dosyasını kullanmalıdır.

## Belge önceliği

1. **Güncel mimari:** [`ARCHITECTURE.md`](ARCHITECTURE.md) — v5.2.0 runtime bileşenleri ve sahiplik sınırları.
2. **Teknik/operasyonel sözleşme:** [`TEKNIK_REFERANS.md`](TEKNIK_REFERANS.md).
3. **Kapsamlı proje raporu bölümleri:** aşağıdaki konu dosyaları.
4. **Tarihsel faz raporları:** `SIDAR_v5_0_MIMARI_RAPORU.md` ve `SIDAR_v5_1_MIMARI_RAPORU.md`; güncel API/dosya adı kaynağı değildir.

## Bölümler

| Bölümler | Dosya | Kapsam |
| --- | --- | --- |
| 1–4 | [`01-genel-bakis-ve-mimari.md`](project-report/01-genel-bakis-ve-mimari.md) | Genel bakış, dosya yapısı, modüller ve mimari değerlendirme |
| 5–8 | [`02-guvenlik-kalite-ve-bagimliliklar.md`](project-report/02-guvenlik-kalite-ve-bagimliliklar.md) | Güvenlik, test/coverage, bağımlılıklar ve hacim özeti |
| 9–10 | [`03-bagimlilik-ve-veri-akislari.md`](project-report/03-bagimlilik-ve-veri-akislari.md) | Modül bağımlılıkları, event/P2P ve veri akışları |
| 11–12 | [`04-teknik-borc-ve-yapilandirma.md`](project-report/04-teknik-borc-ve-yapilandirma.md) | Aktif teknik borç görünümü ve ortam değişkenleri |
| 13–15 | [`05-mimari-evrim-ve-yol-haritasi.md`](project-report/05-mimari-evrim-ve-yol-haritasi.md) | Tarihsel mimari evrim, roadmap ve gereksinim matrisi |
| 16–18 | [`06-operasyon-sorun-giderme-ve-gecmis.md`](project-report/06-operasyon-sorun-giderme-ve-gecmis.md) | Observability, troubleshooting ve session geçmişi |

## Aktif kalite özeti

- Coverage Quality Gate kaynağı `pyproject.toml` olup güncel ratchet `fail_under = 100` ve branch coverage açıktır.
- Runtime dotenv zinciri `.env` → `.env.advanced` → ortama özel katman → `DOTENV_FILE` → `SIDAR_KEYS_FILE` sırasını izler; repo dışı varsayılan secret dosyası `~/.sidar_keys.env` değeridir.
- Yerel `production_ready=true`, self-hosted GPU kanıtını kapsamaz; merge/release kararı CI'daki GPU evidence policy ve production-readiness aggregate sonucuna bağlıdır.

## Güncelleme kuralı

Yeni ayrıntılı içerik ilgili bölüm dosyasına eklenmelidir. Yeni bir güncel mimari
sözleşme önce `ARCHITECTURE.md` içinde değiştirilmelidir; session kayıtları
[`06-operasyon-sorun-giderme-ve-gecmis.md`](project-report/06-operasyon-sorun-giderme-ve-gecmis.md)
dosyasına eklenir. Bu indeks yeniden monolitik rapora dönüştürülmemelidir.

# 3.16 `managers/package_info.py` — Paket Bilgi Yöneticisi (322 satır)

**Amaç:** PyPI, npm ve GitHub Releases gerçek zamanlı sorgusu.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l managers/package_info.py` çıktısına göre **322** olarak ölçülmüştür.

**Özellikler:**
- `pypi_info(package)`: Sürüm, lisans, GitHub URL, son güncelleme tarihi
- `pypi_compare(package, version)`: Mevcut kurulu sürüm ile son sürüm karşılaştırması
- `npm_info(package)`: npm Registry paket bilgisi
- `github_releases(owner/repo)`: GitHub Releases listesi
- `github_latest_release(owner/repo)`: Son release bilgisini hızlı döndürür

**Asenkron Ağ Katmanı (httpx):**
- Tüm dış istekler `httpx.AsyncClient` ile `async/await` akışında çalışır; ajan döngüsü bloklanmaz.
- Ortak `_get_json()` yardımcı metodu timeout/bağlantı hatalarını standartlaştırır.

**TTL Tabanlı Akıllı Önbellek:**
- `PACKAGE_INFO_CACHE_TTL` (varsayılan 1800 sn) ile in-memory cache (`_cache_get`/`_cache_set`) kullanılır.
- Aynı paket sorgularında gereksiz dış API çağrıları azaltılarak latency ve rate-limit baskısı düşürülür.

**Semantik Sürüm Doğrulama:**
- `packaging.version.Version` / `InvalidVersion` ile sürüm metinleri normalize edilir.
- `_is_prerelease()` ve `_version_sort_key()` üzerinden pre-release/bozuk sürüm durumları güvenli fallback ile ele alınır.

---

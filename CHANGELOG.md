# Sürüm Geçmişi (Changelog)

## [v2.7.0] - 2026-03-07
Bu sürümde asenkron güvenlik, performans ve stabilite iyileştirmelerine odaklanılmıştır.

### ✅ Çözülen Yüksek Öncelikli Sorunlar
* **`core/rag.py` (Thread-Safety):** `_chunk_text()` içindeki geçici sınıf değişkeni değişimi lokal değişkenlere alınarak race condition engellendi. Sıfıra bölme ve sonsuz döngü koruması eklendi.
* **`core/rag.py` (Performans):** `_bm25_search()` içindeki skor hesaplaması `_write_lock` kapsamı dışına çıkarılarak thread bloklanması önlendi.
* **`agent/sidar_agent.py` (Cache Güvenliği):** `_instructions_cache` okuma/yazma işlemleri `threading.Lock` ile asenkron çakışmalara karşı koruma altına alındı.

### ✅ Çözülen Orta Öncelikli Sorunlar
* **`web_server.py` (Rate Limiting):** İstek sınırlandırması `defaultdict` yerine `cachetools.TTLCache` entegrasyonu ile kalıcı hale getirildi.
* **`core/memory.py` (Token Optimizasyonu):** Tahmini token hesabı yerine `tiktoken` kütüphanesi ile gerçek tokenizer entegrasyonu yapıldı.
* **`docker-compose.yml` (Güvenlik):** `sidar-web` ve `sidar-web-gpu` servislerinden `/var/run/docker.sock` erişimi kaldırılarak container escape zafiyeti giderildi.
* **`managers/github_manager.py` (API Güvenliği):** `list_commits` metodunda limit aşımlarında kullanıcıya açık uyarı dönecek şekilde düzenleme yapıldı.

### ✅ Çözülen Düşük Öncelikli / Teknik Borçlar
* **`agent/auto_handle.py`:** Çok adımlı regex kalıbına İngilizce bağlaçlar (`first`, `then`, `step`, vb.) eklendi.
* **`config.py`:** İçe aktarma anında çalışan dizin oluşturma komutları `__main__` koruması altına alınarak test ortamı izole edildi.

# 3.14 `managers/system_health.py` — Sistem Sağlık Yöneticisi (475 satır)

## Rapor İçeriği (Taşınan Bölüm)

**Amaç:** CPU/RAM/GPU/disk donanım izleme ve VRAM optimizasyonu.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l managers/system_health.py` çıktısına göre **475** olarak ölçülmüştür.

**Bağımlılıklar (opsiyonel):**
- `psutil`: CPU, RAM ve disk metrikleri
- `torch`: CUDA mevcutluğu, VRAM kullanım bilgisi, `empty_cache()`
- `pynvml`: GPU sıcaklık, anlık kullanım yüzdesi, sürücü sürümü

**Derin GPU/VRAM Gözlemi:**
- `get_gpu_info()` her GPU için cihaz adı, compute capability, ayrılan/rezerve VRAM, toplam VRAM, sıcaklık ve utilization yüzdesi döndürür.
- `_get_driver_version()` öncelikle pynvml ile sürücü sürümünü alır; gerekirse `nvidia-smi` fallback yolunu kullanır.

**Graceful Degradation (Donanım bağımsız çalışma):**
- `torch`/`pynvml`/`psutil` modülleri yoksa servis çökmez; ilgili alt metrikler güvenli fallback değerleriyle raporlanır.
- WSL2/NVIDIA sürücü kısıtlarında pynvml hataları kritik kabul edilmez, CPU/RAM odaklı gözlem akışı devam eder.

**Disk Darboğazı Takibi:**
- `get_disk_usage()` ile çalışma dizini için kullanılan/toplam/boş disk ve yüzde kullanım bilgisi üretilir.
- `full_report()` çıktısına disk kullanım satırları eklenerek kapasite doluluk riskleri görünür hale getirilir.

**Operasyonel API'ler:**
- `full_report()`: CPU, RAM, disk, GPU ve sürücü bilgilerini tek raporda sunar.
- `optimize_gpu_memory()`: `torch.cuda.empty_cache()` + `gc.collect()` ile VRAM boşaltır; `try-finally` ile GC her koşulda çalışır.
- `update_prometheus_metrics()`: metrikleri `Gauge` nesnelerine aktarır; `prometheus_client` yoksa sessizce atlar.
- `close()`: pynvml kapanışını güvenli şekilde yapar (atexit ile de çağrılır).

---

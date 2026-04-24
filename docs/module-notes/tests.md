# tests/ klasörü özeti

Bu not, **mevcut depo durumunu** (2026-04-09) yansıtır ve eski “coverage push” döneminden kalan
tek seferlik/geçici dosya adlarını referans almaz.

## Güncel metrikler

- `test_*.py` desenine uyan toplam test dosyası: **90**
- Katman dağılımı:
  - `tests/unit`: **77**
  - `tests/integration`: **7**
  - `tests/quality`: **2**
  - `tests/smoke`: **2**
  - `tests/e2e`: **1**
  - `tests/performance`: **1**

## Mimari kural: anti-fragmentation

- Test dosyaları modül bazlı isimlendirilir: `tests/unit/<modul>/test_<davranis>.py`
- Geçici/acele coverage dosyaları (`test_quick_*`, `test_*_improvements`, `test_*_runtime` gibi)
  kalıcı test mimarisine dahil edilmez.
- Aynı modül için tekrar eden test dosyaları yerine tek odaklı dosya kullanılır.

## Sidar agent özel notu

- Sidar davranış testleri tek bir dosyada toplanmıştır:
  - `tests/unit/agent/test_sidar_agent.py`
- Eski parçalı adlandırma örnekleri (`test_sidar.py`, `test_sidar_improvements.py`,
  `test_sidar_md_improvements.py`, `test_sidar_agent_runtime.py`) güncel test ağacında yoktur.

## Operasyonel takip

- Bu doküman sprint başında test ağacından yeniden üretilmeli/güncellenmelidir.
- Yeni test eklerken önce modül klasörü belirlenmeli, sonra mevcut dosyaya genişletme
  mümkünse yeni dosya açılmamalıdır.

## Performance benchmark baseline yönetimi

- `tests/performance` altında bulunan benchmark testleri için düzenli baseline kaydı alın.
- Önerilen komut:
  - `pytest tests/performance/ --benchmark-save=baseline_master`
- Yeni performans değişikliklerinde karşılaştırma için:
  - `pytest tests/performance/ --benchmark-compare=baseline_master`
- İsimlendirme önerisi:
  - Ana dal için `baseline_master`
  - Sürüm/sprint için `baseline_<release_tag>` (ör. `baseline_v5_2_0`)

# 3.7 `agent/definitions.py` — Ajan Tanımları (165 satır)

## Rapor İçeriği (Taşınan Bölüm)

**Amaç:** `SIDAR_SYSTEM_PROMPT` sistem istemini barındırır.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l agent/definitions.py` çıktısına göre **165** olarak ölçülmüştür.

**Sistem İstemi Bölümleri:**

| Bölüm | İçerik |
|-------|--------|
| Geriye dönük uyumluluk listeleri | `SIDAR_KEYS` ve `SIDAR_WAKE_WORDS` sabitleri |
| KİŞİLİK | Analitik, minimal, veriye dayalı, güvenliğe şüpheci |
| MİSYON | Dosya erişimi, GitHub senkronizasyonu, kod yönetimi, teknik denetim |
| GÜNCEL RUNTIME KİMLİĞİ | Varsayılan port/model bilgileri ve `get_config` ile doğrulama notu |
| BİLGİ SINIRI | Ağustos 2025 sonrası için tahmin yasağı; `web_search` / `pypi` zorunlu |
| HALLUCINATION YASAĞI | Sistem değerlerini (versiyon, model, yol) ASLA uydurma; `get_config` kullan |
| DOSYA ERİŞİM STRATEJİSİ | `glob_search` → `read_file` → `patch_file` sırası |
| GÖREV TAKİP | Çok adımlı görevlerde `todo_write` zorunlu |
| SIDAR.md | Proje özel talimatların otomatik yüklenmesi |
| İLKELER | PEP 8, UTF-8, test doğrulama ve fail-closed yaklaşımı |
| DÖNGÜ YASAĞI | Aynı araç 2 kez çağrılmaz; tek adımlı araçlar listelendi |
| HATA KURTARMA | Dosya/patch/izin/web/GitHub hataları için toparlanma adımları |
| ARAÇ KULLANIM STRATEJİLERİ | Her araç için ne zaman / hangi argüman kullanılacağı |
| ARAÇ KULLANIMI (JSON FORMATI) | Yanıtların zorunlu JSON şeması (`thought`, `tool`, `argument`) |
| ÖRNEK JSON YANITLARI | 5 örnek senaryo |

---

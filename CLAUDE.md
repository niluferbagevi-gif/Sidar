# CLAUDE.md — Sidar Geliştirici Rehberi

Bu dosya, Sidar projesinin derleme, çalıştırma, test ve kodlama standartlarını özetler.

## 📌 Proje Bağlamı (Güncel Durum)

- **Üretim Omurgası:** `v3.0.0` multi-agent çekirdek aktif; dokümantasyon anlatısı `v3.2.0` Autonomous LLMOps ve `v4.2.0` operasyonel kapanış notlarıyla genişletildi.
- **Mimari:** Multi-Agent Supervisor + doğrudan P2P handoff destekli Swarm, FastAPI, async DB erişimi, Redis/Prometheus/Grafana observability.
- **Kalite Durumu:** Açık kritik / yüksek / orta / düşük audit bulgusu yok; Zero-Debt hedefi korunur.

## 🛠 Temel Komutlar

### Kurulum ve Başlatma
- **Sistemi Başlat (Ana):** `python main.py`
- **Hızlı Web Başlatma:** `python main.py --quick web --host 0.0.0.0 --port 7860`
- **Hızlı CLI Başlatma:** `python main.py --quick cli`
- **Doğrudan Web Sunucu:** `python web_server.py --host 0.0.0.0 --port 7860`
- **Docker ile Ayağa Kaldır:** `docker compose up --build`

### Test ve Denetim
- **Tüm Testleri Çalıştır:** `pytest`
- **Belirli Testi Çalıştır:** `pytest tests/test_sidar.py`
- **Kapsam Analizi:** `pytest --cov=.`

### Veritabanı ve Migration
- **Veritabanı Şemasını Güncelle (PostgreSQL/SQLite):** `alembic upgrade head`
- **Yeni Migration Oluştur:** `alembic revision --autogenerate -m "aciklama"`

## 💻 Kodlama Standartları

- **Asenkron Mimari:** Ağ ve I/O odaklı işlemler event-loop'u bloklamayacak şekilde `async/await` + `asyncio.to_thread` prensibiyle yazılmalıdır.
- **Non-Blocking Operasyon:** Audit log yazımı, judge değerlendirmesi, active learning sinyalleri ve metrik toplama gibi işler mümkün olduğunda arka plan görevi veya bağımsız task olarak tetiklenmelidir.
- **Veri Güvenliği:** Dosya işlemlerinde UTF-8 (`encoding="utf-8"`) kullanılmalı; Türkçe karakterler korunmalıdır.
- **Güvenlik:** Sandbox fail-closed yaklaşımı esastır. Güvenli yürütme koşulları sağlanamazsa işlem reddedilmelidir.
- **SQL Hijyeni:** SQL sorguları parameterized olmalı; f-string veya ham string birleştirme ile dinamik SQL üretilmemelidir.
- **Yapılandırma:** Statik/hardcoded değerler yerine merkezi `config.py` / `.env` alanları kullanılmalıdır.
- **Port Standardı:** Varsayılan API/Web portu **7860**'tır.
- **Zero-Debt Disiplini:** Yeni kod; tip ipuçları, doğrulama testleri ve ilgili dokümantasyon güncellemesi olmadan tamamlanmış sayılmaz.

## 🤖 Ajan ve Komut Davranışı

- Sidar çoklu yönetici ve araç katmanlarıyla çalışır (dosya, paket, web, GitHub, RAG, sağlık).
- Nokta önekli sistem komutları desteklenir: `.status`, `.health`, `.clear`, `.audit`, `.gpu`.
- Geniş/kritik değişikliklerde görev takibi (`todo_*`) ve doğrulama testleri birlikte yürütülmelidir.

## 🔐 Erişim ve Güvenlik Seviyeleri

- `restricted`: yalnızca okuma/analiz.
- `sandbox`: sınırlı yazma + izole kod yürütme.
- `full`: geniş yazma + shell/otomasyon yetkileri.

Güvenlik kontrollerinde proje kökü dışına taşma, traversal/symlink riskleri ve hassas yollar (`.env`, `sessions/`, `.git/`) engellenmelidir.
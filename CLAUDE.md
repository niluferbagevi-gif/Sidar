# CLAUDE.md — Sidar Geliştirici Rehberi

Bu dosya, Sidar projesinin derleme, çalıştırma, test ve kodlama standartlarını özetler.

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
- **Veri Güvenliği:** Dosya işlemlerinde UTF-8 (`encoding="utf-8"`) kullanılmalı; Türkçe karakterler korunmalıdır.
- **Güvenlik:** Sandbox fail-closed yaklaşımı esastır. Güvenli yürütme koşulları sağlanamazsa işlem reddedilmelidir.
- **Yapılandırma:** Statik/hardcoded değerler yerine merkezi `config.py` / `.env` alanları kullanılmalıdır.
- **Port Standardı:** Varsayılan API/Web portu **7860**'tır.

## 🤖 Ajan ve Komut Davranışı

- Sidar çoklu yönetici ve araç katmanlarıyla çalışır (dosya, paket, web, GitHub, RAG, sağlık).
- Nokta önekli sistem komutları desteklenir: `.status`, `.health`, `.clear`, `.audit`, `.gpu`.
- Geniş/kritik değişikliklerde görev takibi (`todo_*`) ve doğrulama testleri birlikte yürütülmelidir.

## 🔐 Erişim ve Güvenlik Seviyeleri

- `restricted`: yalnızca okuma/analiz.
- `sandbox`: sınırlı yazma + izole kod yürütme.
- `full`: geniş yazma + shell/otomasyon yetkileri.

Güvenlik kontrollerinde proje kökü dışına taşma, traversal/symlink riskleri ve hassas yollar (`.env`, `sessions/`, `.git/`) engellenmelidir.

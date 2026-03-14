# 3.11 `managers/security.py` — Güvenlik Yöneticisi (290 satır)

## Rapor İçeriği (Taşınan Bölüm)

**Amaç:** OpenClaw erişim kontrol sistemi — 3 katmanlı güvenlik.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l managers/security.py` çıktısına göre **290** olarak ölçülmüştür.

**Erişim Seviyeleri:**

| Seviye | Okuma | Yazma | REPL | Shell |
|--------|-------|-------|------|-------|
| `restricted` (0) | ✓ | ✗ | ✗ | ✗ |
| `sandbox` (1) | ✓ | Yalnızca `/temp` | ✓ | ✗ |
| `full` (2) | ✓ | Proje kökü altı | ✓ | ✓ |

**Hard-Gate Güvenlik Katmanları:**

1. **Path Traversal + Sistem Dizin Koruması:** `_DANGEROUS_PATH_RE` ile `../`, `/etc/`, `/proc/`, `/sys/`, `C:\Windows`, `C:\Program Files` kalıpları doğrudan engellenir.
2. **Hassas Dosya/Dizin Kara Listesi:** `_BLOCKED_PATTERNS` üzerinden `.env`, `sessions/`, `.git/`, `__pycache__/` erişimleri seviyeden bağımsız bloke edilir.
3. **Symlink Kaçış Koruması:** `_resolve_safe()` içinde `Path.resolve()` ile gerçek hedef hesaplanır; base_dir dışına çıkan sembolik bağlantılar reddedilir.
4. **Bilinmeyen Seviye Normalize (Fail-Safe):** Geçersiz erişim seviyesi adları güvenli varsayılan `sandbox` değerine düşürülür.

**İzin Karar API'leri:**
- `check_read(path)`: yol + blacklist + symlink doğrulaması sonrası okuma izni.
- `check_write(path)`: erişim seviyesine göre (`restricted`/`sandbox`/`full`) ve güvenlik bariyerlerine göre yazma izni.
- `check_terminal()`: REPL/terminal çağrılarına seviye tabanlı izin.
- `check_shell()`: yalnızca `full` seviyesinde kabuk komutlarına izin.

---

# `scripts/install_host_sandbox.sh`

- **Kaynak dosya:** `scripts/install_host_sandbox.sh`
- **Not dosyası:** `docs/module-notes/scripts/install_host_sandbox.sh.md`
- **Kategori:** Host güvenlik runtime kurulumu (gVisor/Kata)
- **Çalışma tipi:** Bash + gömülü Python (JSON düzenleme)

## 1) Ne işe yarar?

Bu script, host seviyesinde Docker için güvenlik odaklı runtime kurulumunu otomatikleştirir:

- gVisor (`runsc`) kurulumu,
- Kata Containers kurulumu,
- `/etc/docker/daemon.json` içinde `runtimes` kaydı,
- opsiyonel Docker restart + runtime doğrulama,
- kurulum sonrası `.env` öneri çıktısı.

## 2) Parametreler

```text
--mode gvisor|kata|both   (default: gvisor)
--dry-run                 (komutları çalıştırmadan planı yazdır)
--no-restart              (docker restart adımını atla)
-h, --help
```

Örnekler:

```bash
sudo bash scripts/install_host_sandbox.sh --mode gvisor
sudo bash scripts/install_host_sandbox.sh --mode kata
sudo bash scripts/install_host_sandbox.sh --mode both --dry-run
```

## 3) Çalışma akışı

1. Argümanlar parse edilir ve `--mode` doğrulanır.
2. `require_root` ile root/sudo zorunluluğu kontrol edilir.
3. Seçilen moda göre kurulum fonksiyonları çağrılır:
   - `install_gvisor`
   - `install_kata`
4. `configure_docker_runtimes` ile `daemon.json` güvenli biçimde güncellenir.
   - Mevcut dosya varsa timestamp’li backup alınır.
   - Gömülü Python kodu JSON parse/edit/yazma yapar.
5. `restart_and_verify`:
   - Docker restart (opsiyonel)
   - `docker info` ile runtime kontrolü
   - runtime’larla `hello-world` smoke test
6. `print_env_hint` ile `.env` önerisi basılır.

## 4) Nerede kullanılır?

- Operasyon/runbook tarafında host sandbox rollout adımlarında kullanılır.
- Test tarafında `tests/test_host_sandbox_installer_assets.py` scriptin varlığını ve içerik beklentilerini doğrular.
- `PROJE_RAPORU.md` içerisinde zero-trust sandbox hazırlığı kapsamında envanterlenmiştir.

## 5) Kullanım örneği ve beklenen çıktılar

### Yardım ekranı

```bash
bash scripts/install_host_sandbox.sh --help
```

Çıktı özetinde `--mode`, `--dry-run`, `--no-restart` seçenekleri görünür.

### Dry-run (root gereksinimi devam eder)

```bash
sudo bash scripts/install_host_sandbox.sh --mode both --dry-run --no-restart
```

Beklenen dry-run log örnekleri:

```text
[dry-run] apt-get update
[dry-run] daemon.json runtimes alanına mode=both eklenecek
```

## 6) Bağımlılıklar

- Bash
- `curl`, `chmod`, `ln`, `cp`, `date`
- `apt-get` (Debian/Ubuntu ailesi)
- `python3` (daemon.json düzenleme için)
- `systemctl`, `docker`
- Root/sudo yetkisi

## 7) Sınırlamalar / dikkat

1. Dağıtım ve paket yöneticisi varsayımı Debian/Ubuntu ağırlıklıdır (`apt-get`).
2. Root yetkisi olmadan çalışmaz (yardım ekranı hariç).
3. `daemon.json` parse edilemiyorsa script hata vererek durur.
4. Runtime smoke test için Docker daemon ve internet erişimi gerekebilir.
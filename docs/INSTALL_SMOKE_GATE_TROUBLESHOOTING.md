# Installer smoke gate sorun giderme

Bu not, Ubuntu/WSL kurulumunda `06_services` fazı başlamadan önce görülen
`test_install_sidar_source_exports_pyproject_version_without_python` hatasını
teşhis etmek için hazırlanmıştır.

## Belirti

Kurulum aşağıdaki imzayla duruyorsa servisler henüz başlatılmamıştır:

- `Servis öncesi installer smoke gate başarısız`
- `test_install_sidar_source_exports_pyproject_version_without_python`
- `_run_bash_smoke 180s içinde tamamlanamadı`
- `python3 should not be required for SIDAR_INSTALL_TEST_MODE version resolution`

Bu test, `source install_sidar.sh` komutunun yalnızca `INSTALL_SIDAR_VERSION`
değerini dışa aktarmasını ve bunu Python'a ihtiyaç duymadan hızlıca yapmasını
bekler. Test sırasında `python3` kasıtlı olarak hata veren sahte bir komutla
öndedir; amaç, sürüm çözümlemenin Python'a veya ağır installer fazlarına
girmediğini kanıtlamaktır.

## Beklenen davranış

`install_sidar.sh`, `SIDAR_INSTALL_VERSION_PROBE_ONLY=1` gördüğünde çok erken
bir fast-path'e girer, `pyproject.toml` içindeki `[project].version` değerini
Bash yerleşikleriyle okur, `INSTALL_SIDAR_VERSION` değişkenini export eder ve
hemen döner.

Hızlı yerel doğrulama:

```bash
cd ~/Sidar
bash -c 'unset INSTALL_SIDAR_VERSION; export SIDAR_INSTALL_TEST_MODE=1 SIDAR_INSTALL_VERSION_PROBE_ONLY=1; source install_sidar.sh >/dev/null; printf "%s\n" "$INSTALL_SIDAR_VERSION"'
```

Çıktı `pyproject.toml` içindeki sürümle aynı olmalıdır; örneğin bu sürümde
`5.2.0` beklenir.

## En olası kök nedenler

1. Yereldeki `install_sidar.sh`, probe-only fast-path düzeltmesini içermeyen eski
   bir kopyadır.
2. Kurulum farklı bir dizindeki eski Sidar checkout'undan çalıştırılmıştır.
3. Antivirüs/WSL dosya sistemi yavaşlığı smoke test süresini büyütmektedir; ancak
   güncel fast-path ile bu kontrol normalde saniyeler içinde bitmelidir.
4. `pyproject.toml` ve `install_sidar.sh` farklı branch veya farklı commit'ten
   gelmiştir.

## Önerilen düzeltme sırası

```bash
cd ~/Sidar
pwd
git status --short
git rev-parse --abbrev-ref HEAD
git pull --ff-only
uv sync --all-extras
bash -c 'unset INSTALL_SIDAR_VERSION; export SIDAR_INSTALL_TEST_MODE=1 SIDAR_INSTALL_VERSION_PROBE_ONLY=1; source install_sidar.sh >/dev/null; printf "INSTALL_SIDAR_VERSION=%s\n" "$INSTALL_SIDAR_VERSION"'
./install_sidar.sh
```

Eğer yalnızca ortam yavaşlığı doğrulanmışsa geçici olarak timeout artırılabilir.
Bu ortam değişkeni artık installer tarafından pre-service smoke gate'in
`pytest` çağrısına doğrudan aktarılmaktadır; verilen değer boş, sıfır veya
alfasayısal olmayan bir girdi olursa installer bir uyarıyla `180` saniyelik
varsayılana geri döner:

```bash
SIDAR_INSTALL_SMOKE_BASH_TIMEOUT=240 ./install_sidar.sh
```

Smoke gate'i bilinçli atlamak son çaredir; servis öncesi sözleşmeyi devre dışı
bırakır:

```bash
./install_sidar.sh --skip-smoke-test
# veya
RUN_SMOKE_TESTS_MODE=never ./install_sidar.sh
# veya yalnızca pre-service smoke gate'i devre dışı bırakmak için:
SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE=0 ./install_sidar.sh
```

## Repo tarafında korunması gereken sözleşme

- Yeni kurulum kodları `SIDAR_INSTALL_VERSION_PROBE_ONLY=1` modunda Python,
  `uv`, Docker, ağ veya helper module source işlemlerini tetiklememelidir.
- `pyproject.toml` içindeki `[project].version` değeri ile
  `INSTALL_SIDAR_VERSION` aynı kalmalıdır.
- Kurulum komutları `uv` standardını izlemelidir: tam geliştirici kurulum için
  `uv sync --all-extras`, test araçları için `uv sync --extra dev`.

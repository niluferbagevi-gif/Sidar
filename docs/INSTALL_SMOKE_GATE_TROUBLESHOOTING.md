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

## Ortamı hızlandırın (WSL2 + Windows Defender)

WSL2 üstünde `bash`/`sed`/`python3` gibi kısa ömürlü alt süreçler, Windows
Defender'ın "real-time protection" taraması ve `\\wsl$` üzerinden yapılan
dosya erişimleri yüzünden 10-100× yavaşlayabilir. Aynı `resolve_install_sidar_version`
probe'unu bu senaryoda 180 saniyelik varsayılana ittiği belgelenmiştir. Aşağıdaki
komutları **PowerShell'i "Yönetici olarak çalıştır"** ile açıp bir kere uygulamak,
smoke gate timeout'unu genellikle tek başına çözer:

```powershell
Add-MpPreference -ExclusionProcess "wsl.exe"
Add-MpPreference -ExclusionProcess "bash.exe"
Add-MpPreference -ExclusionProcess "python3.exe"
Add-MpPreference -ExclusionProcess "python.exe"
# <kullanici-adi> yerine kendi Windows kullanıcı adınızı yazın:
Add-MpPreference -ExclusionPath "\\wsl$\Ubuntu\home\<kullanici-adi>\Sidar"
```

Uygulanan istisnaları doğrulamak için:

```powershell
Get-MpPreference | Select-Object -ExpandProperty ExclusionProcess
Get-MpPreference | Select-Object -ExpandProperty ExclusionPath
```

Ek olarak, installer artık `%UserProfile%\.wslconfig` içinde `processors`,
`kernelCommandLine=cgroup_no_v1=all` ve `[experimental] sparseVhd=true`
anahtarlarını da otomatik olarak yazar. Değişiklik sonrasında PowerShell'de
`wsl --shutdown` çalıştırıp dağıtımı yeniden başlatın; smoke gate'i bir sonraki
kurulumda tekrar deneyin.

## Kısa yol: smoke gate'i atla ve kurulumu bitir

`resolve_install_sidar_version` doğrulaması ortam yavaşlığından tekrar tekrar
timeout alıyor ve **kurulumun geri kalanını (Docker servisleri, migration,
Ollama modelleri, React web UI) tamamlamak** istiyorsanız aşağıdaki üç kısa
yoldan biri kullanılabilir. Her üçü de servis öncesi smoke gate'i atlar; smoke
gate'in kendisi bir bloklama sözleşmesidir ve normal koşullarda **kapatılmamalıdır**,
ancak kırık host ortamını izole etmek ve kurulumu ilerletmek için geçici olarak
kullanılabilir:

```bash
# En temiz: yalnız pre-service smoke gate'i kapatır, kurulum sonu smoke testleri
# yine çalışır. Docker servisleri, Alembic migration'ları vs. normal başlar.
SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE=0 ./install_sidar.sh

# Alternatif 1: kurulum-sonu smoke testleri de dahil hepsini kapatır.
./install_sidar.sh --skip-smoke-test

# Alternatif 2: aynı davranışı bayrak yerine environment üzerinden verir.
RUN_SMOKE_TESTS_MODE=never ./install_sidar.sh
```

Kurulum bittikten sonra Defender exclusion + `wsl --shutdown` uyguladıysanız,
smoke gate'i **bir sonraki tam kurulumda tekrar açık bırakın** — aksi halde
sözleşme regression'ları CI dışında yakalanamaz. Kapatma yalnızca aktif tanılama
seansı için geçerlidir.

## Repo tarafında korunması gereken sözleşme

- Yeni kurulum kodları `SIDAR_INSTALL_VERSION_PROBE_ONLY=1` modunda Python,
  `uv`, Docker, ağ veya helper module source işlemlerini tetiklememelidir.
- `pyproject.toml` içindeki `[project].version` değeri ile
  `INSTALL_SIDAR_VERSION` aynı kalmalıdır.
- Kurulum komutları `uv` standardını izlemelidir: tam geliştirici kurulum için
  `uv sync --all-extras`, test araçları için `uv sync --extra dev`.

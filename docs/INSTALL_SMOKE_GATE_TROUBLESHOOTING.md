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

Çıktı `pyproject.toml` içindeki sürümle aynı olmalıdır; beklenen değer
komut çalıştırılan checkout'taki `[project].version` alanından okunur (değer
hard-code edilmez).

## En olası kök nedenler

1. Yereldeki `install_sidar.sh`, probe-only fast-path düzeltmesini içermeyen eski
   bir kopyadır.
2. Kurulum farklı bir dizindeki eski Sidar checkout'undan çalıştırılmıştır.
3. Antivirüs/WSL dosya sistemi yavaşlığı smoke test süresini büyütmektedir.
   Özellikle Ubuntu 26.04/resolute gibi geliştirme dağıtımı + WSL2 + Windows Defender real-time scanning kombinasyonunda `source install_sidar.sh` çağrısı
   dosyanın yeniden taranması nedeniyle 20 saniyeye yaklaşabilir. Güncel
   fast-path Python/uv/helper source işlemlerine girmese bile bu dış I/O maliyeti
   ortam kaynaklı olarak kalabilir.
4. `pyproject.toml` ve `install_sidar.sh` farklı branch veya farklı commit'ten
   gelmiştir.
5. Timeout sonrası pytest'in gösterdiği stdout/stderr parçası önceki denemeden
   kalmış gibi görünebilir. Aktif installer sözleşmesini doğrulamak için
   `pyproject.toml`, `install_sidar.sh` ve smoke gate logundaki komut satırı
   birlikte kontrol edilmelidir; güncel akış Conda değil `uv` kullanır.

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
WSL2/Defender kaynaklı probe süreleri 20 saniyeye yaklaşıyorsa 240 saniye
başlangıç için güvenli değerdir:

```bash
SIDAR_INSTALL_SMOKE_BASH_TIMEOUT=240 ./install_sidar.sh
```

Sadece servis öncesi smoke gate takılı kalıyor, diğer kurulum adımlarını koruyarak
Docker servislerine geçmek istiyorsanız daha dar kapsamlı kısa yol kullanılabilir:

```bash
SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE=0 ./install_sidar.sh
```

Smoke gate'i bilinçli atlamak son çaredir; servis öncesi sözleşmeyi ve kurulum
sonu smoke testlerini devre dışı bırakır:

```bash
./install_sidar.sh --skip-smoke-test
# veya
RUN_SMOKE_TESTS_MODE=never ./install_sidar.sh
```

WSL2 üzerinde `bash`, `python3`, `uv` veya repo dosya erişimleri Windows Defender
taraması nedeniyle belirgin yavaşlıyorsa, Windows PowerShell'i yönetici olarak
açıp yalnız kendi WSL/Sidar yolunuz için exclusion ekleyin:

```powershell
Add-MpPreference -ExclusionProcess "wsl.exe"
Add-MpPreference -ExclusionProcess "bash.exe"
Add-MpPreference -ExclusionPath "\\wsl$\Ubuntu\home\<kullanıcı>\Sidar"
```

> Not: `<kullanıcı>` ve dağıtım adını kendi ortamınıza göre değiştirin. Defender
> exclusion kurumsal güvenlik politikalarına bağlı olabilir; yalnız güvendiğiniz
> proje dizinini hariç tutun.

## Repo tarafında korunması gereken sözleşme

- Yeni kurulum kodları `SIDAR_INSTALL_VERSION_PROBE_ONLY=1` modunda Python,
  `uv`, Docker, ağ veya helper module source işlemlerini tetiklememelidir.
- `pyproject.toml` içindeki `[project].version` değeri ile
  `INSTALL_SIDAR_VERSION` aynı kalmalıdır.
- Kurulum komutları `uv` standardını izlemelidir: tam geliştirici kurulum için
  `uv sync --all-extras`, test araçları için `uv sync --extra dev`.

## Test timeout politikası

Repo içi smoke testlerde `SIDAR_INSTALL_VERSION_PROBE_ONLY=1` kaynaklama
sözleşmesi, yavaş WSL2/Defender ortamlarında yanlış negatif üretmemesi için
60 saniyelik varsayılan timeout ile doğrulanır. Kurulum fazındaki servis öncesi
gate daha geniş operasyonel tampon kullanır (`SIDAR_INSTALL_SMOKE_BASH_TIMEOUT`
varsayılanı 180 saniye) ve ihtiyaç halinde 240 saniye gibi değerlerle
override edilebilir.

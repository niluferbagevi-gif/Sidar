# Sidar Dev Container tanılama notları

Bu not, VS Code Dev Containers çıktısında sık görülen WSL/Docker satırlarını yorumlamak
ve gerçek hata sinyallerini ayırt etmek için hazırlanmıştır.

## Log yorumu

Aşağıdaki satırlar tek başına hata kabul edilmez:

- `test -f .../server/node` ardından `Exit code 1`: VS Code Remote Server farklı
  kurulum yollarını sırayla dener. Sonraki `.../.vscode-server/bin/<commit>/node`
  kontrolü başarılı oluyorsa bu normal fallback davranışıdır.
- `userEnvProbe: not found in cache`: İlk açılışta veya cache temizlendiğinde normaldir;
  VS Code login shell ortamını yeniden okur.
- `Container: None`: Konfigürasyon okunurken henüz container başlatılmadığını gösterir.
- `Resolving Feature dependencies` ve `Fetching feature`: Dev Container feature katmanı
  hazırlanıyordur.

Gerçek sorun ararken şu satırlara odaklanılmalıdır:

- `docker version` veya `docker info` komutlarında erişim hatası ya da uzun süre
  ilerlememe. Sidar, bu aşamayı daha okunur hale getirmek için `initializeCommand`
  içinde `.devcontainer/host-preflight.sh` çalıştırır ve Docker CLI/daemon durumunu timeout ile
  doğrular. Linux hostlarda eksik CLI, `SIDAR_DEVCONTAINER_PREFLIGHT_INSTALL_DOCKER_CLI=auto`
  politikasıyla Docker resmi APT deposundan kurulmaya çalışılır; WSL2'de Docker Desktop
  Integration tercih edilir ve APT kurulumu yalnız `SIDAR_DEVCONTAINER_PREFLIGHT_INSTALL_DOCKER_CLI=always`
  ile zorlanır. Preflight varsayılan olarak uyarı üretip akışı sürdürür; yerel makinede
  fail-fast davranışı istenirse `SIDAR_DEVCONTAINER_PREFLIGHT_STRICT=1` kullanılabilir.
- `read-configuration` sonrasında JSON/şema hatası.
- Feature kurulumunda `apt-get update`, GPG key veya network hatası.
- `postCreateCommand` veya `updateContentCommand` sırasında `uv sync --frozen --all-extras`
  veya Python sürüm uyuşmazlığı hatası. Dev Container içindeki proje ortamı
  `.venv-container` olarak ayrılmıştır; WSL/host tarafındaki `.venv` bu akışta
  yeniden kullanılmaz ve silinmez. `.venv-container/bin/python -> /home/.../uv/python/...`
  gibi container dışındaki mutlak yollara bakan kırık symlink uyarıları tek başına
  hata değildir; setup betiği bunları, eksik `pyvenv.cfg home` yollarını ve yanlış
  Python minor sürümünü `uv sync` öncesinde temizleyip container sanal ortamını
  deterministik yeniden kurar. Başarılı sync sonrasında
  `.venv-container/.sidar-uv-sync.sha256` dosyasına bağımlılık parmak izi yazılır;
  `pyproject.toml`, `uv.lock`, `.python-version` ve Python minor sürümü değişmediyse
  sonraki `updateContentCommand` çalıştırmalarında `uv sync` atlanır. Bağımlılıkların zorla yenilenmesi gerekiyorsa
  `SIDAR_FORCE_UV_SYNC=1 bash .devcontainer/setup-codespaces.sh sync` çalıştırılmalıdır.
  Bu uyarıdan sonra `uv sync` başarısız oluyorsa asıl hata satırı dependency çözümü,
  network veya sistem paketi çıktısında aranmalıdır.

## VS Code Dev Containers uyarıları ve sanal ortam izolasyonu

`InvalidDefaultArgInFrom: Default value for ARG $BASE_IMAGE...` satırı, VS Code
Dev Containers CLI'ın container kullanıcısı/UID ayarı için ürettiği geçici
Dockerfile katmanından gelebilir. Bu satır tek başına Sidar Dockerfile'ının veya
proje bağımlılıklarının hatalı olduğu anlamına gelmez; build/postCreate akışının
sonucuna bakılmalıdır.

Asıl tekrar kurulum kaynağı çoğunlukla host ile container sanal ortamlarının aynı
`.venv` dizinini paylaşmasıdır. Host WSL yolu `/home/<kullanıcı>/Sidar`, Dev
Container workspace yolu ise `/workspaces/Sidar` olduğundan `pyvenv.cfg` ve
`bin/python` gibi mutlak yol/symlink kayıtları uyuşmaz. Bu nedenle Sidar Dev
Container varsayılanı `UV_PROJECT_ENVIRONMENT=.venv-container` olarak ayrılmıştır;
VS Code Python yorumlayıcısı da `${containerWorkspaceFolder}/.venv-container/bin/python`
yolunu kullanır. Hosttaki `.venv` yerel geliştirme için kalır, container ise
Debian tabanlı imajdaki native bağımlılıklarla kendi ortamını kurar.


## Docker CLI ve daemon beklentisi

Sidar Dev Container imajı, container içinde Docker istemcisini hazır bulundurmak için
Docker resmi APT deposundan `docker-ce-cli`, `docker-buildx-plugin` ve
`docker-compose-plugin` paketlerini kurar. Setup fallback'i Debian ve Ubuntu
tabanlı özel imajları ayırt ederek Docker APT deposunu `debian/<codename>` veya
`ubuntu/<codename>` olarak yazar; Ubuntu `noble` gibi ortamlarda hatalı
`download.docker.com/linux/debian noble` deposu oluşursa sonraki çalıştırmada
eski `docker.list` dosyasını yeniler. Ayrıca `devcontainer.json`, host Docker
daemon'unu container içine güvenli şekilde kullanabilmek için
`docker-outside-of-docker` feature'ını etkinleştirir.

Bu düzenleme container içindeki `docker`, `docker buildx` ve `docker compose`
komutlarını hazırlar; ancak imajı ilk kez oluşturmak için kullanılan host/WSL
bağlamında yine çalışan bir Docker CLI + Docker daemon gerekir. Başka bir ifadeyle
`docker build -f .devcontainer/Dockerfile .devcontainer --progress=plain` komutu host
makinede `docker` binary'si yoksa proje dosyalarıyla başlatılamaz; önce Docker Desktop,
Docker Engine veya eşdeğer runtime kurulmalıdır.

Beklenen doğrulama komutları:

```bash
# Linux hostlarda eksik Docker CLI'ı otomatik tamamlamayı dener.
bash .devcontainer/host-preflight.sh

docker --version
docker compose version
docker buildx version
```

Repo içi genel kurulum betiği de aynı ayrımı korur: `install_sidar.sh` Debian/Ubuntu
hostlarda `DOCKER_CLI_INSTALL=auto` politikasıyla eksik Docker CLI'ı tamamlamayı dener,
`--install-docker-cli` ile kurulum zorlanabilir ve `--skip-docker-cli` ile otomatik
kurulum kapatılabilir. Bu adım CLI/Compose araçlarını sağlar; Docker daemon için hostta
Docker Desktop/Engine veya erişilebilir bir remote daemon yine gereklidir.

## Sidar için beklenen ortam

Sidar'ın varsayılan geliştirme ortamı Python `3.11`, pin'li `uv` ve yerel coding modeli olarak
`qwen2.5-coder:7b` kullanır. Dev Container imajı, updateContent/postCreate aşamasında
tekrar bootstrap yapılmaması için uv binary'sini önceden içerir; setup betiğindeki
resmi uv kurulum yolu yalnız özel veya eski imajlarda fallback olarak kalır. Dev Container
imajı ve container'a özel `.venv-container` kurulumu bu varsayımla aynı hizaya getirilmiştir.

## Hızlı kontrol komutları

WSL/host veya container bağlamında aşağıdaki komutlar çalıştırılabilir:

```bash
bash .devcontainer/host-preflight.sh
bash .devcontainer/setup-codespaces.sh sync
SIDAR_FORCE_UV_SYNC=1 bash .devcontainer/setup-codespaces.sh sync
uv run python --version
bash -n .devcontainer/setup-codespaces.sh
```

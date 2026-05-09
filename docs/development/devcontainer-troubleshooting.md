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
  içinde `.devcontainer/host-preflight.sh` çalıştırır ve Docker komutlarını timeout ile
  doğrular. Preflight varsayılan olarak uyarı üretip akışı sürdürür; yerel makinede
  fail-fast davranışı istenirse `SIDAR_DEVCONTAINER_PREFLIGHT_STRICT=1` kullanılabilir.
- `read-configuration` sonrasında JSON/şema hatası.
- Feature kurulumunda `apt-get update`, GPG key veya network hatası.
- `postCreateCommand` sırasında `uv sync --frozen --all-extras` veya Python sürüm
  uyuşmazlığı hatası.

## Sidar için beklenen ortam

Sidar'ın varsayılan geliştirme ortamı Python `3.11`, `uv` ve yerel coding modeli olarak
`qwen2.5-coder:7b` kullanır. Dev Container imajı ve `.venv` kurulumu bu varsayımla aynı
hizaya getirilmiştir.

## Hızlı kontrol komutları

WSL/host veya container bağlamında aşağıdaki komutlar çalıştırılabilir:

```bash
bash .devcontainer/host-preflight.sh
bash .devcontainer/setup-codespaces.sh sync
uv run python --version
bash -n .devcontainer/setup-codespaces.sh
```
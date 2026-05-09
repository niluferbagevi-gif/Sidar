# Sidar Dev Container notları

Bu klasör, Sidar geliştirici ortamını VS Code Dev Containers, WSL ve Codespaces
senaryolarında tutarlı başlatmak için kullanılan yapılandırmayı içerir.

## Son log analizi

Paylaşılan Dev Containers çıktısında kritik bir kurulum hatası görünmüyor:

- `host-preflight.sh`, WSL dağıtımını, Docker CLI'yi, Docker Compose v2'yi,
  Docker Buildx'i ve Docker daemon erişimini başarıyla doğruluyor.
- Dev Container image build'i cache üzerinden başarıyla tamamlanıyor.
- Logdaki `server/node` için görülen ilk `Exit code 1` kontrolleri, VS Code'un
  mevcut server kurulum yolunu bulana kadar yaptığı normal fallback kontrolleridir.
- BuildKit'in `InvalidDefaultArgInFrom` uyarısı, VS Code Dev Containers CLI'nin
  remote user UID eşitlemesi için geçici olarak ürettiği `updateUID.Dockerfile`
  içinden gelir; Sidar'ın `.devcontainer/Dockerfile` dosyasından kaynaklanmaz.

## UID eşitleme kararı

WSL + Docker Desktop kurulumlarında kullanıcı UID'si çoğunlukla `1000` olur ve
`mcr.microsoft.com/devcontainers/python:1-3.11-bookworm` taban image'indeki
`vscode` kullanıcısı da bu UID ile gelir. Bu nedenle Sidar, `remoteUser` değerini
`vscode` olarak açıkça pinler ve Dev Containers CLI'nin ekstra UID rewrite build
adımını kapatır. Bu ayar:

- logdaki geçici `updateUID.Dockerfile` BuildKit uyarısını önler,
- container başlatma sırasında gereksiz bir mini image build adımını azaltır,
- WSL/Docker Desktop varsayılan geliştirme ortamıyla uyumlu kalır.

Eğer Linux host üzerinde workspace dosyalarınız `1000` dışında bir UID ile
sahiplenildiyse, container içinde yazma izni sorunları görürseniz host tarafında
workspace sahipliğini düzeltin veya yerel Dev Containers override dosyanızda UID
eşitlemesini yeniden etkinleştirin.

## Hızlı doğrulama

Dev Container açılmadan önce host tarafında aşağıdaki komut çalışır:

```bash
bash .devcontainer/host-preflight.sh
```

Container açıldıktan sonra Python ortamı ve temel servisler şu fazlarla hazırlanır:

```bash
bash .devcontainer/setup-codespaces.sh post-create
bash .devcontainer/setup-codespaces.sh post-start
```

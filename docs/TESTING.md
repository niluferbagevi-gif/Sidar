# Test çalıştırma rehberi

Sidar'da iki farklı test akışı vardır:

## Hızlı tekil test / debug

Tek bir test fonksiyonunu veya küçük bir dosya grubunu incelerken doğrudan pytest
kullanın. Coverage gate bu akışta varsayılan olarak çalışmaz; böylece fonksiyonel
olarak geçen tekil testler toplam repo coverage düşük çıktığı için yanıltıcı şekilde
başarısız görünmez.

```bash
uv run pytest tests/unit/core/test_rag.py::test_fetch_pgvector_returns_empty_when_query_embedding_empty -q
```

Geçici olarak coverage eklenecekse ve gate istenmiyorsa açıkça `--no-cov` verilebilir:

```bash
uv run pytest tests/unit/core/test_rag.py::test_fetch_pgvector_returns_empty_when_query_embedding_empty -q --no-cov
```

## Kalite kapısı / coverage doğrulaması

Merge/PR öncesi ana doğrulama yolu `run_tests.sh` betiğidir. Coverage raporları ve
`.coveragerc` tabanlı fail-under kontrolü bu betik tarafından yönetilir.

```bash
./run_tests.sh
```

CI profilinde coverage eşiği daha sıkı çalıştırılabilir:

```bash
CI=true TEST_PROFILE=ci ./run_tests.sh
```
## Voice extra / PyAudio sistem bağımlılığı

`pyproject.toml` içindeki `voice` extra grubu `pyaudio` içerir. `pyaudio`
tekerleği her platformda hazır gelmeyebildiği için `uv sync --all-extras` veya
`uv sync --extra voice` sırasında PortAudio geliştirme başlıklarına ihtiyaç
duyabilir.

Linux/Ubuntu tabanlı geliştirme ve CI ortamlarında Python bağımlılıklarını
senkronlamadan önce sistem paketini kurun:

```bash
sudo apt-get update
sudo apt-get install -y portaudio19-dev
uv sync --all-extras
```

macOS üzerinde eşdeğer ön koşul Homebrew ile sağlanır:

```bash
brew install portaudio
uv sync --all-extras
```

Repo CI akışı bu ön koşulu `scripts/install_ci_system_deps.sh` üzerinden kurar;
`install_sidar.sh` ve modüler installer da tam/voice profil senkronizasyonundan
önce Debian/Ubuntu üzerinde `portaudio19-dev` paketini idempotent biçimde
doğrular.

# AI_CONTEXT.md — Sidar için AI çalışma bağlamı

Bu dosya, farklı AI araçlarıyla (ChatGPT, Claude, Cursor vb.) çalışırken proje beklentilerini
tek noktada toplamak için hazırlanmıştır.

## 1) Proje teknik özeti

- **Proje adı:** Sidar (`pyproject.toml`)
- **Python sürümü:** `>=3.11`
- **Paket yöneticisi:** `uv` (requirements kilidi `uv pip compile` ile üretilir)
- **Ana backend:** FastAPI + async mimari
- **Mimari:** Multi-agent (coder/reviewer/researcher/qa/coverage/poyraz)

## 2) Bağımlılık ve ortam yönetimi

- Uygulama ve ekstra bağımlılıklar `pyproject.toml` içinde tanımlıdır.
- Geliştirme bağımlılıkları (`pytest`, `pytest-asyncio`, `ruff`, `mypy`, `pytest-cov` vb.)
  `project.optional-dependencies.dev` altında tutulur.
- Kilitli dev bağımlılıkları `requirements-dev.txt` dosyasına derlenir:

```bash
uv pip compile pyproject.toml --extra dev -o requirements-dev.txt
```

## 3) Test / kalite kapısı standartları

- **Test framework:** `pytest`
- **Async test modu:** `asyncio_mode = auto`
- **Kapsam:** `--cov=agent --cov=core --cov=managers --cov=plugins`
- **Linter:** `ruff`
- **Tip denetimi:** `mypy` (`strict = true`)

Önerilen komutlar:

```bash
pytest
pytest -m "not slow"
ruff check .
mypy .
```

## 4) AI araçları için çalışma sözleşmesi

### ChatGPT / sandbox çalışan araçlar

- `requirements-dev.txt` dosyasını **bağlam** olarak kullan.
- Paket kurmayı veya internetten bağımlılık çekmeyi varsayma.
- Özel kütüphaneler (ör. `litellm`, `chromadb`, `google-genai`) gerekliyse:
  - Kod/testi çalıştırmadan yaz,
  - "yerelde doğrulanmalı" notu ekle.
- `unittest` yerine proje standardı olan `pytest`/`pytest-asyncio` tercih et.

Örnek istek kalıbı:

> "AI_CONTEXT.md ve requirements-dev.txt dosyalarını referans al.
> Pytest uyumlu test yaz; kodu çalıştırmayı deneme. Gerekli doğrulama komutlarını ayrıca ver."

### Claude / IDE bağlam okuyucular

- `AI_CONTEXT.md`, `AGENTS.md` ve `pyproject.toml` birlikte okunmalı.
- Üretilen kod şu sırayla hizalanmalı:
  1. Agent rol ve capability sözleşmeleri,
  2. `pytest` + `pytest-asyncio` test yaklaşımı,
  3. `ruff` ve `mypy strict` kuralları.

## 5) Kod üretiminde zorunlu ilkeler

- Asenkron akışta bloklayıcı I/O kullanılmamalı (`async/await`, gerekirse `asyncio.to_thread`).
- SQL sorguları parametreli olmalı.
- UTF-8 ve Türkçe karakter güvenliği korunmalı.
- Yeni özelliklerde ilgili test dosyaları ve doküman güncellemesi birlikte yapılmalı.

## 6) PR / değişiklik disiplini

- Değişiklik özetinde:
  - hangi dosyaların değiştiği,
  - hangi komutların çalıştırıldığı,
  - hangi kontrollerin yerelde doğrulanması gerektiği
  açıkça belirtilmelidir.
- Çalıştırılamayan adımlar "neden" ile birlikte raporlanmalıdır.

## 7) Hızlı başlangıç istemleri

### Kod değişikliği isterken

> "Bu repo için AI_CONTEXT.md kurallarına uyarak değişiklik yap.
> Testleri pytest formatında yaz, ruff/mypy etkisini değerlendir,
> çalıştırılamayan adımları varsayım olarak değil açık not olarak belirt."

### Sadece taslak/analiz isterken

> "Kod çalıştırma yok. AI_CONTEXT.md'ye göre yalnızca tasarım, patch planı
> ve pytest odaklı test stratejisi üret."

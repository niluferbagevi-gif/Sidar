# Observability Simülasyonu (Jaeger + Redis + PostgreSQL + Sidar)

Bu akış, WSL/Ubuntu üzerinde **tam izlenebilirlik demosu** için hazırlanmıştır.

## 1) Stack'i ayağa kaldır

```bash
docker compose up -d redis postgres jaeger sidar-web
```

Kontrol:

```bash
docker compose ps
curl -s http://localhost:7860/health
```

## 2) RAG görevi üret (belge ekle + arama)

Örnek bir URL'yi RAG deposuna ekleyin:

```bash
curl -s -X POST http://localhost:7860/rag/add-url \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com","title":"example"}'
```

Ardından RAG araması yapın:

```bash
curl -s "http://localhost:7860/rag/search?q=example&mode=auto&top_k=3"
```

## 3) LLM + supervisor/delegation trafiğini tetikle

Aşağıdaki komut konteyner içinde Supervisor zincirini tetikler (research/review/code akışları):

```bash
docker compose exec -T sidar-web python - <<'PY'
import asyncio
from config import Config
from agent.sidar_agent import SidarAgent

async def main():
    cfg = Config()
    cfg.ENABLE_TRACING = True
    cfg.OTEL_EXPORTER_ENDPOINT = "http://jaeger:4317"
    agent = SidarAgent(cfg)

    prompt = (
        "RAG deposundaki example dokümanını dikkate alarak "
        "kısa bir analiz yap, ardından güvenlik ve kalite açısından değerlendir."
    )

    chunks = []
    async for ch in agent.respond(prompt):
        chunks.append(ch)
    print("".join(chunks)[:1000])

asyncio.run(main())
PY
```

## 4) Jaeger UI üzerinden span'leri izle

UI: <http://localhost:16686>

1. Service olarak `sidar-web` (veya `sidar`) seçin.
2. Son 15 dakikayı filtreleyin.
3. Aşağıdaki span tiplerini doğrulayın:
   - FastAPI request span'leri (`/rag/add-url`, `/rag/search`, `/health`)
   - HTTP client span'leri (LLM provider çağrısı; `httpx` enstrümantasyonu)
   - Supervisor/delegation adımları (researcher/coder/reviewer event zinciri)
4. Span timeline'ında milisaniye bazlı gecikmeleri karşılaştırın.

## 5) API ile trace sorgulama (opsiyonel)

```bash
curl -s "http://localhost:16686/api/services"
curl -s "http://localhost:16686/api/traces?service=sidar-web&limit=5"
```

## 6) Temizlik

```bash
docker compose down
```
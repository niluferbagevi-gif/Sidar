# Chaos Live Rehearsal Runbook

Bu runbook, Kubernetes üzerinde Sidar dağıtımının Redis/PostgreSQL kesintilerine ve event-stream bozulmalarına karşı davranışını prova etmek için hazırlanmıştır.

## Amaç

- `liveness` ve `readiness` probe'larının doğru endpoint'lere baktığını doğrulamak.
- Redis veya PostgreSQL kesintilerinde uygulamanın **çökmek yerine degrade** olduğunu göstermek.
- Agent event bus tarafında bozuk/ack edilemeyen mesajların **DLQ** kanalına düştüğünü doğrulamak.

## Önkoşullar

- Helm chart ile dağıtılmış aktif bir ortam.
- `kubectl` erişimi.
- Web deployment için `ENABLE_DEPENDENCY_HEALTHCHECKS=true`.
- Event bus için `SIDAR_EVENT_BUS_DLQ_CHANNEL` tanımlı.

## 1. Preflight

```bash
kubectl get deploy,po,svc -n <namespace>
kubectl describe deploy <release>-web -n <namespace> | rg "healthz|readyz|ENABLE_DEPENDENCY_HEALTHCHECKS|SIDAR_EVENT_BUS_DLQ"
kubectl port-forward svc/<release>-web 7860:7860 -n <namespace>
curl -sSf http://127.0.0.1:7860/healthz
curl -sSf http://127.0.0.1:7860/readyz
```

Beklenen sonuç:

- `/healthz` → `200`
- `/readyz` → `200`
- readiness probe yolu `/readyz` olarak görünür.

## 2. Redis kesintisi provası

Redis pod'unu geçici olarak durdurun:

```bash
kubectl scale statefulset <release>-redis --replicas=0 -n <namespace>
sleep 10
curl -i http://127.0.0.1:7860/healthz
curl -i http://127.0.0.1:7860/readyz
```

Beklenen sonuç:

- `/healthz` → halen `200` döner. Proses yaşıyor olmalıdır.
- `/readyz` → `503` döner ve `dependencies.redis.healthy=false` içerir.
- Web pod'u sürekli restart döngüsüne girmemelidir.

Geri alma:

```bash
kubectl scale statefulset <release>-redis --replicas=1 -n <namespace>
kubectl rollout status statefulset/<release>-redis -n <namespace>
curl -sSf http://127.0.0.1:7860/readyz
```

## 3. PostgreSQL kesintisi provası

```bash
kubectl scale statefulset <release>-postgresql --replicas=0 -n <namespace>
sleep 10
curl -i http://127.0.0.1:7860/readyz
```

Beklenen sonuç:

- `/readyz` → `503`
- JSON çıktısında `dependencies.database.healthy=false`
- `liveness` hâlâ ayakta kalır.

Geri alma:

```bash
kubectl scale statefulset <release>-postgresql --replicas=1 -n <namespace>
kubectl rollout status statefulset/<release>-postgresql -n <namespace>
curl -sSf http://127.0.0.1:7860/readyz
```

## 4. Event bus DLQ doğrulaması

Bir worker pod'undan bozuk payload senaryosu üretin veya uygulama loglarını izleyin:

```bash
kubectl logs deploy/<release>-web -n <namespace> --tail=200 -f
kubectl exec -it deploy/<release>-web -n <namespace> -- python - <<'PY'
import asyncio
from agent.core.event_stream import AgentEventBus

async def main():
    bus = AgentEventBus()
    await bus._write_dead_letter(
        reason="manual-chaos-check",
        payload={"note": "probe"},
        error=RuntimeError("simulated")
    )
    print(len(bus._dlq_buffer))

asyncio.run(main())
PY
```

Redis erişimi varsa DLQ stream'ini doğrulayın:

```bash
kubectl exec -it statefulset/<release>-redis -n <namespace> -- \
  redis-cli XRANGE sidar:agent_events:dlq - +
```

Beklenen sonuç:

- En az bir DLQ kaydı görünür.
- Kayıtta `reason`, `payload`, `ts` alanları bulunur.

## 5. Başarı kriterleri

- Liveness probe kesinti sırasında pod'u gereksiz yere öldürmez.
- Readiness probe bağımlılık kesintilerinde trafiği pod'dan uzaklaştırır.
- Redis event-stream hata kayıtları DLQ veya yerel DLQ buffer'a düşer.
- Redis/PostgreSQL geri geldiğinde `/readyz` tekrar `200` olur.

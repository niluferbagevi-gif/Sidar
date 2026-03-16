
# Plugin Marketplace Demo (Crypto Agent)

Bu demo, `plugins/crypto_price_agent.py` dosyasını API ile yükleyip ajanı anında çalıştırmayı gösterir.

## 1) Plugin dosyasını API ile yükleme

```bash
curl -X POST "http://localhost:7860/api/agents/register-file" \
  -H "Authorization: Bearer $SIDAR_ADMIN_TOKEN" \
  -F "file=@plugins/crypto_price_agent.py" \
  -F "class_name=CryptoPriceAgent" \
  -F "capabilities=crypto_price,market_data" \
  -F "description=Marketplace demo crypto agent" \
  -F "version=1.0.0"
```

Beklenen sonuç: JSON içinde `"success": true` ve `"agent.role_name": "crypto_price_agent"`.

## 2) Yüklenen ajanı görevle çağırma (CLI/Python)

```bash
python - <<'PY'
import asyncio
from agent.registry import AgentRegistry

agent = AgentRegistry.create("crypto_price_agent")
print(asyncio.run(agent.run_task("btc fiyatı nedir?")))
PY
```

Beklenen sonuç: `BTC` ve USD fiyat bilgisi döner.

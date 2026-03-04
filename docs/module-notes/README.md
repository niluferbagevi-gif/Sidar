# Module Notes

Bu klasör, proje içindeki kritik modüllerin **doğrulanmış teknik açıklamalarını** içerir.

Amaç:
- Kod inceleme notlarını tek yerde toplamak,
- Yeni geliştiricilere hızlı onboarding sağlamak,
- Rapor metinleri ile gerçek kod davranışını eşleştirmek.

## İçerik

- [`00-roadmap.md`](./00-roadmap.md): Klasör bazlı + parti bazlı dokümantasyon planı.
- [`config.md`](./config.md): `config.py` için görev, özellik, bağımlılık ve entegrasyon haritası.
- [`main.md`](./main.md): CLI giriş noktası, event-loop akışı ve runtime override davranışı.
- [`web_server.md`](./web_server.md): FastAPI/SSE servis katmanı, endpoint grupları, rate-limit ve iyileştirme notları.
- [`agent/README.md`](./agent/README.md): Agent katmanı (sidar_agent, auto_handle, definitions, init) teknik notları.
- [`core/README.md`](./core/README.md): Core katmanı (`__init__`, llm_client, memory, rag) teknik notları.

## Not

Bu klasör yaşayan doküman yaklaşımıyla tutulur; ilgili modülde önemli değişiklik yapıldığında aynı commit içinde notun da güncellenmesi önerilir.

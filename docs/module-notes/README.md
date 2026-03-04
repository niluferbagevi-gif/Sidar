# Module Notes

Bu klasör, proje içindeki kritik modüllerin **doğrulanmış teknik açıklamalarını** içerir.

Amaç:
- Kod inceleme notlarını tek yerde toplamak,
- Yeni geliştiricilere hızlı onboarding sağlamak,
- Rapor metinleri ile gerçek kod davranışını eşleştirmek.

## İçerik

- [`00-roadmap.md`](./00-roadmap.md): Klasör bazlı + parti bazlı dokümantasyon planı.
- [`config.md`](./config.md): `config.py` için görev, özellik, bağımlılık ve entegrasyon haritası.
- [`main.md`](./main.md): Akıllı başlatıcı (wizard/quick), çalışma modu seçim akışı.
- [`cli.md`](./cli.md): Terminal/CLI çalışma giriş noktası (eski main akışı).
- [`web_server.md`](./web_server.md): FastAPI/SSE servis katmanı, endpoint grupları, rate-limit ve iyileştirme notları.
- [`agent/README.md`](./agent/README.md): Agent katmanı (sidar_agent, auto_handle, definitions, init) teknik notları.
- [`core/README.md`](./core/README.md): Core katmanı (`__init__`, llm_client, memory, rag) teknik notları.
- [`managers/README.md`](./managers/README.md): Managers katmanı (code/security/github/web/package/system/todo) teknik notları.
- [`ops/README.md`](./ops/README.md): Ops/dağıtım/dokümantasyon katmanı teknik notları.
- [`tests-ui/README.md`](./tests-ui/README.md): Test altyapısı ve web UI katmanı teknik notları.

## Not

Bu klasör yaşayan doküman yaklaşımıyla tutulur; ilgili modülde önemli değişiklik yapıldığında aynı commit içinde notun da güncellenmesi önerilir.
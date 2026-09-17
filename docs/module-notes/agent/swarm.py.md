# `agent/swarm.py` — Swarm Orchestrator (Dinamik Çoklu Ajan Koordinasyonu)

- **Kaynak dosya:** `agent/swarm.py`
- **Not dosyası:** `docs/module-notes/agent/swarm.py.md`

**Amaç:** Karmaşık görevleri alt görevlere böler, uygun uzman ajanlara
yönlendirir ve sonuçları birleştirir; `agent/registry.py`'deki
`AgentCatalog`/`AgentSpec` ile entegre çalışır.

**Kullanım:**
```python
orchestrator = SwarmOrchestrator(cfg)
result = await orchestrator.run("Bu kodu incele ve güvenlik açıklarını bul")
results = await orchestrator.run_parallel(
    [
        SwarmTask(goal="Kodu incele", intent="code_review"),
        SwarmTask(goal="Güvenlik denetle", intent="security_audit"),
    ]
)
```

**Özellikler:** Tek görev + otomatik ajan seçimi (`run()`) ve paralel swarm
(`run_parallel()` — birden fazla ajan eş zamanlı çalışır) iki ana modu.
`agent/core/contracts.py`'deki `BrokerTaskEnvelope`/`BrokerTaskResult`/`DelegationRequest`/`TaskEnvelope`
sözleşmelerini (yalnızca type-checking sırasında import edilir) kullanır —
doğrudan-P2P handoff mimarisinin merkezi orkestrasyon katmanı.

# 3.7c `agent/base_agent.py` — Temel Ajan Sınıfı (55 satır)

**Amaç:** Multi-agent yapısındaki uzman ajanlar için ortak bir soyut temel sınıf (`BaseAgent`) sağlar.

**Öne Çıkanlar:**
- Ortak `cfg` ve `llm_client` bağımlılıklarının tek bir tabanda toplanması
- Uzman roller arasında tutarlı arayüz (`register_tool`, `call_tool`)
- P2P delegasyon altyapısı: `delegate_to` ile `DelegationRequest` üretimi ve `is_delegation_message` ile sonuç tip doğrulama
- Gelecekte yeni role eklentileri için genişletilebilir iskelet (`ABC` + `@abstractmethod run_task`)

---

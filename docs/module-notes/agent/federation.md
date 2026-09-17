# agent/federation/

- **Kaynak dizini:** `agent/federation/` (`__init__.py`, `service.py`)
- **Not dosyası:** `docs/module-notes/agent/federation.md`

## Amaç

Harici (swarm-federasyon) tetikleyicilerin LLM prompt'una dönüştürülmesini
kapsayan yardımcı katman. `service.py`, gerçek kontrat sınıflarını
(`FederationTaskEnvelope`, `ActionFeedback`, `derive_correlation_id`) önce
`agent.core.contracts`'tan (`sys.modules`/`import_module` ile döngüsel
import'u önleyerek) çözmeye çalışır; bulunamazsa
`agent.core.contracts_fallback.bind_fallback_contracts` ile üretilen
fallback sınıflara düşer.

- **`trigger_attr`/`trigger_payload`/`trigger_meta`:** hem dict hem
  contract-nesnesi biçimindeki tetikleyicilerden savunmacı (defensive-copy)
  alan okuma.
- **`trigger_to_prompt`/`build_federation_task_prompt`/
  `build_action_feedback_prompt`/`build_trigger_prompt`:** tetikleyici tipine
  göre LLM'e sunulacak prompt metnini üretir.
- **`_cap_trigger_prompt` (`_MAX_TRIGGER_PROMPT_CHARS=60_000`):** CI yolunun
  aksine (bkz. `core/ci_remediation.py::build_ci_failure_prompt`, kendi boyut
  bütçelemesi var) federasyon/feedback/generic tetikleyicilerin dahili bir
  boyut sınırı yok; bu fonksiyon kötü niyetli/aşırı büyük bir dış payload'ın
  prompt'u sınırsız şişirmesini engelleyen güvenlik ağıdır.

## Kullanım noktası

`agent/triggers.py` ve `agent/sidar_agent.py`, gelen federasyon
tetikleyicilerini bu prompt builder'lardan geçirip ajana iletir.

## Test kapısı

`tests/unit/agent/test_federation_service.py`,
`tests/unit/web/routes/test_autonomy_federation.py`,
`tests/integration/workflow/test_swarm_federation.py`.

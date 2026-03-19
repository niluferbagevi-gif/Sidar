# RFC: Multi-Agent / Supervisor Mimarisi

- **Belge No:** RFC-0001
- **Durum:** Tamamlandı (Implemented / v4.2.0 ile kurumsal olarak kapanış aldı)
- **Tarih:** 2026-03-10
- **Uygulanan Sürüm:** v4.2.0
- **Yazar:** Sidar Mühendislik

---

## 1) Özet

Bu RFC, `sidar_agent.py` içinde tek bir ReAct döngüsüne yüklenen çok sayıdaki aracın (45+) **uzman rollere ayrılarak** yönetilmesini önerir. Hedef, sistemi daha ölçeklenebilir, test edilebilir ve bakım maliyeti düşük hale getirmektir.

Önerilen yapı:

- **Supervisor Ajan:** Kullanıcı isteğini analiz eder, alt görevlere böler, doğru uzman ajana yönlendirir ve sonuçları birleştirir.
- **Coder Ajan:** Dosya, kod üretim/çalıştırma, güvenli çalışma araçları.
- **Researcher Ajan:** Web arama + RAG/doküman keşif araçları.
- **Reviewer Ajan:** Dinamik pytest üretimi, sandbox içinde regresyon çalıştırma, repo/PR/issue inceleme ve QA geri bildirimi.

---

## Durum Matrisi (Planlandı / Implement Edildi)

| Bileşen | Durum | Not |
|---|---|---|
| `agent/core/contracts.py` | ✅ Implement edildi | TaskEnvelope ve TaskResult aktif. |
| `agent/core/supervisor.py` | ✅ Implement edildi | Varsayılan yönlendirme ve coder→reviewer hattı var. |
| `agent/roles/coder_agent.py` | ✅ Implement edildi | Kod odaklı araçlar aktif. |
| `agent/roles/researcher_agent.py` | ✅ Implement edildi | Web/RAG akışı aktif. |
| `agent/roles/reviewer_agent.py` | ✅ Implement edildi | PR/issue/repo review akışı eklendi. |
| `agent/core/registry.py` | ✅ Implement edildi | Role kayıt/keşif merkezi eklendi. |
| `agent/core/memory_hub.py` | ✅ Implement edildi | Global + role-local notlar eklendi. |
| P2P role handoff | ✅ Implement edildi | `P2PMessage` protokolü + direct handoff hattı ile ajanlar Swarm içinde rol→rol doğrudan görev devredebiliyor. |
| Legacy single-agent akışı | 🟡 Deprecation | `SidarAgent` varsayılan olarak supervisor yolunu kullanıyor. |

## 2) Problem Tanımı

Tek ajan yaklaşımında:

1. Araç seçim uzayı büyüdükçe yanlış tool seçimi riski artar.
2. Tek prompt içinde çok farklı görev türleri (kod, web araştırma, GitHub) birbirini kirletir.
3. Test kapsamı büyüse de, değişikliklerin yan etkisini izole etmek zorlaşır.
4. Uzun vadede yeni rol eklemek (ör. SecurityAgent, DataAgent) maliyetlidir.

Sonuç: Ajanın yetkinliği yüksek olsa da mimari karmaşıklık operasyonel riski artırır.

---

## 3) Hedefler ve Hedef Dışı Kapsam

### 3.1 Hedefler

- Tool alanını role göre daraltmak.
- Planlama ve yürütmeyi ayırmak (Supervisor vs. Specialist).
- Bağlam transferini standart bir protokole bağlamak.
- Mevcut API/CLI/Web kullanımını bozmadan arkada mimariyi dönüştürmek.
- Geçişin aşamalı yapılabilmesi (feature flag / fallback).

### 3.2 Hedef Dışı Kapsam

- İlk fazda dağıtık/ayrı process ajanlar zorunlu değil (in-process başlayabilir).
- İlk fazda yeni iş alanı ajanları (security/data) zorunlu değil.
- İlk fazda tam otonom paralel orkestrasyon şart değil (kontrollü paralellik yeterli).

---

## 4) Önerilen Mimari

```text
Kullanıcı İsteği
   │
   ▼
SupervisorAgent
   ├─ Planlayıcı (intent + task decomposition)
   ├─ Router (role selection)
   ├─ Orchestrator (sıra/bağımlılık/yineleme)
   └─ Synthesizer (tek final cevap)
      │
      ├────────► CoderAgent
      ├────────► ResearcherAgent
      └────────► ReviewerAgent
```

Her uzman ajan yalnızca kendi tool setini görür. Böylece ReAct karar yüzeyi küçülür.

---

## 5) Rollerin Sorumlulukları

### 5.1 SupervisorAgent (Yönetici)

- Kullanıcı isteğini sınıflandırır (kodlama, araştırma, repo inceleme, hibrit).
- Görevi alt görevlere böler.
- Alt görevleri role ve önceliğe göre sıralar.
- Uzman ajanlardan gelen çıktıları doğrular, çelişkileri giderir.
- Nihai yanıtı tek formatta üretir.

### 5.2 CoderAgent (Kodlayıcı)

- Sadece kod/dosya odaklı araçlar:
  - `read_file`, `write_file`, `list_dir`, `exec_code` (ve benzeri CodeManager araçları).
- Kod değişikliği + test + diff + commit önerisi üretir.
- Güvenlik seviyesi (sandbox/full/restricted) kurallarına sıkı bağlıdır.

### 5.3 ResearcherAgent (Araştırmacı)

- Sadece bilgi edinme araçları:
  - `web_search`, `fetch_url`, `rag_search`, `rag_add` (policy’ye bağlı), `package_info`.
- Çıktı formatı: kaynak odaklı özet, bulgu listesi, kanıt bağlantısı.

### 5.4 ReviewerAgent (GitHub İnceleyici)

- Sadece repo/PR/issue odaklı araçlar:
  - `list_prs`, `pr_diff`, `issues`, `repo_meta`, `changelog/release` yardımcıları.
- Çıktı formatı: risk matrisi, review checklist, önerilen aksiyonlar.

---

## 6) İletişim Protokolü (Agent Contract)

Ajanlar arası standart mesaj zarfı:

```json
{
  "task_id": "uuid",
  "parent_task_id": "uuid|null",
  "sender": "supervisor|coder|researcher|reviewer",
  "receiver": "supervisor|coder|researcher|reviewer",
  "intent": "code_change|research|review|mixed",
  "goal": "string",
  "context": {
    "session_id": "string",
    "repo": "string",
    "branch": "string",
    "constraints": ["..."]
  },
  "inputs": ["..."],
  "artifacts": [{"type": "file|diff|url|note", "ref": "..."}],
  "status": "queued|running|done|failed",
  "result": {
    "summary": "string",
    "evidence": ["..."],
    "next_actions": ["..."]
  }
}
```

### 6.1 Protokol İlkeleri

- **Idempotent task_id:** Aynı görev tekrarında dedup uygulanır.
- **Deterministic handoff:** Supervisor role seçimini gerekçesiyle loglar.
- **Evidence-first:** Uzman ajanlar mümkünse her bulguya kanıt ekler.
- **Timeout budget:** Her alt görev üst görev bütçesinden pay alır.

---

## 7) ConversationMemory ve Bağlam Yönetimi

### 7.1 Bellek Katmanları

1. **Global Session Memory:** Kullanıcıyla paylaşılan ana konuşma bağlamı.
2. **Role-local Working Memory:** Uzman ajanın kısa ömürlü çalışma notları.
3. **Artifact Store:** Dosya/diff/link gibi büyük çıktılar için referans deposu.

### 7.2 Güncelleme Politikası

- Uzman ajanlar global belleğe doğrudan ham ara adım yazmaz.
- Önce `result.summary + evidence` üretir, Supervisor filtreleyip global belleğe yazar.
- Böylece kullanıcı tarafında gereksiz iç monolog ve token şişmesi önlenir.

### 7.3 Bağlam Aktarımı

- Supervisor, role’e sadece gerekli bağlamı geçirir (least-context principle).
- RAG/web bulguları Coder’a "minimal actionable brief" olarak taşınır.
- Reviewer çıktıları gerekiyorsa Coder’a "patch-risk constraints" olarak aktarılır.

---

## 8) Önerilen Dizin Yapısı

```text
agent/
  core/
    supervisor.py          # planlama, routing, orchestration
    contracts.py           # task envelope / protocol tipleri
    memory_hub.py          # global + local memory kuralları
    registry.py            # role-agent kayıt ve keşif
  roles/
    coder_agent.py         # code-centric tool set
    researcher_agent.py    # web + rag tool set
    reviewer_agent.py      # github/review tool set
  sidar_agent.py           # backward-compatible facade
```

### 8.1 Geriye Dönük Uyumluluk

- `SidarAgent` dış API’si korunur.
- İçeride `SupervisorAgent` delegasyonu varsayılan çalışma yolu olarak kullanılır.
- `ENABLE_MULTI_AGENT` artık rollout flag’i değil; mimari fiilen supervisor-first ve direct `p2p.v1` handoff ile çalışır.

---

## 8.2 Modül Durum Matrisi (Planlandı vs Uygulandı)

| Modül | RFC Durumu | Depo Durumu | Not |
|---|---|---|---|
| `agent/roles/reviewer_agent.py` | Planlandı | ✅ Uygulandı | GitHub PR/issue inceleme araçları + test çalıştırma aracı (`run_tests`) mevcut. |
| `agent/core/memory_hub.py` | Planlandı | ✅ Uygulandı | Global ve role-local kısa ömürlü bağlam notları tutuluyor. |
| `agent/core/registry.py` | Planlandı | ✅ Uygulandı | Role -> agent kayıt/keşif katmanı Supervisor içinde aktif kullanılıyor. |

## 9) Yürütüm Akışı (Sequence)

1. Kullanıcı isteği gelir.
2. Supervisor intent analizi yapar.
3. Plan çıkarır (N alt görev).
4. Görevleri uygun role dağıtır.
5. Role çıktıları toplanır/normalize edilir.
6. Gerekirse ikinci tur görevler tetiklenir.
7. Synthesizer nihai cevabı üretir.
8. Bellek + telemetry + audit kaydı tamamlanır.

---

## 10) Güvenlik ve Yetki Ayrımı

- Her role, policy bazlı tool whitelist uygulanır.
- Coder agent için execution araçları erişim seviyesine göre sınırlandırılır.
- Researcher doğrudan yazma tool’larına sahip olmaz.
- Reviewer doğrudan kod çalıştırma yetkisine sahip olmaz.
- Supervisor yalnızca orkestrasyon yapar, doğrudan güçlü tool çağırmaz (tercih edilen model).

---

## 11) Gözlemlenebilirlik (Tracing/Metrics)

Ek önerilen metrikler:

- `sidar.supervisor.route.count{role=...}`
- `sidar.supervisor.task.duration_ms{role=...}`
- `sidar.supervisor.retry.count`
- `sidar.agent.context_tokens{role=...}`
- `sidar.agent.tool_error.count{role=...,tool=...}`

Her alt göreve span:

- parent span: user request
- child span: supervisor planning
- child span(s): role execution
- child span: synthesis

---

## 12) Başarı Kriterleri

- Tool yanlış seçim oranında düşüş.
- Karma görevlerde ilk yanıtta doğruluk artışı.
- Ortalama token tüketiminde düşüş (context isolation).
- Testlerde role bazlı izole kapsam artışı.
- Yeni rol ekleme geliştirme süresinde azalma.

---

## 13) Riskler ve Azaltım Planı

1. **Orkestrasyon karmaşıklığı artışı**
   - Çözüm: Tek tip task contract + merkezi registry.
2. **Latency artışı (çok adım)**
   - Çözüm: kritik görevlerde tek-role fast-path, paralel bağımsız görevler.
3. **Handoff bilgi kaybı**
   - Çözüm: evidence zorunluluğu + structured result schema.
4. **Regresyon riski**
   - Çözüm: feature flag + kademeli rollout + A/B telemetry.

---

## 14) Geçiş Planı (Phased Rollout)

### Faz 0 — Tasarım ve Kontrat

- Bu RFC onayı
- `contracts.py`, `registry.py` iskeleti

### Faz 1 — Supervisor iskeleti + Coder role

- `SidarAgent` → supervisor delegasyon
- İlk üretim rollout’unda code ağırlıklı istekler öncelikli route edildi; bu faz artık tarihsel kayıt niteliğindedir

### Faz 2 — Researcher role

- web/rag görevleri ayrıştırılır
- context handoff optimize edilir

### Faz 3 — Reviewer role

- GitHub/PR review + dinamik QA test üretimi/sandbox regresyon akışı role bazlı taşınır

### Faz 4 — Varsayılan hale getirme

- Supervisor-first orkestrasyon varsayılan hale gelir
- Legacy tekli akış yalnızca tarihsel/deprecated not olarak kalır
- **Kapanış Notu (v3.2.0):** Supervisor + role tabanlı mimari artık yalnız başına bir yönlendirme kabiliyeti değil; active learning, vision, cost-aware routing ve dış sistem entegrasyonlarıyla birlikte Autonomous LLMOps omurgasının orkestrasyon katmanı olarak tanımlanır.
- **Operasyonel Teyit (v4.2.0):** `audit_logs` trail, direct `p2p.v1` handoff ve Supervisor/Swarm zinciri sayesinde çok ajanlı yapı denetlenebilir, kurumsal rollout'a hazır ve varsayılan mimari olarak kalıcıdır.

---

## 15) v3.0 Multi-User Hazırlık Planı (PostgreSQL + Redis)

- **Kimlik modeli:** `session_id` tekil yaklaşımı, `user_id` ile ilişkili çoklu oturum modeline evrilecek (`user_id -> sessions -> messages`).
- **PostgreSQL çekirdeği (öneri):**
  - `users(id, email, created_at, status)`
  - `sessions(id, user_id, title, created_at, archived_at)`
  - `messages(id, session_id, role, content, token_estimate, created_at)`
  - `provider_usage_daily(user_id, provider, prompt_tokens, completion_tokens, cost_usd, day)`
  - `user_quotas(user_id, daily_token_limit, daily_cost_limit, updated_at)`
- **Redis sıcak katman (öneri):**
  - `sidar:rl:{user_id}` (rate-limit)
  - `sidar:budget:{user_id}` (anlık bütçe sayaçları)
  - `sidar:session:{session_id}:hot` (kısa ömürlü aktif bağlam)
- **Geçiş stratejisi:** Strangler Pattern ile mevcut dosya tabanlı memory + Redis fallback yapısı korunurken, read-path kademeli olarak PostgreSQL'e alınacak.
- **Test planı (minimum):**
  1. Tek kullanıcı regresyon testi (mevcut davranış bozulmamalı).
  2. İki kullanıcı izolasyon testi (`user_a`/`user_b` oturum ve quota ayrışması).
  3. Rate-limit + budget enforcement testi (Redis + DB tutarlılığı).

## 16) Uygulama Sonucu ve Kapanış

Bu RFC artık yalnızca "çok ajanlı mimariye geçildi" bilgisini taşıyan tarihsel bir kapanış notu değildir; depo içindeki gerçek işletim modeli **telemetry-first gözlemlenebilirlik**, **swarm tabanlı hata izolasyonu** ve **audit-log ile denetlenebilir yürütüm** ilkeleri etrafında kalıcı olarak şekillenmiştir. Supervisor/Coder/Researcher/Reviewer ayrımı korunurken, operasyonel güvenceyi sağlayan katman artık rollerin varlığından çok bu rollerin nasıl izlendiği, birbirine nasıl görev devrettiği ve başarısızlıkların nasıl çevrelendiğidir.

### 16.1 Telemetry-first işletim modeli

- Her kullanıcı isteği, supervisor planlama adımı, swarm alt görevi ve sentez aşaması span/metric üretimine uygun şekilde ele alınır.
- `cfg.init_telemetry(...)` ile başlatılan OpenTelemetry hattı; FastAPI istekleri, `httpx` istemci çağrıları ve uygulama içi supervisor/swarm akışlarını aynı iz üzerinde ilişkilendirecek şekilde kullanılır.
- Hedef artık yalnızca "istek başarılı mı" sorusunu yanıtlamak değil; **hangi role neden route edildi**, **hangi alt görev ne kadar sürdü**, **hangi araç/handoff gecikme veya hata üretti** sorularını da üretim sırasında cevaplayabilmektir.
- Bu nedenle bu RFC'nin kapanış kriteri, mimarinin devreye alınmış olması kadar, Jaeger/OTEL üzerinden uçtan uca iz bırakabilen ve olay sonrası inceleme yapılabilen bir yürütüm modelinin yerleşmesidir.

### 16.2 Swarm ile hata izolasyonu ve kontrollü delegasyon

- `SwarmOrchestrator` artık mimarinin deneysel eki değil; karma görevleri tekil `SwarmTask` birimlerine bölerek ajan seçimi, paralel yürütüm ve doğrudan rol→rol handoff akışını yöneten operasyonel çekirdektir.
- Hata izolasyonu, bir alt görevin başarısız olmasının tüm kullanıcı isteğini körlemesine düşürmesi yerine, başarısızlığı ilgili task/route üzerinde sınırlandırmak ve geri kalan görevleri ölçülebilir biçimde sürdürmek üzerine kuruludur.
- `p2p.v1` bağlamı, `route_trace`, hop sınırları ve loop guard mekanizmaları; delegasyonun gözlenebilir, tekrar üretilebilir ve kendi üstüne çöken sonsuz yönlendirme döngülerine karşı dayanıklı olmasını sağlar.
- Böylece kapanış notu yalnızca "multi-agent tamamlandı" değil; **başarısızlık alanı küçültülmüş**, **fallback davranışı tanımlanmış** ve **swarm yürütümü testlerle çevrelenmiş** bir orkestrasyon katmanının kalıcı hale geldiğini ifade eder.

### 16.3 Audit logging ve kurumsal denetlenebilirlik

- Web/API erişim yolu, RBAC/policy çözümlemesi ve kaynak erişimi sonrasında `_schedule_access_audit_log(...)` üzerinden kullanıcı, tenant, kaynak, aksiyon ve allow/deny sonucunu kalıcı audit trail'e yazar.
- Audit kaydı burada yalnızca güvenlik eki değildir; supervisor/swarm mimarisinin kurumsal kabulü için gerekli olan "kim, neye, hangi yetki kararıyla erişti" sorusunun temel veri kaynağıdır.
- Çok ajanlı yürütümün kurumsal kapanışı; telemetry'nin olay akışını, swarm'ın görev izolasyonunu ve audit log'un yetki/erişim izini birlikte sunabildiği noktada anlam kazanır. Bu üçlüden biri eksik olduğunda mimari teknik olarak çalışsa bile operasyonel olarak tamamlanmış sayılmaz.

### 16.4 Son karar

Bu nedenle RFC-0001'in güncel kapanış kararı şudur: Sidar'da supervisor-first ve swarm destekli çok ajanlı mimari **uygulanmış**, **varsayılan hale gelmiş** ve **telemetry + audit trail + direct handoff doğrulamaları** ile üretim/kurumsal kullanım için denetlenebilir bir işletim modeline dönüştürülmüştür. `SidarAgent` geriye dönük uyumluluk yüzeyi olarak yaşamaya devam etse de mimarinin özü artık tekli ajan akışı değil; izlenebilir, ölçülebilir ve hata alanı sınırlandırılmış çok ajanlı orkestrasyondur.
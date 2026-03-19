# SİDAR v5.0 — İleri Düzey Otonomi ve Yeni Yetenekler Geliştirme Raporu

> **Durum:** Stratejik mimari öneri / ürünleşme planı  
> **Hazırlanma Tarihi:** 2026-03-19  
> **Kapsam:** `PROJE_RAPORU.md`, `README.md`, `core/vision.py`, `core/rag.py`, `agent/tooling.py`, `agent/swarm.py`, `agent/core/supervisor.py`, `managers/web_search.py`, `managers/code_manager.py`, `web_server.py`, `web_ui_react/src/components/SwarmFlowPanel.jsx`

---

## 1. Yönetici Özeti

SİDAR v4.2.0 itibarıyla güçlü bir **Autonomous LLMOps** platformuna dönüşmüş durumdadır: multimodal görsel analiz, hibrit RAG, direct P2P swarm, audit trail, HITL ve observability katmanları ürün seviyesinde mevcuttur. Buna rağmen sistem bugün hâlâ ağırlıklı olarak **reaktif** bir çalışma modeli izlemektedir; kullanıcı komutu geldiğinde araç çağıran gelişmiş bir mühendis asistanı gibi davranır.

**v5.0 hedefi**, bu temeli bozmadan SİDAR'ı gerçek anlamda bir **AI Co-Worker** seviyesine çıkarmaktır. Bunun için dört ana eksende ilerleme önerilir:

1. **Algı katmanını genişletmek:** statik görsel analizden video, ses ve gerçek zamanlı konuşmaya geçmek.
2. **Araç kullanma kabiliyetini derinleştirmek:** statik HTML çekmekten dinamik tarayıcı otomasyonuna ve LSP destekli güvenli kod manipülasyonuna yükselmek.
3. **Otonom orkestrasyonu kurumsal ölçekte büyütmek:** yalnızca dahili swarm yerine dış swarm protokolleri, cron/webhook uyanma mekanizmaları ve proaktif aksiyon akışları eklemek.
4. **Karar görünürlüğünü artırmak:** kullanıcıya ajanların ne düşündüğünü düz loglarla değil, görsel görev grafiği ve canlı çalışma yüzeyleri ile sunmak.

Bu rapor, önerilen yetenekleri mevcut dosya yapısına yerleştirerek, her başlık için **neden gerekli**, **nereye entegre edilmeli**, **minimum uygulanabilir kapsam**, **bağımlılıklar**, **riskler** ve **başarı ölçütleri** tanımlar.

---

## 1.1 Güncel Faz Durumu (2026-03-19)

| Başlık | Güncel Durum | Not |
|---|---|---|
| Algı katmanının genişletilmesi (MVP) | **✅ Faz A: Tamamlandı / Alpha** | `core/multimodal.py`, `/ws/voice` ve temel medya bağlamı hattı repo içinde çalışır durumda. |
| Tarayıcı otomasyonu başlangıcı | **✅ Faz A: Tamamlandı / Alpha** | `managers/browser_manager.py` ile Playwright/Selenium tabanlı yaşam döngüsü eklendi. |
| GraphRAG başlangıcı | **Faz A: İskelet Kuruldu** | `core/rag.py` içinde modül bağımlılık grafiği arama/yol açıklama akışı mevcut. |
| Reviewer + LSP anlamsal denetim | **✅ Faz B eşiği aşıldı** | Reviewer ajan refactor sonrası LSP diagnostics ile regresyon riskini anlamsal düzeyde raporlayabiliyor. |
| Proaktif otonomi omurgası | **✅ Faz A/B tamamlandı** | Webhook, manual wake ve cron tabanlı trigger akışları `web_server.py` + `agent/sidar_agent.py` üzerinde aktif. |
| Interactive CLI Launcher | **✅ Tamamlandı** | `main.py` ön kontrollü etkileşimli başlatıcı olarak ürünleşti. |

## 2. Mevcut Mimari Dayanaklar

v5.0 önerileri sıfırdan yeni bir platform tasarlamak için değil, mevcut güçlü omurgayı genişletmek için hazırlanmıştır.

### 2.1 Bugün zaten güçlü olan alanlar

- **Multimodal girişin ilk adımı hazır:** `core/vision.py` görsel yükleme, provider'a özel vision message üretimi ve `VisionPipeline` üzerinden görselden kod / analiz akışı sağlıyor; ek olarak `core/multimodal.py` ve `/ws/voice` ile Faz A iskeleti kurulmuş durumda.
- **Araç çağırma ve şema doğrulama altyapısı hazır:** `agent/tooling.py` JSON-object tabanlı typed tool argument doğrulaması ile yeni araçları güvenli biçimde eklemeye uygun.
- **Swarm ve P2P delege zinciri hazır:** `agent/swarm.py` ve `agent/core/supervisor.py` görev yönlendirme, handoff depth, trace ve QA retry davranışlarını zaten yönetiyor.
- **RAG katmanı hibrit aramaya uygun:** `core/rag.py` ChromaDB + BM25 tabanı üzerine yeni retrieval stratejileri eklemek için iyi bir temel sunuyor.
- **Web kontrol düzlemi genişlemeye uygun:** `web_server.py` hâlihazırda REST + WebSocket + HITL + swarm yürütme gibi akışları barındırıyor.
- **UI'da operasyon paneli çekirdeği var:** `web_ui_react/src/components/SwarmFlowPanel.jsx` bugün görev listesi ve telemetri zaman çizelgesi sunuyor; bunu node-graph karar görünürlüğüne büyütmek mümkün.

### 2.2 v5.0 ile çözülmek istenen açıklar

- Video/ses odaklı hata bildirimleri doğrudan anlaşılamıyor.
- Dinamik web uygulamalarında gerçek tarayıcı işlemi yapılamıyor.
- Kod tabanındaki anlamsal/ilişkisel bağımlılıklar artık ilk GraphRAG iskeleti ile modellenmeye başladı; ancak etki analizi ve reviewer entegrasyonu henüz erken aşamada.
- IDE seviyesinde güvenli refactor işlemleri için LSP araçları eklenmiş olsa da Reviewer ajanı bu çıktıları henüz tam anlamsal kalite kapısı olarak kullanmıyor.
- Sistem kullanıcı yazmadan kendi kendine tetiklenen bir ajan mimarisine tam geçmedi.
- Swarm karar süreçleri telemetri listesinde görülüyor, fakat görsel karar grafiği olarak keşfedilemiyor.

---

## 3. v5.0 Hedef Mimarisi

### 3.1 Ürün tanımı

**Yeni ürün tanımı:** SİDAR, yalnızca komut alan bir asistan değil; bağlamı çoklu modalitelerde anlayan, gerektiğinde kendini tetikleyen, hem kod tabanında hem tarayıcıda güvenli operasyon yapabilen ve karar sürecini kullanıcıya şeffaf biçimde gösteren bir **otonom yapay zeka takım arkadaşıdır**.

### 3.2 Mimarinin dört sütunu

| Sütun | Hedef | Ana dosyalar |
|---|---|---|
| Çoklu algı (Perception) | Görsel + video + ses + canlı sesli etkileşim | `core/vision.py`, yeni `core/multimodal.py`, yeni `core/voice.py`, `web_server.py` |
| Araç derinliği (Actionability) | Browser automation + LSP + gelişmiş tool şemaları | `agent/tooling.py`, `managers/browser_manager.py`, `managers/code_manager.py` |
| Proaktif otonomi (Autonomy) | Webhook/cron ile uyanan, dış swarm ile konuşan ajanlar | `agent/core/contracts.py`, `agent/swarm.py`, `agent/sidar_agent.py`, `web_server.py` |
| Karar görünürlüğü (Transparency) | Görsel swarm akışı ve canlı çalışma yüzeyleri | `web_ui_react/src/components/SwarmFlowPanel.jsx` |

---

## 4. Çekirdek AI ve Algı Yetenekleri

### 4.1 Multimodal Audio/Video Processing

**Öneri:** `core/vision.py` içindeki mevcut görsel odaklı yapı, daha geniş bir `core/multimodal.py` çatısı altında evrilmeli; görsel analiz korunurken video ve ses işleme pipeline'ı eklenmelidir.

#### Neden elzem?

- Geliştirici ekipleri bug raporlarını çoğu zaman **ekran kaydı**, Loom videosu, kısa MP4 veya sesli anlatımla paylaşır.
- UI/UX hataları, loading race condition'lar, animasyon bug'ları ve flaky davranışlar çoğu zaman statik ekran görüntüsü ile tam anlaşılamaz.
- SİDAR'ın bir kayıt içinden **frame seçmesi**, sesi **transkript etmesi** ve bunları ortak bağlama dönüştürmesi, hata analizinde ciddi sıçrama sağlar.

#### Dosya düzeyinde öneri

- **Kısa vade:** `core/vision.py` korunur, içine video/ses yardımcıları eklenmez; bunun yerine yeni `core/multimodal.py` oluşturulur.
- **Orta vade:** `core/vision.py` içindeki reusable parçalar (`build_vision_messages`, görsel yükleme, prompt oluşturma) `core/multimodal.py` içine taşınır; `core/vision.py` geriye uyumluluk katmanı olur.

#### Önerilen modüller

- `core/multimodal.py`
  - `extract_video_frames(path, strategy="scene-change" | "fixed-interval")`
  - `extract_audio_track(path)`
  - `transcribe_audio(path, provider="whisper")`
  - `build_multimodal_context(...)`
  - `MultimodalPipeline.analyze_media(...)`
- `core/vision.py`
  - Geriye uyum için `VisionPipeline` export etmeye devam eder.

#### Minimum uygulanabilir kapsam (MVP)

1. MP4/WebM dosyası al.
2. Sabit aralıkla 1–N frame çıkar.
3. Ses kanalını ayır.
4. Whisper benzeri STT ile transkript üret.
5. Frame özetleri + transkripti tek bir bağlama dönüştür.
6. Mevcut LLM istemcisine gönder.

#### Başarı ölçütleri

- 5 dakikalık bir ekran kaydı için < 90 saniyede özet bağlam üretimi.
- Bir medya dosyasından çıkarılan transkript + frame raporunun tekil hata kök nedenini tarif edebilmesi.
- En az bir örnek akışta: "video yükle → hata bul → aksiyon planı üret" uçtan uca demo.

#### Riskler

- Dosya boyutu ve inference maliyeti yükselebilir.
- Frame sampling kalitesiz olursa kritik anlar kaçabilir.
- STT sonuçları gürültülü seslerde bağlamı bozabilir.

---

### 4.2 Gerçek Zamanlı Sesli İletişim (Voice-to-Voice)

**Öneri:** `web_server.py` içine yeni `/ws/voice` rotası, çekirdeğe ise yeni `core/voice.py` modülü eklenmelidir.

#### Hedef davranış

- Kullanıcı mikrofon akışını WebSocket üzerinden gönderir.
- Sunucu sesi parçalara ayırır ve transkript eder.
- LLM yanıtı üretir.
- İsteğe bağlı TTS ile sesli yanıt geri döner.

#### Mimari yerleşim

- `core/voice.py`
  - ses çerçeveleme / buffering
  - VAD (voice activity detection)
  - STT adaptörü
  - TTS adaptörü
- `web_server.py`
  - `/ws/voice`
  - session auth, rate limit, partial transcript event'leri
- `web_ui_react/`
  - push-to-talk veya streaming microphone istemcisi

#### Neden önemli?

Bu yetenek, SİDAR'ı günlük akışta **yan pencere asistandan** çok daha doğal bir mühendislik partnerine dönüştürür. Özellikle incident response, pair debugging ve hızlı brainstorming oturumlarında büyük fark yaratır.

#### MVP sınırı

- İlk fazda yalnızca **voice-to-text + text response** yeterlidir.
- Tam duplex voice-to-voice ikinci iterasyonda eklenebilir.

---

### 4.3 GraphRAG (Bilgi Grafiği Tabanlı Retrieval)

**Öneri:** `core/rag.py` içindeki hibrit retrieval, bilgi grafiği katmanı ile genişletilmelidir.

#### Problem

Bugünkü hibrit RAG semantik benzerlik ve keyword arama açısından güçlüdür; ancak şu soruları sınırlı çözer:

- `A modülü hangi zincir üzerinden B modülüne bağımlı?`
- `Bu endpoint hangi manager → core → db akışını çağırıyor?`
- `Bir sınıfın etkilediği tüm çağrı halkası nedir?`

#### Mimari yaklaşım

- **İlişki çıkarımı:** import grafı, class/function referansları, endpoint → manager → core çağrıları.
- **Graf veri modeli:** basit başlangıç için `networkx`; kurumsal ölçekte `Neo4j` opsiyonel.
- **Birleşik retrieval:** önce graph hop sorgusu, sonra vektör/BM25 ile düğüm belgelerini zenginleştirme.

#### Dosya düzeyinde değişim

- `core/rag.py`
  - `GraphIndex` veya `GraphRAGStore` entegrasyonu
  - `search_graph(...)`
  - `explain_dependency_path(source, target)`
- `managers/code_manager.py`
  - statik analiz çıktılarının graph node/edge üretimine beslenmesi

#### Başarı ölçütleri

- Belirli iki modül arasında bağımlılık yolunun açıklanması.
- Endpoint bazlı etki analizi raporlarının daha az halüsinasyonla üretilmesi.
- Büyük repo analizlerinde “mimari harita” özetlerinin tutarlılığının artması.

---

## 5. Dış Dünya ve Sistem Etkileşimi

### 5.1 Dinamik Tarayıcı Otomasyonu (Computer Use / Browser Automation)

**Öneri:** `managers/web_search.py` yanına yeni `managers/browser_manager.py` eklenmeli; `agent/tooling.py` ise tarayıcı eylemleri için typed şemalar kazanmalıdır.

#### Neden elzem?

SİDAR bugün web sayfası içeriği **çekebiliyor**, fakat dinamik SaaS ekranlarında işlem yapamıyor. Oysa modern mühendislik işleri çoğu zaman tarayıcı üstünden gerçekleşir:

- Jira issue açma / güncelleme
- CI dashboard'ında failed run inceleme
- AWS/Grafana/Kibana konsolunda veri toplama
- Form doldurma, buton tıklama, modal kontrolü

#### Önerilen araçlar

- `open_browser`
- `goto_url`
- `click_element`
- `fill_form`
- `select_option`
- `scroll_page`
- `capture_dom`
- `capture_screenshot`
- `close_browser`

#### Dosya yerleşimi

- `managers/browser_manager.py`
  - Playwright tabanlı tarayıcı yaşam döngüsü
  - selector güvenliği ve allowlist mantığı
  - screenshot / DOM snapshot üretimi
- `agent/tooling.py`
  - yukarıdaki araçlar için Pydantic şemaları
- `web_server.py`
  - uzun süren browser session'larını takip eden servis katmanı (opsiyonel)

#### Güvenlik şartları

- Domain allowlist / denylist
- Session recording / audit log
- HITL onayı olmadan yüksek riskli aksiyon yapmama
- Secret alanlarına yazı yazarken DLP filtresi

---

### 5.2 LSP (Language Server Protocol) Entegrasyonu

**Öneri:** `managers/code_manager.py` içinde LSP tabanlı analiz ve refactor yardımcıları eklenmelidir.

#### Neden kritik?

Regex/grep ile çalışan ajanlar hızlıdır ama güvenli refactor için yeterli değildir. LSP destekli ajan şunları çok daha güvenilir yapabilir:

- Go to Definition
- Find All References
- Rename Symbol
- Workspace diagnostics
- Code action önerileri

#### Mimari yaklaşım

- Python için Pyright/Pylance uyumlu kanal veya Jedi tabanlı ilk entegrasyon.
- TypeScript için tsserver tabanlı provider.
- Tool yüzeyine yalnızca **yüksek seviye güvenli komutlar** açılmalı; ham JSON-RPC doğrudan expose edilmemeli.

#### Önerilen araçlar

- `lsp_find_references`
- `lsp_go_to_definition`
- `lsp_rename_symbol`
- `lsp_workspace_diagnostics`

#### Başarı ölçütleri

- Bir sembolün tüm referansları güvenilir şekilde listelenebilmeli.
- Çok dosyalı rename işlemi dry-run + onaylı apply şeklinde yapılabilmeli.
- Review ajanı, refactor sonrası LSP diagnostics ile regresyon riskini raporlayabilmeli.

---

## 6. Ajan ve Orkestrasyon Mimarisi

### 6.1 External Swarm Interoperability

**Öneri:** `agent/core/contracts.py` içindeki sözleşme yaklaşımı, dış orchestrator'larla konuşabilecek şekilde genişletilmelidir.

#### Hedef

SİDAR yalnızca kendi Coder/Reviewer/Researcher ajanlarını yönetmekle kalmamalı; gerektiğinde şirket içindeki başka bir swarm sistemine görev devredebilmelidir.

#### Olası entegrasyonlar

- CrewAI tabanlı servisler
- AutoGen tabanlı ajan kümeleri
- Dahili HTTP/gRPC agent gateway'leri

#### Gerekli yetenekler

- Federated task envelope
- Capability discovery endpoint'i
- Timeout / retry / fallback politikası
- Güven ilişkisi: imzalı görev çağrıları veya servis token'ları

#### Dosya önerisi

- `agent/core/contracts.py`
  - `federation.v1` benzeri yeni sözleşme modeli
- `agent/swarm.py`
  - local-first, remote-capable routing
- `agent/core/supervisor.py`
  - dış ajan başarısız olursa yerel fallback

---

### 6.2 Proaktif Uyanan Ajanlar (Cron / Webhook Agents)

**Öneri:** SİDAR reaktif moddan proaktif moda geçebilmek için webhook ve scheduler tabanlı uyanma mekanizmaları kazanmalıdır.

#### Örnek senaryolar

- CI pipeline fail olduğunda webhook ile uyan.
- Son logları topla.
- Hata kök nedenini tahmin et.
- Gerekirse patch öner.
- Kullanıcıya "PR taslağı hazır" bildirimi gönder.

#### Dosya düzeyinde öneri

- `web_server.py`
  - yeni webhook endpoint'leri (`/api/hooks/ci`, `/api/hooks/alerts` gibi)
- `agent/sidar_agent.py`
  - insan mesajı olmadan da çalışabilen sistem-görevi giriş noktası
- yeni `core/scheduler.py` veya `managers/trigger_manager.py`
  - cron, debounce, retry, dedupe

#### Kontroller

- Fail-open değil fail-closed davranış
- Her proaktif aksiyonda audit trail
- Yüksek riskli aksiyonlarda HITL kapısı

---

## 7. Kullanıcı Deneyimi ve Arayüz

### 7.1 Visual Chain-of-Thought / Decision Graph Explorer

**Öneri:** `web_ui_react/src/components/SwarmFlowPanel.jsx` düz timeline yaklaşımından, düğüm/graf tabanlı görselleştirmeye taşınmalıdır.

#### Neden önemli?

Swarm davranışı ne kadar otonom olursa, kullanıcı tarafında **güven ve izlenebilirlik** o kadar önemli olur. Kararların neden alındığını görmek; hatalı delege zincirlerini, reviewer-coder döngülerini ve tıkanan görevleri anlamayı kolaylaştırır.

#### Önerilen görünüm

- Düğümler: agent step, tool call, review decision, external handoff, HITL gate
- Kenarlar: delegation, retry, reject, approve, completion
- Sağ panel: seçili node detayları, kullanılan araçlar, özet reasoning, süre

#### Teknik yaklaşım

- İlk iterasyon: mevcut `telemetryEvents` verisinden graph modeli türet.
- Görselleştirme: React Flow / Cytoscape.js gibi bir kütüphane.
- Filtreler: agent, status, duration, session id.

---

### 7.2 Live Collaborative Editor / IDE Entegrasyonu

**Öneri:** Web UI dışına taşan bir entegrasyon katmanı planlanmalıdır.

#### Hedefler

- VS Code / Cursor eklentisi
- Açık dosya bağlamını SİDAR'a aktarma
- LSP + agent + HITL üçlüsünü editör içine taşıma
- Diff / patch önerilerini inline gösterebilme

#### Ürün etkisi

Bu yetenek, SİDAR'ın yalnızca ayrı bir web uygulaması değil, geliştiricinin günlük IDE akışı içinde çalışan gerçek bir takım arkadaşı olmasını sağlar.

---

## 8. Önceliklendirme ve Fazlama

### Faz A — Elzem v5.0 Çekirdeği

1. `docs` + mimari karar kaydı ile v5.0 hedeflerinin netleştirilmesi **(tamamlandı)**
2. `core/multimodal.py` başlangıcı (video frame + STT) **(✅ tamamlandı / alpha)**
3. `managers/browser_manager.py` + temel Playwright araçları **(✅ tamamlandı / alpha)**
4. `agent/tooling.py` içine browser/LSP tool şemaları **(başlatıldı)**
5. `web_server.py` webhook tabanlı proaktif trigger girişleri **(✅ tamamlandı)**
6. `SwarmFlowPanel.jsx` için graph veri modeli **(✅ tamamlandı)**
7. `main.py` interactive CLI launcher **(✅ tamamlandı)**

### Faz B — Güvenli Otonomi Derinleşmesi

1. GraphRAG indeksleyicinin reviewer/etki analizi ile derinleştirilmesi
2. LSP entegrasyonunun Reviewer ajan kalite kapısına bağlanması **(✅ tamamlandı)**
3. HITL + audit ile yüksek riskli browser aksiyonları
4. Proaktif CI remediation akışları

### Faz C — AI Co-Worker Deneyimi

1. `/ws/voice`
2. Tam voice-to-voice akış
3. Harici swarm federasyonu
4. IDE eklentileri

---

## 9. Mimari Karar İlkeleri

v5.0 geliştirmeleri aşağıdaki ilkelere bağlı kalmalıdır:

1. **Geriye uyumlu genişleme:** mevcut `core/vision.py`, `core/rag.py`, `agent/swarm.py` gibi dosyalar kırılmadan evrilmeli.
2. **Fail-closed güvenlik:** browser automation ve proaktif ajanlar varsayılan olarak kısıtlı başlamalı.
3. **Açıklanabilirlik:** her otonom aksiyon audit edilebilir ve UI'da izlenebilir olmalı.
4. **Provider agnosticism:** video/STT/TTS/LSP/browser katmanları tek sağlayıcıya kilitlenmemeli.
5. **Aşamalı ürünleşme:** her yetenek için önce MVP, sonra kurumsal sertleştirme yapılmalı.

---

## 10. Önerilen Teknik Backlog

| Öncelik | İş kalemi | Ana dosyalar | Çıktı |
|---|---|---|---|
| P0 | v5.0 mimari raporunun repo içine alınması | `docs/`, `README.md`, `PROJE_RAPORU.md` | Ortak ürün vizyonu |
| P0 | Multimodal medya ingestion MVP | `core/multimodal.py`, `core/vision.py` | ✅ Video + ses bağlam üretimi |
| P0 | Browser automation manager | `managers/browser_manager.py`, `agent/tooling.py` | ✅ Dinamik web aksiyonları |
| P1 | Webhook/proaktif ajan omurgası | `web_server.py`, `agent/sidar_agent.py` | ✅ Reaktif → proaktif geçiş |
| P1 | Decision graph UI | `web_ui_react/src/components/SwarmFlowPanel.jsx` | ✅ Görsel swarm görünürlüğü |
| P1 | GraphRAG prototipi | `core/rag.py`, `managers/code_manager.py` | Mimari bağımlılık sorguları |
| P2 | LSP entegrasyonu | `managers/code_manager.py` | ✅ Güvenli refactor |
| P2 | Voice WebSocket akışı | `core/voice.py`, `web_server.py` | Gerçek zamanlı konuşma |
| P3 | External swarm federation | `agent/core/contracts.py`, `agent/swarm.py` | Kurumsal çoklu ajan federasyonu |
| P3 | IDE eklentileri | yeni `extensions/` veya ayrı repo | Inline co-worker deneyimi |

---

## 11. Sonuç

SİDAR bugün güçlü bir otonom mühendislik platformudur; ancak v5.0 ile hedef yalnızca daha fazla araç eklemek değildir. Asıl hedef, sistemi şu üç nitelikte ileri taşımaktır:

- **Daha çok algılayan** (video, ses, canlı konuşma)
- **Daha çok iş yapan** (browser, LSP, proaktif trigger, dış swarm)
- **Daha çok güven veren** (graph görünürlük, audit, HITL, explainability)

Bu rapordaki öneriler, mevcut dosya yapısını bozmadan SİDAR'ın bir sonraki büyük sıçramasını tanımlar: **gelişmiş AI asistanı → otonom AI takım arkadaşı**. 
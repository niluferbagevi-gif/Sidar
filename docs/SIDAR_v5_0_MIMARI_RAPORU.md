# SİDAR v5.0 — İleri Düzey Otonomi ve Yeni Yetenekler Geliştirme Raporu

> **Durum:** Faz A ve Faz B tamamlandı; Faz C odağına geçmiş stratejik mimari raporu
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

Bu rapor, ürünleşen yetenekleri mevcut dosya yapısı içinde belgeleyerek her başlık için **neden önemli**, **nereye entegre edildiği**, **uygulanan pipeline akışı**, **bağımlılıklar** ve **sonraki Faz C odaklarını** tanımlar.

---

## 1.1 Güncel Faz Durumu (2026-03-20)

| Başlık | Güncel Durum | Not |
|---|---|---|
| Algı katmanının genişletilmesi (MVP) | **✅ Faz A: Tamamlandı / Beta'ya Hazır** | `core/multimodal.py`, `/ws/voice` ve `core/voice.py` üzerinden medya bağlamı + TTS segmentasyon hattı repo içinde çalışır durumda. |
| Tarayıcı otomasyonu başlangıcı | **✅ Faz A: Tamamlandı / Beta'ya Hazır** | `managers/browser_manager.py` ile Playwright/Selenium tabanlı yaşam döngüsü ve HITL onay kapısı eklendi. |
| GraphRAG + Reviewer etki analizi | **✅ Faz B: Tamamlandı** | `core/rag.py` içindeki modül bağımlılık grafiği arama/yol açıklama akışı reviewer ajanında birleşik etki analizi ve hedef önerileri üretir. |
| Reviewer + LSP anlamsal denetim | **✅ Faz B: Tamamlandı** | Reviewer ajanı artık LSP diagnostics ile GraphRAG etki analizi sinyallerini aynı kalite kapısında birleştiriyor. |
| Proaktif otonomi omurgası | **✅ Faz A/B tamamlandı** | Webhook, manual wake ve cron tabanlı trigger akışları `web_server.py` + `agent/sidar_agent.py` üzerinde aktif. |
| Swarm karar grafiği + operasyon yüzeyi | **✅ Faz B: Tamamlandı** | `SwarmFlowPanel.jsx`, node/edge tabanlı handoff görselleştirmesini canlı operasyon yüzeyine taşıdı; seçili düğümden rerun/follow-up/HITL müdahalesi yapılabiliyor. |
| Interactive CLI Launcher | **✅ Tamamlandı** | `main.py` ön kontrollü etkileşimli başlatıcı olarak ürünleşti. |

## 1.2 Faz B Tamamlanma Özeti

Faz A kapanışından sonra tanımlanan üç Faz B hedefi de repo içinde kapanmıştır: GraphRAG sinyalleri reviewer kalite kapısına bağlanmış, `/ws/voice` hattı duplex state/buffer ve barge-in interrupt davranışı kazanmış, `SwarmFlowPanel` ise ajan handoff zincirini node-graph olarak görselleştirmekten öte canlı operasyon yüzeyine dönüşmüştür. Böylece SİDAR artık yalnızca medya anlayan ve proaktif uyanan bir sistem değil; karar gerekçesini, kod etkisini, dış olay korelasyonunu ve operatör müdahalesini görünür hale getiren bir **AI Co-Worker altyapısı** sunmaktadır.

1. **GraphRAG → Reviewer entegrasyonu tamamlandı:** bağımlılık grafiği, etki analizi ve `lsp_diagnostics` sinyalleri aynı kalite kapısında birleşiyor.
2. **Tam Voice-to-Voice duplex'in Faz B kapsamı tamamlandı:** assistant turn metadata'sı, duplex output buffer ve VAD tabanlı interrupt temizliği aktif.
3. **Swarm akışı görselleştirildi:** `SwarmFlowPanel` ve ilişkili UI yüzeylerinde ajan kararları node-graph biçiminde keşfedilebilir hale geldi.

Bu özet, repo içindeki Faz A/B kazanımlarını artık "öneri" değil, ürünleşmiş baseline kabulleri olarak tanımlar; raporun geri kalanı da bundan sonra Faz C deneyim derinleşmesini bu yeni temel üzerinden okur.

## 2. Mevcut Mimari Dayanaklar

v5.0 önerileri sıfırdan yeni bir platform tasarlamak için değil, mevcut güçlü omurgayı genişletmek için hazırlanmıştır.

### 2.1 Bugün zaten güçlü olan alanlar

- **Multimodal girişin ilk adımı hazır:** `core/vision.py` görsel yükleme, provider'a özel vision message üretimi ve `VisionPipeline` üzerinden görselden kod / analiz akışı sağlıyor; ek olarak `core/multimodal.py`, `/ws/voice` ve `core/voice.py` ile Faz A hedefleri alpha seviyesinde tamamlandı.
- **Araç çağırma ve şema doğrulama altyapısı hazır:** `agent/tooling.py` JSON-object tabanlı typed tool argument doğrulaması ile yeni araçları güvenli biçimde eklemeye uygun.
- **Swarm ve P2P delege zinciri hazır:** `agent/swarm.py` ve `agent/core/supervisor.py` görev yönlendirme, handoff depth, trace ve QA retry davranışlarını zaten yönetiyor.
- **RAG katmanı hibrit aramaya uygun:** `core/rag.py` ChromaDB + BM25 tabanı üzerine yeni retrieval stratejileri eklemek için iyi bir temel sunuyor.
- **Web kontrol düzlemi genişlemeye uygun:** `web_server.py` hâlihazırda REST + WebSocket + HITL + swarm yürütme gibi akışları barındırıyor.
- **UI'da canlı operasyon yüzeyi hazır:** `web_ui_react/src/components/SwarmFlowPanel.jsx` artık görev listesi/telemetriye ek olarak node-graph handoff görünümü, seçili node aksiyonları ve HITL karar yüzeyi sunuyor; Faz C'de odak bu yüzeyi remediation/self-healing ve daha derin browser sinyalleri ile beslemek.

### 2.2 v5.0 ile çözülmek istenen açıklar

- Video/ses odaklı hata bildirimleri doğrudan anlaşılamıyor.
- Dinamik web uygulamalarında gerçek tarayıcı işlemi yapılamıyor.
- Kod tabanındaki anlamsal/ilişkisel bağımlılıklar GraphRAG iskeletinden reviewer kalite kapısına taşındı; sonraki açık, bunu daha ileri remediation ve dış bilgi katmanlarıyla derinleştirmek.
- LSP araçları ve Reviewer entegrasyonu artık GraphRAG etki analizi ile birleşik çalışıyor; sıradaki açık, otomatik düzeltme/remediation döngüsünü daha kontrollü hale getirmektir.
- Sistem artık cron/webhook tabanlı kendi kendine uyanma omurgasına sahip; sıradaki açık, bu omurganın daha zengin dış sistem korelasyonu ve aksiyon geri beslemesiyle güçlendirilmesidir.
- Swarm karar süreçleri artık telemetri listesine ek olarak görsel karar grafiği halinde keşfedilebiliyor; sıradaki açık, grafiği canlı görev kontrolleriyle zenginleştirmektir.

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

**Gerçekleştirilen uygulama:** `core/vision.py` korunurken video/ses işleme hattı `core/multimodal.py` altında ürünleştirildi; görsel analiz ile medya çözümleme aynı multimodal bağlama akacak şekilde yapılandırıldı.

#### Neden elzem?

- Geliştirici ekipleri bug raporlarını çoğu zaman **ekran kaydı**, Loom videosu, kısa MP4 veya sesli anlatımla paylaşır.
- UI/UX hataları, loading race condition'lar, animasyon bug'ları ve flaky davranışlar çoğu zaman statik ekran görüntüsü ile tam anlaşılamaz.
- SİDAR'ın bir kayıt içinden **frame seçmesi**, sesi **transkript etmesi** ve bunları ortak bağlama dönüştürmesi, hata analizinde ciddi sıçrama sağlar.

#### Mevcut dosya yerleşimi

- **Kısa vade:** `core/vision.py` korunur, içine video/ses yardımcıları eklenmez; bunun yerine yeni `core/multimodal.py` oluşturulur.
- **Orta vade:** `core/vision.py` içindeki reusable parçalar (`build_vision_messages`, görsel yükleme, prompt oluşturma) `core/multimodal.py` içine taşınır; `core/vision.py` geriye uyumluluk katmanı olur.

#### Mevcut modüller

- `core/multimodal.py`
  - `extract_video_frames(path, strategy="scene-change" | "fixed-interval")`
  - `extract_audio_track(path)`
  - `transcribe_audio(path, provider="whisper")`
  - `build_multimodal_context(...)`
  - `MultimodalPipeline.analyze_media(...)`
- `core/vision.py`
  - Geriye uyum için `VisionPipeline` export etmeye devam eder.

#### Uygulanan Pipeline Akışı

1. `core/multimodal.py`, MP4/WebM benzeri girdileri kabul edip FFmpeg üzerinden frame ve ses izini ayrıştırır.
2. Frame çıkarma stratejisi sabit aralıklı veya sahne değişimi ağırlıklı örnekleme mantığıyla medya bağlamını üretir.
3. Ayrılan ses izi STT katmanına aktarılır ve konuşma içeriği metne dönüştürülür.
4. Frame özetleri ile transkript tek bir multimodal bağlam paketine birleştirilir.
5. Bu birleşik bağlam Reviewer/LLM akışlarına iletilerek hata analizi, kök neden çıkarımı ve aksiyon önerileri oluşturulur.

#### Riskler

- Dosya boyutu ve inference maliyeti yükselebilir.
- Frame sampling kalitesiz olursa kritik anlar kaçabilir.
- STT sonuçları gürültülü seslerde bağlamı bozabilir.

---

### 4.2 Gerçek Zamanlı Sesli İletişim (Voice-to-Voice)

**Durum:** `/ws/voice` rotası ve `core/voice.py` çekirdeği alpha seviyesinde çalışıyor; TTS adaptörleri artık duplex output buffer durumu, assistant turn kimliği ve VAD tabanlı interrupt/barge-in temizliği ile daha düşük gecikmeli çift yönlü akışı destekliyor.

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

#### Güncel Faz B derinleşmesi

- İlk alpha fazındaki **voice-to-text + text response + opsiyonel TTS segmentasyonu** iskeleti korunur.
- Bunun üzerine duplex state/buffer yönetimi, assistant turn metadata'sı ve VAD tabanlı barge-in interrupt temizliği eklenmiştir.
- Sonraki iterasyon odağı; daha ince taneli gerçek VAD/STT zamanlaması ve istemci tarafında oynatma ACK/clock senkronizasyonudur.

---

### 4.3 GraphRAG (Bilgi Grafiği Tabanlı Retrieval)

**Mevcut mimari:** `core/rag.py` içindeki hibrit retrieval, GraphRAG katmanı ile genişletildi; bağımlılık yolları, etki alanı ve reviewer hedefleri artık aynı retrieval yüzeyinde üretilebiliyor.

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

#### Uygulanan Pipeline Akışı

- Statik ilişki çıkarımı ile modül bağımlılık grafiği oluşturulur.
- Graph sorguları reviewer akışına etki alanı, risk seviyesi ve hedef dosya listesi olarak beslenir.
- Vektör/BM25 retrieval çıktıları graph bulgularıyla birleştirilerek daha yönlendirici remediation raporları üretilir.

---

## 5. Dış Dünya ve Sistem Etkileşimi

### 5.1 Dinamik Tarayıcı Otomasyonu (Computer Use / Browser Automation)

**Durum:** `managers/browser_manager.py` eklendi; `agent/tooling.py` tarafındaki typed browser şemaları başlatıldı ve yüksek riskli aksiyonlar HITL ile korunuyor.

#### Neden elzem?

SİDAR bugün web sayfası içeriği **çekebiliyor**, fakat dinamik SaaS ekranlarında işlem yapamıyor. Oysa modern mühendislik işleri çoğu zaman tarayıcı üstünden gerçekleşir:

- Jira issue açma / güncelleme
- CI dashboard'ında failed run inceleme
- AWS/Grafana/Kibana konsolunda veri toplama
- Form doldurma, buton tıklama, modal kontrolü

#### Mevcut araçlar

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

**Gerçekleştirilen uygulama:** `managers/code_manager.py` içinde LSP tabanlı analiz ve refactor yardımcıları eklendi; Pyright ve TypeScript Language Server diagnostics artık reviewer kalite kapısına bağlanmış durumda.

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

#### Mevcut araçlar

- `lsp_find_references`
- `lsp_go_to_definition`
- `lsp_rename_symbol`
- `lsp_workspace_diagnostics`

#### Uygulanan Pipeline Akışı

- Güvenli yüksek seviye LSP komutları tool yüzeyine açılır.
- Reviewer ajanı bu diagnostics verisini GraphRAG ve test sinyalleriyle birleştirir.
- Çok dosyalı değişikliklerde dry-run, etki analizi ve kalite kapısı aynı orkestrasyon içinde değerlendirilir.

---

## 6. Ajan ve Orkestrasyon Mimarisi

### 6.1 External Swarm Interoperability

**Mevcut mimari:** `agent/core/contracts.py` içindeki sözleşme yaklaşımı `federation` ve correlation-id odaklı genişletmelerle dış orchestrator'larla konuşabilecek biçimde ilerletildi.

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

**Gerçekleştirilen uygulama:** SİDAR, webhook ve scheduler tabanlı uyanma mekanizmaları kazandı; `web_server.py` ve `agent/sidar_agent.py` üzerinden proaktif cron/manual wake/federation akışları çalışıyor.

#### Örnek senaryolar

- CI pipeline fail olduğunda webhook ile uyan.
- Son logları topla.
- Hata kök nedenini tahmin et.
- Gerekirse patch öner.
- Kullanıcıya "PR taslağı hazır" bildirimi gönder.

#### Mevcut dosya yerleşimi

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

**Gerçekleştirilen uygulama:** `web_ui_react/src/components/SwarmFlowPanel.jsx` düz timeline yaklaşımından node/graf tabanlı görselleştirmeye taşındı ve canlı operasyon yüzeyi haline geldi.

#### Neden önemli?

Swarm davranışı ne kadar otonom olursa, kullanıcı tarafında **güven ve izlenebilirlik** o kadar önemli olur. Kararların neden alındığını görmek; hatalı delege zincirlerini, reviewer-coder döngülerini ve tıkanan görevleri anlamayı kolaylaştırır.

#### Mevcut görünüm

- Düğümler: agent step, tool call, review decision, external handoff, HITL gate
- Kenarlar: delegation, retry, reject, approve, completion
- Sağ panel: seçili node detayları, kullanılan araçlar, özet reasoning, süre

#### Teknik yaklaşım

- İlk iterasyon: mevcut `telemetryEvents` verisinden graph modeli türet.
- Görselleştirme: React Flow / Cytoscape.js gibi bir kütüphane.
- Filtreler: agent, status, duration, session id.

---

### 7.2 Live Collaborative Editor / IDE Entegrasyonu

**Faz C odağı:** Web UI dışına taşan entegrasyon katmanı planı korunuyor; mevcut baseline artık web UI içindeki canlı operasyon yüzeyini, HITL aksiyonlarını ve swarm graph görünürlüğünü üretimde taşıyor.

#### Hedefler

- VS Code / Cursor eklentisi
- Açık dosya bağlamını SİDAR'a aktarma
- LSP + agent + HITL üçlüsünü editör içine taşıma
- Diff / patch önerilerini inline gösterebilme

#### Ürün etkisi

Bu yetenek, SİDAR'ın yalnızca ayrı bir web uygulaması değil, geliştiricinin günlük IDE akışı içinde çalışan gerçek bir takım arkadaşı olmasını sağlar.

---

## 8. Önceliklendirme ve Fazlama

### Faz A — Elzem v5.0 Çekirdeği (**Tamamlandı / Beta'ya Hazır**)

> Faz A hedefleri tamamlandı. `core/multimodal.py`, `core/voice.py`, `/ws/voice`, `managers/browser_manager.py` ve etkileşimli `main.py` ile algı/etkileşim iskeleti ürünleşmiş; ilgili voice/browser/launcher regresyon testleri de repoda yerini almış durumda.

1. `docs` + mimari karar kaydı ile v5.0 hedeflerinin netleştirilmesi **(tamamlandı)**
2. `core/multimodal.py` başlangıcı (video frame + STT) **(✅ tamamlandı / alpha)**
3. `managers/browser_manager.py` + temel Playwright araçları **(✅ tamamlandı / beta'ya hazır)**
4. `agent/tooling.py` içine browser/LSP tool şemaları **(başlatıldı)**
5. `web_server.py` webhook tabanlı proaktif trigger girişleri **(✅ tamamlandı)**
6. `SwarmFlowPanel.jsx` için graph veri modeli **(✅ tamamlandı)**
7. `main.py` interactive CLI launcher **(✅ tamamlandı)**

### Faz B — Güvenli Otonomi ve GraphRAG Derinleşmesi (**Tamamlandı**)

> Faz B hedefleri repo içinde tamamlandı: GraphRAG reviewer kalite kapısına bağlandı, duplex voice-to-voice akışı derinleştirildi ve görsel Swarm karar grafiği ürünleşti.

1. GraphRAG indeksleyicinin reviewer/etki analizi ile derinleştirilmesi **(✅ tamamlandı)**
2. LSP entegrasyonunun Reviewer ajan kalite kapısına bağlanması **(✅ tamamlandı)**
3. Duplex voice-to-voice akışında state/buffer + interrupt temizliği **(✅ tamamlandı)**
4. Swarm karar akışının node-graph görünürlüğü **(✅ tamamlandı)**

### Faz C — AI Co-Worker Deneyimi

1. **Proaktif self-healing:** İlk bootstrap tamamlandı; `core/ci_remediation.py` + `agent/sidar_agent.py` artık düşük riskli CI kırılmalarında JSON patch planı üretip sandbox doğrulaması sonrası patch'i uyguluyor, başarısızlıkta rollback yapıyor. Faz C'nin sıradaki odağı bunu Reviewer/Coder remediation zincirine daha derin bağlamak.
2. **Tarayıcı ajanının derinleştirilmesi:** Browser signal özetlerini swarm kararları ve reviewer kalite kapısı içinde daha doğrudan karar değişkeni haline getirmek.
3. **Operasyon yüzeyinin ileri müdahalesi:** SwarmFlowPanel üzerindeki canlı node aksiyonlarını remediation, federasyon feedback ve görev durumu yönetimiyle genişletmek.
4. **Voice istemcisinde oynatma ACK / clock senkronizasyonu ve IDE eklentileri:** gerçek zamanlı deneyimi istemci tarafında daha deterministik hale getirmek.

---

## 9. Mimari Karar İlkeleri

v5.0 geliştirmeleri aşağıdaki ilkelere bağlı kalmalıdır:

1. **Geriye uyumlu genişleme:** mevcut `core/vision.py`, `core/rag.py`, `agent/swarm.py` gibi dosyalar kırılmadan evrilmeli.
2. **Fail-closed güvenlik:** browser automation ve proaktif ajanlar varsayılan olarak kısıtlı başlamalı.
3. **Açıklanabilirlik:** her otonom aksiyon audit edilebilir ve UI'da izlenebilir olmalı.
4. **Provider agnosticism:** video/STT/TTS/LSP/browser katmanları tek sağlayıcıya kilitlenmemeli.
5. **Aşamalı ürünleşme:** her yetenek için önce MVP, sonra kurumsal sertleştirme yapılmalı.

---

## 10. Teknik Backlog (Faz C Odağı)

| Öncelik | İş kalemi | Ana dosyalar | Çıktı |
|---|---|---|---|
| P0 | Faz C remediation/self-healing döngüsünün derinleştirilmesi | `agent/roles/reviewer_agent.py`, `agent/roles/coder_agent.py`, `core/rag.py` | Daha kontrollü otomatik düzeltme |
| P0 | Multimodal medya ingestion MVP | `core/multimodal.py`, `core/vision.py` | ✅ Video + ses bağlam üretimi |
| P0 | Browser automation manager | `managers/browser_manager.py`, `agent/tooling.py` | ✅ Dinamik web aksiyonları |
| P1 | Webhook/proaktif ajan omurgası | `web_server.py`, `agent/sidar_agent.py` | ✅ Reaktif → proaktif geçiş |
| P1 | Live operation surface UI | `web_ui_react/src/components/SwarmFlowPanel.jsx`, `core/hitl.py` | ✅ Görsel swarm görünürlüğü + node tabanlı operatör müdahalesi |
| P1 | GraphRAG + reviewer impact gate | `core/rag.py`, `agent/roles/reviewer_agent.py`, `managers/code_manager.py` | ✅ Mimari bağımlılık sorguları + reviewer hedefleri |
| P2 | LSP entegrasyonu | `managers/code_manager.py` | ✅ Güvenli refactor |
| P2 | Voice WebSocket akışı | `core/voice.py`, `web_server.py` | ✅ Gerçek zamanlı duplex konuşma + VAD/buffer olayları |
| P3 | External swarm federation | `agent/core/contracts.py`, `agent/swarm.py` | ✅ `federation.v1` ile kurumsal çoklu ajan federasyonu |
| P3 | IDE eklentileri | yeni `extensions/` veya ayrı repo | Inline co-worker deneyimi |

---

## 11. Sonuç

SİDAR bugün güçlü bir otonom mühendislik platformudur; ancak v5.0 ile hedef yalnızca daha fazla araç eklemek değildir. Asıl hedef, sistemi şu üç nitelikte ileri taşımaktır:

- **Daha çok algılayan** (video, ses, canlı konuşma)
- **Daha çok iş yapan** (browser, LSP, proaktif trigger, dış swarm)
- **Daha çok güven veren** (graph görünürlük, audit, HITL, explainability)

Bu rapordaki öneriler, mevcut dosya yapısını bozmadan SİDAR'ın bir sonraki büyük sıçramasını tanımlar: **gelişmiş AI asistanı → otonom AI takım arkadaşı**.
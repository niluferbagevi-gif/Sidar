# `docker/grafana/dashboards/sidar-llm-overview.json`

- **Kaynak dosya:** `docker/grafana/dashboards/sidar-llm-overview.json`
- **Not dosyası:** `docs/module-notes/docker/grafana/dashboards/sidar-llm-overview.json.md`
- **Kategori:** Grafana dashboard tanımı (LLM maliyet/kullanım)
- **Çalışma tipi:** JSON dashboard schema (Grafana)

## 1) Bu dosya ne işe yarar?

Bu dosya, SIDAR için Grafana üzerinde hazır (provisioned) bir LLM gözlemlenebilirlik paneli tanımlar.

Dashboard başlığı: **`SIDAR LLM Maliyet & Kullanım`**

Ana amaçları:

- LLM maliyetini (USD) zaman serisi olarak izlemek,
- provider bazlı hata oranını takip etmek,
- aktif kullanıcı sayısını görünür kılmak.

## 2) İçerdiği panel ve sorgular

Dashboard üç ana panel içerir:

1. **Günlük Token Maliyeti (USD)**
   - Sorgu: `sum(increase(sidar_llm_cost_total_usd[1d]))`
   - Metriği günlük artış olarak toplar.

2. **Ajan Bazlı Hata Oranı (429 Rate Limit)**
   - Sorgu: `sum by (provider) (increase(sidar_llm_failures_total{provider!=""}[5m])) / clamp_min(sum by (provider) (increase(sidar_llm_calls_total{provider!=""}[5m])), 1)`
   - Provider bazında failure/call oranı üretir.

3. **Aktif Kullanıcı Sayısı (LLM çağrısı yapan)**
   - Sorgu: `count(count by (user_id) (sidar_llm_user_calls_total{user_id!=""}))`
   - En az bir çağrı yapan kullanıcıları sayar.

## 3) Provisioning ve kullanım bağlamı

Bu dosya tek başına çalışmaz; aşağıdaki provisioning zinciri ile Grafana’ya yüklenir:

- `docker/grafana/provisioning/dashboards/dashboards.yml`
- `docker/grafana/provisioning/datasources/prometheus.yml`

Grafana container içinde dashboard yolu:

- `/var/lib/grafana/dashboards`

## 4) Nerede kullanılıyor?

- `docker-compose.yml` içinde Grafana volume mount’u ile container’a taşınır.
- `tests/test_grafana_dashboard_provisioning.py` bu dosyanın varlığını, panel başlıklarını ve kritik PromQL ifadelerini doğrular.
- Prometheus tarafında ölçüm kaynağı `web_server.py` içinde sunulan `/metrics/llm/prometheus` endpoint’idir.

## 5) Önemli metadata alanları

- `uid`: `sidar-llm-overview`
- `refresh`: `30s`
- varsayılan zaman penceresi: `now-7d` → `now`
- `tags`: `sidar`, `llm`, `cost`

## 6) Bağımlılıklar

- Grafana dashboard provisioning sistemi
- Prometheus datasource (uid/type: `prometheus`)
- SIDAR uygulama metrikleri:
  - `sidar_llm_cost_total_usd`
  - `sidar_llm_failures_total`
  - `sidar_llm_calls_total`
  - `sidar_llm_user_calls_total`

## 7) Dikkat edilmesi gerekenler

1. PromQL metrik adları backend’de değişirse paneller boş kalır.
2. Datasource `uid`/`type` eşleşmesi bozulursa sorgular çalışmaz.
3. Dashboard JSON elle düzenlenirken Grafana schema alanlarının (`schemaVersion`, panel id’leri) tutarlılığı korunmalıdır.

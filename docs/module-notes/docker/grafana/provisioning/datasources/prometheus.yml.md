# `docker/grafana/provisioning/datasources/prometheus.yml`

- **Kaynak dosya:** `docker/grafana/provisioning/datasources/prometheus.yml`
- **Not dosyası:** `docs/module-notes/docker/grafana/provisioning/datasources/prometheus.yml.md`
- **Kategori:** Grafana datasource provisioning (Prometheus)
- **Çalışma tipi:** YAML provisioning konfigürasyonu

## 1) Bu dosya ne işe yarar?

Bu dosya, Grafana için varsayılan Prometheus datasource’unu otomatik tanımlar.

Böylece dashboard sorguları kullanıcı müdahalesi olmadan doğrudan çalışabilir.

## 2) Konfigürasyon özeti

- `apiVersion: 1`
- Datasource adı: `Prometheus`
- Tür: `prometheus`
- Erişim tipi: `proxy`
- URL: `http://prometheus:9090`
- `isDefault: true`
- `editable: false`

## 3) Neden önemli?

- Grafana dashboard sorguları Prometheus endpoint’ine bağlanmak için bu datasource’a ihtiyaç duyar.
- `isDefault: true` sayesinde panel tanımlarında datasource seçimi tutarlı hale gelir.
- `editable: false` ile production benzeri ortamlarda manuel drift azaltılır.

## 4) Nerede kullanılıyor?

- `docker-compose.yml` içinde Grafana provisioning mount’u ile container’a taşınır.
- `docker/grafana/dashboards/sidar-llm-overview.json` içindeki panel sorguları bu datasource üzerinden çalışır.
- `tests/test_grafana_dashboard_provisioning.py`, bu dosyada `name: Prometheus` ve `url: http://prometheus:9090` değerlerini doğrular.

## 5) İlişkili bileşenler

- `docker/prometheus/prometheus.yml` (scrape hedefleri)
- `web_server.py` (`/metrics/llm/prometheus` metrik endpoint’i)
- `docker/grafana/provisioning/dashboards/dashboards.yml`

## 6) Bağımlılıklar

- Prometheus servisinin Docker ağında `prometheus` host adıyla erişilebilir olması
- Grafana provisioning dizininin doğru mount edilmesi
- Dashboardlardaki Prometheus sorgularının backend metrik isimleriyle uyumlu olması

## 7) Dikkat edilmesi gerekenler

1. `url` servis adı/port değişirse datasource bağlanamaz.
2. `editable: false` nedeniyle değişiklikler UI’dan değil dosya üzerinden yapılmalıdır.
3. TLS/auth gerektiren ortamlarda ek datasource alanları (basic auth, headers, secureJsonData vb.) gerekebilir.

# `docker/grafana/provisioning/dashboards/dashboards.yml`

- **Kaynak dosya:** `docker/grafana/provisioning/dashboards/dashboards.yml`
- **Not dosyası:** `docs/module-notes/docker/grafana/provisioning/dashboards/dashboards.yml.md`
- **Kategori:** Grafana dashboard provider provisioning
- **Çalışma tipi:** YAML provisioning konfigürasyonu

## 1) Bu dosya ne işe yarar?

Bu dosya, Grafana’nın dosya tabanlı dashboard provider’ını tanımlar. Böylece dashboard JSON dosyaları UI’dan manuel import gerektirmeden otomatik yüklenir.

## 2) Temel konfigürasyon

- `apiVersion: 1`
- Provider adı: `sidar-default`
- `orgId: 1`
- Hedef klasör: `SIDAR`
- `type: file`
- `disableDeletion: false`
- `editable: true`
- Dashboard path: `/var/lib/grafana/dashboards`

## 3) Ne sağlar?

- Container açılışında dashboardların otomatik keşfi
- Git ile versiyonlanan JSON dashboardların merkezi yönetimi
- Ortamlar arası aynı panel setinin tekrarlanabilir kurulumu

## 4) Nerede kullanılıyor?

- `docker-compose.yml` içinde provisioning klasörü Grafana container’a mount edilir:
  - `./docker/grafana/provisioning:/etc/grafana/provisioning:ro`
- Dashboard dosyaları ayrıca şu mount ile okunur:
  - `./docker/grafana/dashboards:/var/lib/grafana/dashboards:ro`
- `tests/test_grafana_dashboard_provisioning.py` bu dosyada dashboard path değerini doğrular.

## 5) İlişkili dosyalar

- `docker/grafana/dashboards/sidar-llm-overview.json`
- `docker/grafana/provisioning/datasources/prometheus.yml`

## 6) Bağımlılıklar

- Grafana provisioning mekanizması
- Container içindeki doğru path eşleşmesi (`/var/lib/grafana/dashboards`)
- Docker volume mount’larının doğru tanımlanması

## 7) Dikkat edilmesi gerekenler

1. `path` yanlış olursa dashboardlar yüklenmez.
2. `disableDeletion: false` olduğundan provider dışına çıkan dashboardların davranışı yönetim politikasına göre gözden geçirilmelidir.
3. `editable: true` UI’dan geçici değişikliklere izin verir; kalıcı değişiklikler için JSON dosyası repo üzerinden güncellenmelidir.

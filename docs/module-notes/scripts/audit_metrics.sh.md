# scripts/audit_metrics.sh

- **Kaynak dosya:** `scripts/audit_metrics.sh`
- **Not dosyası:** `docs/module-notes/scripts/audit_metrics.sh.md`
- **Amaç:** Repodaki belirli uzantılar için (py/js/css/html/md) dosya sayısı ve toplam satır sayısı metriklerini hızlıca üretmek.
- **Durum:** İncelendi, kullanım ve örnek çıktılarla dokümante edildi.

---

## Ne İşe Yarar?

`audit_metrics.sh`, proje kökü veya verilen bir dizin altında aşağıdaki uzantılar için metrik üretir:

- `.py`
- `.js`
- `.css`
- `.html`
- `.md`

Her uzantı için şu değerleri hesaplar:

1. **Dosya sayısı**
2. **Toplam satır sayısı**

Ardından genel toplamı da verir.

> Not: `.git` dizini hariç tutulur.

---

## Parametreler

Script iki opsiyonel parametre alır:

1. `root` (varsayılan: `.`)
   - Taranacak kök dizin.
2. `format` (varsayılan: `markdown`)
   - Çıktı biçimi: `markdown` veya `json`.

---

## Kullanım Örnekleri

### 1) Varsayılan kullanım (Markdown)

```bash
bash scripts/audit_metrics.sh
```

### 2) Belirli dizin + Markdown

```bash
bash scripts/audit_metrics.sh /workspace/sidar_project markdown
```

### 3) JSON çıktı (CI/CD veya script entegrasyonu için)

```bash
bash scripts/audit_metrics.sh . json
```

---

## Sonuç Örneği (Markdown)

```text
# Audit Metrics

| Uzantı | Dosya Sayısı | Satır Sayısı |
|---|---:|---:|
| .py | 132 | 34226 |
| .js | 4 | 1904 |
| .css | 1 | 1684 |
| .html | 1 | 572 |
| .md | 87 | 4094 |
| **Toplam** | **225** | **42480** |
```

## Sonuç Örneği (JSON)

```json
{"root":".","generated_at":1773461202,"metrics":{"py":{"files":132,"lines":34226},"js":{"files":4,"lines":1904},"css":{"files":1,"lines":1684},"html":{"files":1,"lines":572},"md":{"files":87,"lines":4094}},"totals":{"files":225,"lines":42480}}
```

---

## Nerede Kullanılır?

- **Kod tabanı büyüme takibi** (satır ve dosya sayısı trendleri)
- **Rapor üretimi** (Markdown tablo çıktısı)
- **CI/CD entegrasyonu** (JSON çıktıyı diğer script'lere besleme)
- **Teknoloji dağılımının hızlı görünümü** (hangi uzantıda ne kadar içerik var)

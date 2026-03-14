# `data/.gitkeep`

- **Kaynak dosya:** `data/.gitkeep`
- **Not dosyası:** `docs/module-notes/data/gitkeep.md`
- **Kategori:** Depo yapısı koruma (boş dizin izleme)
- **Çalışma tipi:** Placeholder dosya (içeriksiz)

## 1) Bu dosya ne işe yarar?

`data/.gitkeep`, Git’in boş klasörleri izlemediği davranışını aşmak için kullanılan standart bir placeholder dosyadır.

Amaç:

- `data/` klasörünün repoda kalıcı olarak bulunmasını sağlamak,
- ilk kurulumda beklenen dizin yapısını garanti etmek,
- runtime’da oluşturulacak dosyalar için sabit bir kök dizin sunmak.

Dosya içeriği bilinçli olarak boştur; varlığı işlevseldir.

## 2) Neden gerekli?

Projede birçok bileşen `data/` altında dosya üretir veya bu yolu varsayar:

- varsayılan SQLite yolu (`data/sidar.db`),
- oturum/veri dosyaları (`data/sessions/...`),
- RAG dizini (`data/rag`),
- backup/cutover artefaktları (`data/sidar.backup.db`) gibi.

`data/` klasörü repoda yoksa, bazı yerel veya CI benzeri senaryolarda dizin varlığına bağlı akışlar ilk çalıştırmada hata üretebilir.

## 3) Nerede kullanılıyor?

Doğrudan kod tarafından okunup parse edilen bir dosya değildir; dolaylı altyapı bileşenidir.

- `README.md` ve `PROJE_RAPORU.md` içinde `data/` klasörü proje depolama alanı olarak tanımlanır.
- `runbooks/production-cutover-playbook.md` içinde `data/sidar.db` ve `data/sidar.backup.db` yolları operasyonel örneklerde kullanılır.
- `docs/module-notes/INDEX.md` içinde bu varlık için modül notu eşlemesi vardır.

## 4) Kullanım örnekleri

### Örnek A — Yeni clone sonrası dizin varlığını doğrulama

```bash
test -d data && test -f data/.gitkeep && echo "data dizini hazır"
```

### Örnek B — Runtime dosyası üretimi

```bash
sqlite3 data/sidar.db ".databases"
```

Bu örnek, `data/` kökünün mevcut olması sayesinde doğrudan çalışabilir.

## 5) Bağımlılıklar

- Git davranışı (boş dizinler commit edilmez)
- Projenin dosya tabanlı depolama varsayımları (`data/` altında)

Ek runtime bağımlılığı yoktur.

## 6) Dikkat edilmesi gerekenler

1. `.gitkeep` bir standart değildir; ekip sözleşmesidir. Bu repoda dizin takibi için kullanılır.
2. `data/` altında oluşan gerçek runtime dosyaları (DB, oturum, RAG çıktıları) genelde `.gitignore` ile yönetilmelidir.
3. Bu dosyanın silinmesi, dizin boş kaldığında `data/` klasörünün Git’ten düşmesine neden olabilir.

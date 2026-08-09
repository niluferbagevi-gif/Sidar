# Pull request hijyeni ve birleştirme kuyruğu

Sidar'da otomasyon kaynaklı PR'lar insan incelemesinin yerine geçmez. Açık PR sayısı veya
aynı dosyaya dokunan PR sayısı yükseldiğinde toplu ve sırasız merge yapılmaz; haftalık
`Pull request hygiene audit` workflow'u önce salt-okunur envanter üretir.

## Haftalık karar akışı

1. `artifacts/pr-hygiene/report.md` içindeki birebir dosya-seti gruplarını inceleyin.
   Aynı amacı çözen PR'larda testleri geçen, güncel `main` tabanlı en küçük değişikliği tutun;
   diğerlerini ancak maintainer doğrulamasından sonra “superseded by #…” gerekçesiyle kapatın.
2. `install_sidar.sh`, `run_tests.sh`, `uv.lock` ve `web_ui_react/package-lock.json` hotspot
   değişikliklerini aynı batch'e koymayın. Bunları tek tek rebase edin, ilgili tam kalite kapısını
   çalıştırın ve ilk merge sonrasında sıradakini yeniden değerlendirin.
3. Aynı dosyalara dokunmayan küçük PR'ları en fazla 3 PR'lık inceleme batch'lerinde ele alın.
   Batch, tek squash/cherry-pick commit anlamına gelmez; her PR kendi CI ve geri alma sınırını korur.
4. Dependabot major güncellemelerini grup PR'larıyla birleştirmeyin. Lockfile üreten tek PR seçin;
   eski tekil veya grup PR'larını yeniden oluşturma/kapama kararı son lockfile doğrulamasından sonra verin.
5. 30 günden uzun süredir güncellenmeyen PR'ı otomatik kapatmayın. Önce değişikliğin `main` üzerinde
   zaten bulunup bulunmadığını, hâlâ geçerli bir bug'ı çözüp çözmediğini ve CI sonucunu doğrulayın.

## Komutlar

Yerel salt-okunur rapor:

```bash
GITHUB_TOKEN=... uv run python scripts/audit_open_pull_requests.py
```

Rapor GitHub durumunu değiştirmez. PR kapatma, label ekleme, rebase veya merge işlemleri yalnız
yetkili maintainer tarafından rapordaki kanıt incelendikten sonra yapılır.

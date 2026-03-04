# main.py Teknik Notu

`main.py`, Sidar CLI uygulamasının giriş noktasıdır. Kullanıcı etkileşimini, tek-komut modunu ve çalışma zamanı override akışını yönetir.

## 1) Sorumluluklar

- CLI argümanlarını parse etmek (`--status`, `--command`, `--provider`, `--level`, `--model`, `--log`).
- `Config` nesnesini oluşturup gerektiğinde CLI ile override etmek.
- `SidarAgent` örneğini başlatmak.
- Interaktif döngüde kullanıcı girdisini güvenli biçimde ajana aktarmak.

## 2) Çalışma Akışı

1. `config.py` import edilir (merkezi logging ve config altyapısı devrede).
2. `main()` içinde `argparse` ile parametreler alınır.
3. `cfg = Config()` oluşturulur; CLI parametreleri sınıf yerine **instance** üzerinde override edilir.
4. `agent = SidarAgent(cfg)` başlatılır.
5. `--status` veya `--command` modları varsa tek-atış akış çalışır, değilse interaktif döngüye girilir.

## 3) Teknik Özellikler

- **Tek event-loop yaklaşımı:** interaktif mod, her komutta yeni loop açmak yerine tek `asyncio.run(_interactive_loop_async(...))` ile yönetilir.
- **`input()` izolasyonu:** kullanıcı girişi `asyncio.to_thread(input, ...)` ile alınır; event-loop bloklanmaz.
- **Dinamik banner/sürüm gösterimi:** sürüm `agent.VERSION` üzerinden çalışma anında yazdırılır.

## 4) Bağlantılı Dosyalar

- `config.py`: merkezi ayar kaynağı
- `agent/sidar_agent.py`: ana davranış motoru
- Dolaylı olarak `core/*` ve `managers/*` (ajan inşası sırasında)

## 5) Operasyon Notu

CLI ile verilen `--provider`, `--level`, `--model` değerleri yalnızca o process ömründe geçerlidir; kalıcı değişiklik için `.env`/deployment ayarları güncellenmelidir.
# cli.py Teknik Notu

`cli.py`, Sidar’ın terminal tabanlı klasik çalışma giriş noktasıdır (eski `main.py` akışı).

## 1) Sorumluluklar

- `SidarAgent` oluşturup terminal etkileşimini yürütmek.
- Tek komut (`-c/--command`) veya interaktif döngü modunu çalıştırmak.
- `.help`, `.status`, `.clear`, `.audit`, `.health` gibi yerel komutları yönetmek.

## 2) Teknik Özellikler

- Interaktif döngü tek event-loop yaklaşımı ile çalışır.
- `input()` çağrıları `asyncio.to_thread` ile izole edilmiştir.
- CLI flag’leri (`--provider`, `--level`, `--model`, `--log`) ile runtime override yapılabilir.
- `Config` ve `SidarAgent` importları `main()` içinde yapılır; böylece `python cli.py --help` gibi çağrılar bağımlılık hatası olmadan daha dayanıklı çalışır.

## 3) Bağlantılı Dosyalar

- `config.py`
- `agent/sidar_agent.py`

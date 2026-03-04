# agent/auto_handle.py Teknik Notu

`AutoHandle`, kullanıcı mesajlarını LLM turuna girmeden hızlı regex tabanlı kurallarla ilgili araca yönlendiren yardımcı katmandır.

## 1) Görev

- `handle(text)` ile giriş metnini normalize eder.
- Belirli niyetleri (GitHub PR okuma, web arama, URL fetch, docs search, StackOverflow, PyPI/NPM, docs add vb.) hızlıca yakalar.
- Eşleşen senaryoda ilgili manager/tool çağrısını yaparak kısa yanıt döndürür.

## 2) Kazanım

- Gereksiz LLM çağrılarını azaltır.
- Sık kullanılan komutları daha düşük gecikmeyle tamamlar.
- Ağır ReAct döngüsünü yalnızca gerektiğinde devreye sokar.

## 3) Sınırlar

- Regex tabanlı yaklaşım yanlış-pozitif/yanlış-negatif üretebilir.
- Karmaşık niyetlerde yine LLM/ana döngüye fallback gerekir.

## 4) Bağlantılar

- Tüketen: `agent/sidar_agent.py` (`self.auto.handle(...)`)
- Çağrılanlar: `github`, `web`, `pkg`, `docs` yöneticileri

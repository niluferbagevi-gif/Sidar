# agent/sidar_agent.py Teknik Notu

`SidarAgent`, projenin ana orkestrasyon sınıfıdır. LLM ile etkileşim, araç çağrısı, ReAct döngüsü, hafıza, RAG, güvenlik ve alt-yönetici (manager) katmanlarını birleştirir.

## 1) Ana Sorumluluklar

- Kullanıcı girdisini alıp yanıt üretmek (`respond`).
- Doğrudan araç yönlendirme (`_try_direct_tool_route`) ile hızlı tek-adım yanıtları işlemek.
- ReAct döngüsünü yönetmek (`_react_loop`) ve araç çağrısı/sonuç geri-besleme akışını sürdürmek.
- Tüm tool handler fonksiyonlarını tek dispatcher içinde toplamak (`_execute_tool`).
- Her turda runtime bağlamını üretmek (`_build_context`) ve talimat dosyalarını hiyerarşik cache ile yüklemek (`_load_instruction_files`).

## 2) Mimari Öne Çıkanlar

- **Structured output güvenliği:** `ToolCall` Pydantic modeli + `JSONDecoder.raw_decode` fallback ile LLM çıktısı kontrollü parse edilir.
- **Event-loop koruması:** dosya/shell/git gibi ağır I/O yollarının büyük kısmı `asyncio.to_thread(...)` ile taşınır.
- **Tool alias desteği:** `run_shell`/`bash`/`shell`, `grep_files`/`grep`, `subtask`/`agent` gibi alias’larla Claude Code uyumu hedeflenir.
- **Instruction cache:** `SIDAR.md` / `CLAUDE.md` dosyaları `mtime` temelli cache ile gerektiğinde yeniden yüklenir.

## 3) Bağlantılı Dosyalar

- `config.py`: tüm runtime parametreleri
- `agent/definitions.py`: sistem prompt ve anahtar sabitleri
- `agent/auto_handle.py`: regex tabanlı hızlı yönlendirme katmanı
- `core/*`: LLM, memory, RAG
- `managers/*`: security/github/code/web_search/package_info/todo/system_health

## 4) Bilinen İyileştirme Alanı

- `docs_search` yolu doğrudan senkron `docs.search(...)` çağırır; yüksek yükte non-blocking modele taşınması önerilir.

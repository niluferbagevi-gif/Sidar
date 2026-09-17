# `managers/code/lsp.py` — Language Server Protocol Çerçeveleme/URI Yardımcıları

- **Kaynak dosya:** `managers/code/lsp.py`
- **Not dosyası:** `docs/module-notes/managers/code/lsp.py.md`

**Amaç:** LSP mesaj çerçeveleme (`Content-Length` header'lı JSON-RPC framing)
ve dosya yolu ↔ `file://` URI dönüşümlerini barındırır; Windows/POSIX yol
ayrımına dikkat eder (`PosixPath`/`PureWindowsPath`).

**Özellikler:**
- `LSPProtocolError` — eksik/yarım mesaj çerçevesinde fırlatılır.
- `path_to_file_uri(path, *, path_separator=os.sep)`,
  `file_uri_to_path(uri, *, os_name=os.name)` — URI ↔ yol dönüşümü.
- `encode_lsp_message(payload)`, `decode_lsp_stream(raw)` — framing
  encode/decode.
- `lsp_install_hint(language_id)`, `lsp_target_binary(...)`,
  `lsp_stderr_indicates_missing_binary(stderr_text)` — dil sunucusu
  eksikse kullanıcıya kurulum ipucu üretir.
- `extract_lsp_result(...)`, `format_lsp_locations(locations, limit)`,
  `position_params(path, line, character)` — LSP yanıtlarını okunabilir
  metne çevirir.

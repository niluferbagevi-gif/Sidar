# CLAUDE.md

Bu dosya Claude Code uyumluluğu için eklenmiştir.
Sidar ajanı hem `SIDAR.md` hem `CLAUDE.md` dosyalarını okur; her ikisi de her konuşma turunda taze okunur.

## Uyumluluk

- Sidar, Claude Code'un araç sözleşmesini (tool contract) taklit eder:
  - `todo_write` / `todo_read` / `todo_update` → Claude Code'daki `TodoWrite` / `TodoRead` eşdeğeri.
  - `glob_search` → `Glob` eşdeğeri.
  - `grep_files` / `grep` → `Grep` eşdeğeri.
  - `run_shell` / `bash` / `shell` → `Bash` eşdeğeri.
  - `read_file` → `Read` eşdeğeri.
  - `write_file` → `Write` eşdeğeri.
  - `patch_file` → `Edit` eşdeğeri (eski_kod|||yeni_kod formatı).
  - `web_search` / `fetch_url` → `WebSearch` / `WebFetch` eşdeğeri.
  - `github_smart_pr` → Claude Code'daki akıllı PR oluşturma eşdeğeri.

## Hiyerarşi

- `SIDAR.md` → genel proje kuralları (tüm ajanlara uygulanır).
- `CLAUDE.md` → Claude'a özgü notlar (Claude Code uyumluluk ipuçları).
- Alt klasördeki dosyalar, üst klasördeki talimatlardan sonra uygulanır ve öncelik alır.

## Claude Code'dan Farklılıklar

- Sidar yerel bir ajan olduğundan izin onayı UI'da değil, `.env` dosyasındaki `ACCESS_LEVEL` ile belirlenir.
- `FULL` erişim seviyesi → tüm araçlar aktif (Claude Code gibi tam yetki).
- `SANDBOX` erişim seviyesi → yalnızca okuma + `/temp` dizinine yazma.
- Araç sonuçları `[ARAÇ:araç_adı:SONUÇ]` bloğu içinde LLM'e iletilir.

## Öneriler

- Ortak proje kurallarını `SIDAR.md` içinde tutun.
- Claude Code'a özel davranış notları gerekiyorsa bu dosyada belirtin.
- Her iki dosyayı da güncel tutun; Sidar değişiklikleri anında algılar (mtime izleme). 
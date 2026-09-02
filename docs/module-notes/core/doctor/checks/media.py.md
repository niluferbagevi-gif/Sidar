# `core/doctor/checks/media.py` — Medya Araçları Preflight Kontrolü

- **Kaynak dosya:** `core/doctor/checks/media.py`
- **Not dosyası:** `docs/module-notes/core/doctor/checks/media.py.md`

**Amaç:** `core.multimodal`'ın shell-out ettiği harici CLI araçlarının (ffmpeg,
yt-dlp, whisper) kurulum/doctor aşamasında görünür hale getirilmesi. README.md
ffmpeg'i zorunlu sistem bağımlılığı olarak dokümante eder, ancak bu kontrol
eklenmeden önce hiçbir yerde probe edilmiyordu: `install_sidar.sh` ffmpeg'i
kontrol etmiyordu ve `core.multimodal` eksikliği yalnızca çalışma zamanında,
istek ortasında bir `RuntimeError` ile (`extract_video_frames`,
`extract_audio_track`) ortaya çıkarıyordu.

**Davranış:**
- `check_media_tools()` — `shutil.which` ile üç aracı da arar ve tek bir
  `DoctorCheck("media", ...)` sonucu döndürür.
- ffmpeg bulunamazsa: `status="warn"`, çünkü multimodal video/ses ayrıştırma
  çalışma zamanında kesin olarak başarısız olacaktır.
- yt-dlp/whisper eksikse: yine `status="warn"` — bunlar zaten kendi
  yokluklarında zarifçe (graceful) geri düşen opsiyonel uzak-video ve
  konuşma-metne dönüştürme yollarını besler; yalnızca görünürlük için
  raporlanırlar, `fail` durumuna yükseltilmezler.
- Üçü de bulunursa: `status="pass"`.

**Tasarım notu:** `check_gpu()` ile aynı deseni izler — eksik bir opsiyonel
runtime bağımlılığı fatal `fail` değil non-fatal `warn` olarak yüzeye
çıkarılır; böylece taze bir kurulum yine de tamamlanır ve boşluk kullanıcı
ilk video/ses isteğinde sürpriz bir `RuntimeError` ile karşılaşmadan önce
görünür olur.

**İlgili testler:** `tests/unit/core/doctor/test_checks_modules.py`,
`core/doctor/__init__.py` (check kayıt/orkestrasyon noktası).

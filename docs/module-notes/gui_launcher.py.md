# gui_launcher.py

- **Kaynak dosya:** `gui_launcher.py`
- **Not dosyası:** `docs/module-notes/gui_launcher.py.md`

## Özet

`gui_launcher.py`, Eel tabanlı masaüstü başlatıcı için kullanıcı seçimlerini toplayıp bunları `main.py` başlatma hattına normalize eden ince bir adaptör katmanıdır.

## Sorumluluklar

- Web/GUI başlatma seçeneklerini standart argümanlara dönüştürür.
- Varsayılan host/port değerlerini GUI akışına taşır.
- Başlatma sonucunu yapılandırılmış JSON-benzeri sözlük formatında döndürür.
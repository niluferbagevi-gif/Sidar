# docker-compose.local-server.yml

- **Kaynak dosya:** `docker-compose.local-server.yml`
- **Not dosyası:** `docs/module-notes/docker-compose.local-server.yml.md`
- **Amaç:** CPU production web servisini hostun yalnız loopback arayüzünde
  yayınlamak. Overlay, temel/GPU/production dosyalarından sonra uygulanır ve
  Compose `!override` etiketiyle temel dosyadaki tüm-arayüz port binding'ini
  tamamen değiştirir.
- **Kapsam:** Yalnız `sidar-web`; PostgreSQL, Redis ve Ollama production
  overlay'inde host portu yayınlamamaya devam eder.
- **Operasyon:** Aynı makinedeki tarayıcı `http://127.0.0.1:7860` adresini
  kullanır. LAN veya internet erişimi gerekiyorsa bu overlay yerine kontrollü
  VPN/TLS reverse proxy ve firewall politikası uygulanmalıdır.

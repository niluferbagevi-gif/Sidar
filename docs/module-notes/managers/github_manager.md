# managers/github_manager.py Teknik Notu

`GitHubManager`, GitHub API etkileşimlerini (dosya, branch, PR, commit) kapsayan yönetici sınıftır.

## Sorumluluklar
- Repo bağlantısı ve kimlik doğrulama
- Dosya okuma/yazma ve commit işlemleri
- Branch oluşturma ve isim doğrulama
- PR listeleme/okuma/yorumlama/kapatma akışları

## Bağlantılar
- Ayar kaynağı: `config.py` (`GITHUB_TOKEN`, `GITHUB_REPO`)
- Tüketen: `SidarAgent`, `web_server.py`

## Not
- Token/repo eksik senaryolarında kullanıcıya düzeltici yönerge verilmesi, DX açısından kritik.
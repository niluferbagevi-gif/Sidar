"""
Sidar  github_upload.py - Otomatik GitHub Yükleme Aracı
Sürüm: 1.8
Açıklama: Mevcut projeyi kolayca GitHub'a yedekler/yükler. 
Kimlik, çakışma ve otomatik birleştirme (Auto-Merge) kontrolleri içerir.
"""
import os
import subprocess
import sys
from datetime import datetime

# ═══════════════════════════════════════════════════════════════
# RENK KODLARI
# ═══════════════════════════════════════════════════════════════
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

# ═══════════════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ═══════════════════════════════════════════════════════════════
def run_command(command, show_output=True):
    """Terminal komutlarını çalıştırır."""
    try:
        result = subprocess.run(
            command, 
            shell=True, 
            check=True, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True
        )
        if show_output and result.stdout.strip():
            print(f"{result.stdout.strip()}")
        return True, result.stdout.strip()
    except subprocess.CalledProcessError as e:
        # Hata mesajlarını eksiksiz yakala (Hem stdout hem stderr)
        # Not: Git/GitHub ham çıktısı İngilizce olabilir — bu beklenen bir durumdur.
        err_msg = e.stderr.strip()
        if e.stdout and e.stdout.strip():
            err_msg += "\n" + e.stdout.strip()

        if show_output and err_msg:
            print(f"{Colors.WARNING}Git çıktısı: {err_msg}{Colors.ENDC}")
        return False, err_msg

# ═══════════════════════════════════════════════════════════════
# ANA PROGRAM
# ═══════════════════════════════════════════════════════════════
def main():
    print(f"{Colors.HEADER}{'='*65}{Colors.ENDC}")
    print(f"{Colors.BOLD} 🐙 Sidar - GitHub Otomatik Yükleme & Yedekleme Aracı (v1.8) {Colors.ENDC}")
    print(f"{Colors.HEADER}{'='*65}{Colors.ENDC}\n")

    # 1. Git kurulu mu?
    success, _ = run_command("git --version", show_output=False)
    if not success:
        print(f"{Colors.FAIL}Sistemde Git kurulu değil. Lütfen terminalden 'sudo apt install git' yazarak kurun.{Colors.ENDC}")
        sys.exit(1)

    # 1.5 Git Kimlik (Identity) Kontrolü
    success, name_out = run_command("git config user.name", show_output=False)
    if not name_out:
        print(f"{Colors.WARNING}⚠️ Git kimliğiniz tanımlanmamış. Lütfen GitHub bilgilerinizi girin:{Colors.ENDC}")
        git_name = input("Adınız / GitHub Kullanıcı Adınız: ").strip()
        git_email = input("GitHub E-Posta Adresiniz: ").strip()
        run_command(f'git config --global user.name "{git_name}"', show_output=False)
        run_command(f'git config --global user.email "{git_email}"', show_output=False)
        print(f"{Colors.OKGREEN}✅ Git kimliğiniz başarıyla kaydedildi.{Colors.ENDC}\n")

    # 2. Git reposu mu?
    if not os.path.exists(".git"):
        print(f"{Colors.WARNING}Bu klasör henüz bir Git deposu değil. Başlatılıyor...{Colors.ENDC}")
        run_command("git init", show_output=False)
        run_command("git branch -M main", show_output=False)
        print(f"{Colors.OKGREEN}✅ Git deposu oluşturuldu.{Colors.ENDC}")

    # 3. Remote (Uzak Sunucu) kontrolü
    success, remotes = run_command("git remote -v", show_output=False)
    if "origin" not in remotes:
        print(f"{Colors.WARNING}GitHub depo (repository) bağlantısı bulunamadı.{Colors.ENDC}")
        repo_url = input(f"{Colors.OKBLUE}Lütfen GitHub Depo URL'sini girin\n(Örn: https://github.com/niluferbagevi-gif/sidar_project): {Colors.ENDC}").strip()
        
        if not repo_url:
            print(f"{Colors.FAIL}URL girilmedi, işlem iptal edildi.{Colors.ENDC}")
            sys.exit(1)
            
        run_command(f"git remote add origin {repo_url}", show_output=False)
        print(f"{Colors.OKGREEN}✅ GitHub deposu sisteme bağlandı.{Colors.ENDC}")
    else:
        print(f"{Colors.OKGREEN}✅ Mevcut GitHub bağlantısı algılandı.{Colors.ENDC}")

    # 4. Değişiklikleri Ekle (.gitignore kuralları sayesinde .env otomatik atlanır)
    print(f"\n{Colors.OKBLUE}📦 Dosyalar taranıyor ve paketleniyor...{Colors.ENDC}")
    run_command("git add .", show_output=False)

    # 5. Durum Kontrolü (Değişen dosya var mı?)
    _, status = run_command("git status --porcelain", show_output=False)
    if not status:
        print(f"{Colors.WARNING}🤷 Yüklenecek yeni bir değişiklik bulunamadı. Projeniz zaten güncel!{Colors.ENDC}")
        sys.exit(0)

    # 6. Commit (Kaydetme) Mesajı
    default_msg = f"Sistem Güncellemesi: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    print(f"\n{Colors.WARNING}Değişiklikleri kaydetmek için bir not yazın.{Colors.ENDC}")
    commit_msg = input(f"{Colors.OKBLUE}Commit mesajı (Boş bırakırsanız otomatik tarih atılır): {Colors.ENDC}").strip()
    
    if not commit_msg:
        commit_msg = default_msg
    
    print(f"\n{Colors.OKBLUE}💾 Değişiklikler kaydediliyor...{Colors.ENDC}")
    commit_success, commit_err = run_command(f'git commit -m "{commit_msg}"', show_output=False)
    
    if not commit_success:
        print(f"{Colors.FAIL}❌ Dosyalar kaydedilirken hata oluştu: {commit_err}{Colors.ENDC}")
        sys.exit(1)

    # 7. Branch (Dal) belirle
    success, branch = run_command("git branch --show-current", show_output=False)
    current_branch = branch if branch else "main"

    # 8. GitHub'a Gönder (Push)
    print(f"\n{Colors.HEADER}🚀 GitHub'a yükleniyor (Hedef: {current_branch}). Lütfen bekleyin...{Colors.ENDC}")
    
    # Push işlemini dene
    push_success, err_msg = run_command(f"git push -u origin {current_branch}", show_output=False)

    if push_success:
        print(f"\n{Colors.HEADER}{'='*65}{Colors.ENDC}")
        print(f"{Colors.BOLD}{Colors.OKGREEN}🎉 TEBRİKLER! Proje başarıyla GitHub'a yüklendi!{Colors.ENDC}")
        print(f"{Colors.HEADER}{'='*65}{Colors.ENDC}")
    else:
        # Çakışma varsa (fetch first / rejected)
        if "rejected" in err_msg or "fetch first" in err_msg or "non-fast-forward" in err_msg:
            print(f"{Colors.WARNING}⚠️ GitHub'da bilgisayarınızda olmayan dosyalar var. Senkronizasyon başlatılıyor...{Colors.ENDC}")
            
            # Uzak geçmişi yerel ile zorla birleştir (Editör açılmasını engelle ve lokal dosyaları koru)
            print(f"{Colors.OKBLUE}🔄 Uzak sunucu ile dosyalar otomatik birleştiriliyor...{Colors.ENDC}")
            pull_cmd = f"git pull origin {current_branch} --rebase=false --allow-unrelated-histories --no-edit -X ours"
            pull_success, pull_err = run_command(pull_cmd, show_output=False)
            
            if pull_success or "up to date" in pull_err.lower() or "merge made" in pull_err.lower():
                print(f"{Colors.OKGREEN}✅ Senkronizasyon başarılı. Yeniden yükleniyor...{Colors.ENDC}")
                
                # Tekrar Push dene
                retry_success, retry_err = run_command(f"git push -u origin {current_branch}", show_output=False)
                
                if retry_success:
                    print(f"\n{Colors.HEADER}{'='*65}{Colors.ENDC}")
                    print(f"{Colors.BOLD}{Colors.OKGREEN}🎉 TEBRİKLER! Çakışma otomatik çözüldü ve proje başarıyla GitHub'a yüklendi!{Colors.ENDC}")
                    print(f"{Colors.HEADER}{'='*65}{Colors.ENDC}")
                else:
                    # Push tekrar başarısız olursa
                    if "rule violations" in retry_err:
                        print(f"\n{Colors.FAIL}❌ GitHub Güvenlik Duvarı (Push Protection) Devreye Girdi!{Colors.ENDC}")
                        print(f"{Colors.WARNING}İçinde şifre barındıran bir dosya yüklemeye çalışıyorsunuz. Lütfen yukarıdaki hata logunu okuyup şifreli dosyayı gizleyin (.gitignore) veya linke tıklayıp izin verin.{Colors.ENDC}")
                    else:
                        print(f"{Colors.FAIL}❌ Yeniden yükleme başarısız oldu:\n{retry_err}{Colors.ENDC}")
            else:
                print(f"{Colors.FAIL}❌ Birleştirme sırasında hata oluştu. Lütfen komutu terminale manuel yazıp hatayı okuyun:{Colors.ENDC}")
                print(f"{Colors.WARNING}{pull_cmd}{Colors.ENDC}")
                print(f"Hata Çıktısı:\n{pull_err}")
        else:
            print(f"{Colors.FAIL}❌ Yükleme sırasında bilinmeyen bir hata oluştu:\n{err_msg}{Colors.ENDC}")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{Colors.FAIL}İşlem kullanıcı tarafından iptal edildi.{Colors.ENDC}")
        sys.exit(0) 
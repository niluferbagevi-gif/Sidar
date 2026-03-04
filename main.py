"""
Sidar Project - Başlatıcı Arayüz
=================================

Bu modül, kullanıcıya projeyi nasıl başlatmak istediğini soran bir
başlatıcı (starter) arayüzü sağlar. Terminal içinde çalışan basit ve
etkileşimli bir menü üzerinden aşağıdaki seçimler yapılabilir:

1. AI sağlayıcısı: `ollama` veya `gemini`.
2. Erişim seviyesi: `restricted`, `sandbox` veya `full`.
3. Arayüz türü: CLI (terminal), Web (FastAPI) veya Desktop (PyWebView + ayrı frontend).

Seçimler yapıldıktan sonra, uygun alt modu başlatmak için ilgili
Python betiği (`cli.py` veya `web_server.py`) çağrılır ve seçilen
parametreler komut satırı argümanları olarak iletilir.

Not: Bu başlatıcı, gelişmiş bir grafik kütüphanesine (örneğin
Tkinter) ihtiyaç duymadan etkileşimli bir deneyim sağlar. Seçimleri
alırken yanlış girişleri kontrol eder ve kullanıcıyı yönlendirir.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import List


def _clear_screen() -> None:
    """Konsolu temizler (Windows ve POSIX desteği)."""
    command = "cls" if os.name == "nt" else "clear"
    try:
        subprocess.call(command, shell=True)
    except Exception:
        # Konsol temizleme başarısız olursa yoksay
        pass


def _ask_choice(prompt: str, options: List[str]) -> str:
    """
    Kullanıcıya numerik seçimli bir soru sorar ve geçerli bir yanıt alana
    kadar soruyu tekrarlar.

    Args:
        prompt: Ekranda gösterilecek açıklama metni.
        options: Seçenekler listesi (küçük harflerle). Seçim numarası ya da
                 metin eşleşmesi kabul edilir.

    Returns:
        Kullanıcının seçtiği seçenek (liste elemanı).
    """
    while True:
        print(prompt)
        for idx, opt in enumerate(options, 1):
            print(f"  {idx}) {opt}")
        choice = input("Seçiminiz (numara veya isim): ").strip().lower()
        if not choice:
            print("Lütfen bir seçim yapın.\n")
            continue
        # Sayı ise
        if choice.isdigit():
            num = int(choice)
            if 1 <= num <= len(options):
                return options[num - 1]
        # Doğrudan isimle eşleşme
        for opt in options:
            if choice == opt.lower():
                return opt
        print("Geçersiz seçim, lütfen tekrar deneyin.\n")


def _welcome_banner() -> None:
    """Basit bir hoş geldin mesajı yazdırır."""
    print("\n  ╔══════════════════════════════════════════════╗")
    print("  ║             SİDAR Başlatıcı Arayüzü        ║")
    print("  ╚══════════════════════════════════════════════╝\n")
    print("Hoş geldiniz! Lütfen proje başlatma seçeneklerinizi seçin:\n")


def main() -> None:
    _clear_screen()
    _welcome_banner()
    # AI sağlayıcı seçimi
    provider = _ask_choice(
        "Hangi AI sağlayıcısını kullanmak istersiniz?",
        ["ollama", "gemini"],
    )
    # Erişim seviyesi seçimi
    level = _ask_choice(
        "Erişim seviyesini seçin:",
        ["restricted", "sandbox", "full"],
    )
    # Arayüz modu seçimi
    ui = _ask_choice(
        "Arayüz modunu seçin:",
        ["cli", "web", "desktop"],
    )

    # Seçimlere göre komut parametreleri oluştur
    args: List[str] = []
    if provider:
        args.extend(["--provider", provider])
    if level:
        args.extend(["--level", level])

    # Komut yolu (aynı dizinde olduğumuzu varsayar)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    python_exe = sys.executable or "python"

    if ui == "cli":
        target_script = os.path.join(base_dir, "cli.py")
        cmd = [python_exe, target_script] + args
        print("\nTerminal modu başlatılıyor...\n")
        subprocess.run(cmd)
    elif ui == "web":
        target_script = os.path.join(base_dir, "web_server.py")
        # Web arayüzü için varsayılan port ve host config.py'den okunur.
        cmd = [python_exe, target_script] + args
        print("\nWeb arayüzü başlatılıyor...\n")
        subprocess.run(cmd)
    else:
        target_script = os.path.join(base_dir, "desktop_app.py")
        cmd = [python_exe, target_script] + args
        print("\nDesktop modu başlatılıyor (PyWebView + ayrı frontend)...\n")
        subprocess.run(cmd)


if __name__ == "__main__":
    main()
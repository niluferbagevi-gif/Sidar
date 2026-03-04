"""
Sidar Project - Akıllı Başlatıcı

Bu dosya, kullanıcıdan etkileşimli seçimler alarak Sidar'ı CLI veya Web modunda
başlatır. Başlatıcı hem konsol sihirbazı hem de (uygunsa) GUI arayüzü sunar.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Sequence


def _print_header() -> None:
    print("\n" + "═" * 64)
    print("  SİDAR Başlatıcı")
    print("  Hoş geldiniz ✨")
    print("═" * 64)


def _choose(prompt: str, options: Sequence[str], default_index: int = 0) -> str:
    while True:
        print(f"\n{prompt}")
        for i, opt in enumerate(options, start=1):
            mark = " (varsayılan)" if i - 1 == default_index else ""
            print(f"  {i}) {opt}{mark}")

        raw = input("Seçiminiz: ").strip()
        if not raw:
            return options[default_index]
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx]

        print("⚠ Geçersiz seçim, tekrar deneyin.")


def _ask_text(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    return raw or default


def _confirm(prompt: str, default_yes: bool = True) -> bool:
    hint = "[Y/n]" if default_yes else "[y/N]"
    raw = input(f"{prompt} {hint}: ").strip().lower()
    if not raw:
        return default_yes
    return raw in {"y", "yes", "e", "evet"}


def _collect_preflight_messages(cfg, provider: str) -> List[str]:
    messages: List[str] = ["🔎 Ön kontroller yapılıyor..."]

    if sys.version_info < (3, 10):
        messages.append("⚠ Python 3.10+ önerilir.")

    env_path = Path(cfg.BASE_DIR) / ".env"
    if env_path.exists():
        messages.append(f"✅ .env bulundu: {env_path}")
    else:
        messages.append("⚠ .env bulunamadı, varsayılan ayarlarla devam edilecek.")

    if provider == "gemini" and not cfg.GEMINI_API_KEY:
        messages.append("⚠ GEMINI_API_KEY boş görünüyor.")

    if provider == "ollama":
        try:
            import httpx

            base = cfg.OLLAMA_URL.rstrip("/")
            tags_url = base + "/tags" if base.endswith("/api") else base + "/api/tags"
            with httpx.Client(timeout=2) as client:
                code = client.get(tags_url).status_code
            if code == 200:
                messages.append("✅ Ollama erişimi başarılı.")
            else:
                messages.append(f"⚠ Ollama yanıt kodu: {code}")
        except Exception:
            messages.append("⚠ Ollama erişimi doğrulanamadı (servis kapalı olabilir).")

    return messages


def _preflight(cfg, provider: str) -> None:
    for line in _collect_preflight_messages(cfg, provider):
        print(line)


def _build_cli_command(provider: str, access_level: str, model: str | None, log: str) -> List[str]:
    cmd = [sys.executable, "cli.py", "--provider", provider, "--level", access_level, "--log", log]
    if model and provider == "ollama":
        cmd.extend(["--model", model])
    return cmd


def _build_web_command(provider: str, access_level: str, host: str, port: str, log: str) -> List[str]:
    return [
        sys.executable,
        "web_server.py",
        "--provider",
        provider,
        "--level",
        access_level,
        "--host",
        host,
        "--port",
        port,
        "--log",
        log.lower(),
    ]


def run_wizard() -> int:
    from config import Config

    cfg = Config()
    _print_header()

    provider = _choose("AI sağlayıcısı seçin:", ["ollama", "gemini"], 0)
    access_level = _choose("Erişim seviyesini seçin:", ["restricted", "sandbox", "full"], 2)
    mode = _choose("Başlatma modu seçin:", ["cli", "web"], 0)
    log_level = _choose("Log seviyesini seçin:", ["DEBUG", "INFO", "WARNING"], 1)

    ollama_model = None
    if provider == "ollama":
        ollama_model = _ask_text("Ollama modeli", cfg.CODING_MODEL)

    _preflight(cfg, provider)

    if mode == "cli":
        cmd = _build_cli_command(provider, access_level, ollama_model, log_level)
    else:
        host = _ask_text("Web host", cfg.WEB_HOST)
        port = _ask_text("Web port", str(cfg.WEB_PORT))
        cmd = _build_web_command(provider, access_level, host, port, log_level)

    print("\n🚀 Başlatılacak komut:")
    print("   " + " ".join(cmd))

    if not _confirm("Devam edilsin mi?", True):
        print("İşlem iptal edildi.")
        return 0

    return subprocess.call(cmd, cwd=os.path.dirname(__file__) or ".")


def _can_use_gui() -> bool:
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    try:
        import tkinter  # noqa: F401
    except Exception:
        return False
    return True


def run_gui() -> int:
    from config import Config
    import tkinter as tk
    from tkinter import messagebox, ttk

    cfg = Config()
    result = {"code": 0}

    root = tk.Tk()
    root.title("Sidar Başlatıcı")
    root.geometry("660x430")
    root.resizable(False, False)

    provider_var = tk.StringVar(value="ollama")
    level_var = tk.StringVar(value="full")
    mode_var = tk.StringVar(value="cli")
    log_var = tk.StringVar(value="INFO")
    model_var = tk.StringVar(value=cfg.CODING_MODEL)
    host_var = tk.StringVar(value=cfg.WEB_HOST)
    port_var = tk.StringVar(value=str(cfg.WEB_PORT))
    cmd_var = tk.StringVar(value="")

    def build_cmd() -> List[str]:
        provider = provider_var.get()
        if mode_var.get() == "cli":
            model = model_var.get().strip() if provider == "ollama" else None
            return _build_cli_command(provider, level_var.get(), model, log_var.get())
        return _build_web_command(provider, level_var.get(), host_var.get().strip(), port_var.get().strip(), log_var.get())

    def refresh_state(*_args) -> None:
        provider = provider_var.get()
        mode = mode_var.get()
        model_entry.configure(state="normal" if provider == "ollama" else "disabled")
        host_entry.configure(state="normal" if mode == "web" else "disabled")
        port_entry.configure(state="normal" if mode == "web" else "disabled")
        cmd_var.set(" ".join(build_cmd()))

    def run_checks() -> None:
        lines = _collect_preflight_messages(cfg, provider_var.get())
        messagebox.showinfo("Ön Kontrol", "\n".join(lines), parent=root)

    def launch() -> None:
        cmd = build_cmd()
        confirm = messagebox.askyesno("Başlat", "Bu komut çalıştırılsın mı?\n\n" + " ".join(cmd), parent=root)
        if not confirm:
            return
        root.withdraw()
        try:
            result["code"] = subprocess.call(cmd, cwd=os.path.dirname(__file__) or ".")
        finally:
            root.destroy()

    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Sidar Interaktif Başlatıcı", font=("Arial", 14, "bold")).grid(row=0, column=0, columnspan=4, sticky="w")

    ttk.Label(frame, text="Sağlayıcı").grid(row=1, column=0, sticky="w", pady=(12, 4))
    ttk.Combobox(frame, textvariable=provider_var, values=["ollama", "gemini"], state="readonly", width=16).grid(row=1, column=1, sticky="w", pady=(12, 4))

    ttk.Label(frame, text="Erişim").grid(row=1, column=2, sticky="w", pady=(12, 4))
    ttk.Combobox(frame, textvariable=level_var, values=["restricted", "sandbox", "full"], state="readonly", width=16).grid(row=1, column=3, sticky="w", pady=(12, 4))

    ttk.Label(frame, text="Mod").grid(row=2, column=0, sticky="w", pady=4)
    ttk.Combobox(frame, textvariable=mode_var, values=["cli", "web"], state="readonly", width=16).grid(row=2, column=1, sticky="w", pady=4)

    ttk.Label(frame, text="Log").grid(row=2, column=2, sticky="w", pady=4)
    ttk.Combobox(frame, textvariable=log_var, values=["DEBUG", "INFO", "WARNING"], state="readonly", width=16).grid(row=2, column=3, sticky="w", pady=4)

    ttk.Label(frame, text="Ollama model").grid(row=3, column=0, sticky="w", pady=4)
    model_entry = ttk.Entry(frame, textvariable=model_var, width=24)
    model_entry.grid(row=3, column=1, sticky="w", pady=4)

    ttk.Label(frame, text="Web host").grid(row=3, column=2, sticky="w", pady=4)
    host_entry = ttk.Entry(frame, textvariable=host_var, width=24)
    host_entry.grid(row=3, column=3, sticky="w", pady=4)

    ttk.Label(frame, text="Web port").grid(row=4, column=2, sticky="w", pady=4)
    port_entry = ttk.Entry(frame, textvariable=port_var, width=24)
    port_entry.grid(row=4, column=3, sticky="w", pady=4)

    ttk.Label(frame, text="Çalıştırılacak komut").grid(row=5, column=0, columnspan=4, sticky="w", pady=(12, 4))
    cmd_label = ttk.Label(frame, textvariable=cmd_var, foreground="#0d47a1", wraplength=620, justify="left")
    cmd_label.grid(row=6, column=0, columnspan=4, sticky="w")

    btn_row = ttk.Frame(frame)
    btn_row.grid(row=7, column=0, columnspan=4, sticky="w", pady=(18, 0))
    ttk.Button(btn_row, text="Ön Kontrol", command=run_checks).pack(side="left", padx=(0, 8))
    ttk.Button(btn_row, text="Başlat", command=launch).pack(side="left")
    ttk.Button(btn_row, text="Kapat", command=root.destroy).pack(side="left", padx=(8, 0))

    for var in (provider_var, level_var, mode_var, log_var, model_var, host_var, port_var):
        var.trace_add("write", refresh_state)
    refresh_state()

    root.mainloop()
    return result["code"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Sidar akıllı başlatıcı")
    parser.add_argument("--quick", choices=["cli", "web"], help="Sihirbazı atla ve hızlı başlat")
    parser.add_argument("--ui", choices=["auto", "console", "gui"], default="auto", help="Sihirbaz arayüzü (auto/console/gui)")
    parser.add_argument("--provider", choices=["ollama", "gemini"], help="Hızlı başlat için sağlayıcı")
    parser.add_argument("--level", choices=["restricted", "sandbox", "full"], help="Hızlı başlat için erişim")
    parser.add_argument("--model", help="Hızlı CLI başlat için Ollama modeli")
    parser.add_argument("--host", help="Hızlı web başlat için host")
    parser.add_argument("--port", help="Hızlı web başlat için port")
    parser.add_argument("--log", default="INFO", help="Log seviyesi")
    args = parser.parse_args()

    if not args.quick:
        if args.ui == "console":
            raise SystemExit(run_wizard())
        if args.ui == "gui":
            if not _can_use_gui():
                print("⚠ GUI kullanılamadı (display/tkinter yok). Konsol sihirbazı açılıyor.")
                raise SystemExit(run_wizard())
            raise SystemExit(run_gui())

        if _can_use_gui():
            raise SystemExit(run_gui())
        raise SystemExit(run_wizard())

    provider = args.provider or "ollama"
    level = args.level or "full"

    if args.quick == "cli":
        cmd = _build_cli_command(provider, level, args.model, args.log)
    else:
        from config import Config

        cfg = Config()
        cmd = _build_web_command(provider, level, args.host or cfg.WEB_HOST, args.port or str(cfg.WEB_PORT), args.log)

    raise SystemExit(subprocess.call(cmd, cwd=os.path.dirname(__file__) or "."))


if __name__ == "__main__":
    main()

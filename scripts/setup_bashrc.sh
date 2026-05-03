#!/bin/bash
# Sidar projesinin .bashrc alias ve otomasyon bloğunu kullanıcının shell config dosyasına ekler.

SIDAR_DIR="/home/niluf/Sidar"
BASHRC="$HOME/.bashrc"

BLOCK=$(cat <<'EOF'

# ── Sidar AI Projesi ─────────────────────────────────────────────────────────
# Sadece Sidar dizininde terminal açıldığında sanal ortamı aktif et
if [ "$PWD" = "/home/niluf/Sidar" ] && [ -f "/home/niluf/Sidar/.venv/bin/activate" ]; then
    echo "🤖 Sidar proje dizini algılandı. Sanal ortam aktif ediliyor..."
    source /home/niluf/Sidar/.venv/bin/activate
fi

# Sidar testlerini tek komutla çalıştırmak için kısayol
alias stest="source /home/niluf/Sidar/.venv/bin/activate && cd /home/niluf/Sidar && ./run_tests.sh"
# ─────────────────────────────────────────────────────────────────────────────
EOF
)

if grep -q "Sidar AI Projesi" "$BASHRC" 2>/dev/null; then
    echo "✅ Sidar bloğu zaten ~/.bashrc içinde mevcut, değişiklik yapılmadı."
    exit 0
fi

echo "$BLOCK" >> "$BASHRC"
echo "✅ ~/.bashrc dosyasına Sidar bloğu eklendi."
echo "ℹ️  Değişiklikleri aktif etmek için: source ~/.bashrc"

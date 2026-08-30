#!/usr/bin/env bash
# Sidar upstream installer script SHA256 pinleri.
# Bu dosya bilerek repoda tutulur; upstream install.sh değiştiğinde
# değerleri güvenilir bir ortamda yeniden hesaplayıp güncelleyin.

export OLLAMA_INSTALL_SHA256="${OLLAMA_INSTALL_SHA256:-}"
export UV_INSTALL_SHA256="${UV_INSTALL_SHA256:-}"

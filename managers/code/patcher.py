"""Patch application helpers for CodeManager."""

from __future__ import annotations


def apply_exact_block_patch(
    content: str, target_block: str, replacement_block: str
) -> tuple[bool, str]:
    """Replace exactly one occurrence of ``target_block`` in ``content``."""
    count = content.count(target_block)
    if count == 0:
        return False, (
            "⚠ Yama uygulanamadı: 'Hedef kod bloğu' dosyada bulunamadı.\n"
            "Lütfen boşluklara ve girintilere (indentation) dikkat ederek, "
            "dosyada var olan kodu birebir kopyaladığından emin ol."
        )
    if count > 1:
        return False, (
            f"⚠ Yama uygulanamadı: Hedef kod bloğu dosyada {count} kez geçiyor.\n"
            "Hangi bloğun değiştirileceği belirsiz. Lütfen daha fazla bağlam (context) ekle."
        )
    return True, content.replace(target_block, replacement_block)

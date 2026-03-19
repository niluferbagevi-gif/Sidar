from core.multimodal import build_multimodal_context, detect_media_kind


def test_detect_media_kind_uses_mime_or_path_suffix():
    assert detect_media_kind(mime_type="audio/webm") == "audio"
    assert detect_media_kind(path="demo.mp4") == "video"
    assert detect_media_kind(path="frame.png") == "image"
    assert detect_media_kind(mime_type="application/octet-stream") == "unknown"


def test_build_multimodal_context_includes_transcript_frames_and_notes():
    context = build_multimodal_context(
        media_kind="video",
        transcript={"text": "Login ekranında spinner takılıyor.", "language": "tr"},
        frame_analyses=[
            {"timestamp_seconds": 0.0, "analysis": "Ana sayfa yükleniyor."},
            {"timestamp_seconds": 5.0, "summary": "Spinner görünür halde takılı kalıyor."},
        ],
        extra_notes="Kullanıcı Loom kaydı paylaştı.",
    )

    assert "Medya Türü: video" in context
    assert "Login ekranında spinner takılıyor." in context
    assert "- 0.0s: Ana sayfa yükleniyor." in context
    assert "- 5.0s: Spinner görünür halde takılı kalıyor." in context
    assert "Kullanıcı Loom kaydı paylaştı." in context
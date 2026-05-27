from packages.infrastructure import audio_processing


def test_plan_audio_segments_three():
    segs = audio_processing.plan_audio_segments(120.0, 10.0, 3)
    assert len(segs) == 3
    assert segs[0][0] == 0.0
    assert segs[0][1] == 10.0
    assert segs[-1][0] == 110.0


def test_merge_transcript_segments():
    segments = [
        {"text": "你好", "language": "中文", "confidence": 0.8},
        {"text": "世界", "language": "中文", "confidence": 0.6},
    ]
    text, lang, conf = audio_processing.merge_transcript_segments(segments)
    assert "你好" in text
    assert lang == "中文"
    assert conf == 0.7

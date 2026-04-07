from packages.application import analyze_media


def test_sanitize_ai_non_dict():
    cleaned, warnings = analyze_media.sanitize_ai("bad", ["工作", "其他"])
    assert cleaned == {}
    assert "AI output must be an object" in warnings[0]


def test_sanitize_ai_tags_and_text():
    ai = {
        "kind": "截图",
        "category": "未知",
        "title": "abc123测试",
        "tags": "not-a-list",
        "notes": "Hello世界",
    }
    cleaned, warnings = analyze_media.sanitize_ai(ai, ["工作", "其他"])
    assert cleaned["category"] == "其他"
    assert cleaned["title"] == "测试"
    assert cleaned["tags"] == []
    assert cleaned["notes"] == "世界"
    assert warnings

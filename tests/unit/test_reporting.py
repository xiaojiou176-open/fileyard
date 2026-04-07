from pathlib import Path

import pytest

from packages.application.reporting import Summary, cmd_report, generate_report, write_report


def test_summary_counts_basic():
    summary = Summary()
    summary.update(
        {
            "media_type": "image",
            "ai": {"kind": "截图", "category": "工作"},
            "status": "applied",
            "error": "",
            "error_code": "",
        }
    )
    summary.update(
        {
            "media_type": "audio",
            "ai": {"kind": "音频", "category": "其他"},
            "status": "error",
            "error": "boom",
            "error_code": "AI_FAIL",
        }
    )
    summary.update({"media_type": "", "ai": "", "status": "", "error": ""})

    data = summary.to_dict()
    assert data["total"] == 3
    assert data["with_error"] == 1
    assert data["by_media_type"]["image"] == 1
    assert data["by_media_type"]["audio"] == 1
    assert data["by_media_type"]["unknown"] == 1
    assert data["by_kind"]["截图"] == 1
    assert data["by_category"]["工作"] == 1
    assert data["by_status"]["applied"] == 1
    assert data["error_codes"]["AI_FAIL"] == 1


def test_write_report_atomic(tmp_path):
    summary = Summary()
    summary.update({"media_type": "image", "ai": {"kind": "截图", "category": "工作"}})
    out = tmp_path / "report.json"
    write_report(out, summary)

    assert out.exists()
    assert not Path(str(out) + ".partial").exists()


def test_write_report_cleanup_on_error(monkeypatch, tmp_path: Path):
    summary = Summary()
    summary.update({"media_type": "image", "ai": {"kind": "截图", "category": "工作"}})
    out = tmp_path / "report.json"

    original_replace = Path.replace

    def _bad_replace(self, target):
        raise RuntimeError("replace")

    monkeypatch.setattr(Path, "replace", _bad_replace)
    with pytest.raises(RuntimeError):
        write_report(out, summary)
    assert not Path(str(out) + ".partial").exists()

    monkeypatch.setattr(Path, "replace", original_replace)


def test_generate_report_validate(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        '{"path":"/tmp/a.png","media_type":"image","ai":{"kind":"截图","category":"工作"},"error":""}\n',
        encoding="utf-8",
    )
    out = tmp_path / "report.json"
    summary = generate_report(manifest, out, validate=True)
    assert summary.total == 1
    assert out.exists()


def test_cmd_report_success(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        '{"media_type":"image","ai":{"kind":"截图","category":"工作"},"error":""}\n',
        encoding="utf-8",
    )
    out = tmp_path / "report.json"
    args = type(
        "Args",
        (),
        {
            "manifest": str(manifest),
            "out": str(out),
            "validate": False,
            "log_level": "INFO",
            "log_json": False,
        },
    )
    cmd_report(args)
    assert out.exists()


def test_cmd_report_missing_manifest(tmp_path: Path):
    out = tmp_path / "report.json"
    args = type(
        "Args",
        (),
        {
            "manifest": str(tmp_path / "missing.jsonl"),
            "out": str(out),
            "validate": False,
            "log_level": "INFO",
            "log_json": False,
        },
    )
    with pytest.raises(SystemExit, match="Failed to read manifest"):
        cmd_report(args)

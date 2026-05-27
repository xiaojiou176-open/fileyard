from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_english_canonical_surface_script_passes_for_current_repo() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "tooling/scripts/check_english_canonical_surface.py",
            "--root",
            str(repo_root),
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "english-canonical-surface: passed" in result.stdout


def test_deep_water_english_boundary_is_explicit() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    normalization = (repo_root / "packages" / "domain" / "normalization.py").read_text(encoding="utf-8")
    core_utils = (repo_root / "packages" / "domain" / "core_utils.py").read_text(encoding="utf-8")
    media_scanner = (repo_root / "packages" / "infrastructure" / "media_scanner.py").read_text(encoding="utf-8")
    logging_doc = (repo_root / "docs" / "logging_observability.md").read_text(encoding="utf-8")
    report_page = (repo_root / "apps" / "webui" / "src" / "pages" / "report-page.tsx").read_text(encoding="utf-8")
    dashboard_page = (repo_root / "apps" / "webui" / "src" / "pages" / "dashboard-page.tsx").read_text(encoding="utf-8")
    i18n_file = (repo_root / "apps" / "webui" / "src" / "lib" / "i18n.ts").read_text(encoding="utf-8")

    assert 'DEFAULT_LOCALIZED_SLUG_FALLBACK = "未命名"' in normalization
    assert "Product-localized fallback for generated filenames." in normalization

    assert "Another Fileorganize task is already running; lock file exists:" in core_utils
    assert "任务已在运行，锁文件存在" not in core_utils

    assert "Directory traversal failed and was skipped:" in media_scanner
    assert "Failed to read file size; treating it as 0 bytes:" in media_scanner
    assert "遍历目录失败，已跳过" not in media_scanner
    assert "读取文件大小失败，已按0字节处理" not in media_scanner

    assert "# Logging And Observability Policy (No Logs No Merge)" in logging_doc
    assert "Structured logs must remain diagnosable, correlated, and safe to publish." in logging_doc
    assert "日志与可观测性规范" not in logging_doc

    assert "t('report.insights.title')" in report_page
    assert "t('report.insights.retry')" in report_page
    assert "t('report.filters.placeholder')" in report_page
    assert "t('report.filters.empty')" in report_page
    assert "Report 洞察" not in report_page
    assert "重试加载" not in report_page

    assert "t('dashboard.hero.title')" in dashboard_page
    assert "const nextStepMeta = {" in dashboard_page
    assert "t('dashboard.command.next.setupCta')" in dashboard_page
    assert "t('dashboard.command.next.analyzeCta')" in dashboard_page
    assert "t('dashboard.command.next.reviewCta')" in dashboard_page
    assert "t('dashboard.command.next.applyCta')" in dashboard_page
    assert "t('dashboard.command.next.reportCta')" in dashboard_page
    assert "t('dashboard.recentJobs.title')" in dashboard_page
    assert (
        "Use this page like a command center: confirm readiness, take the next step, and keep the current batch in the right stage."
        in i18n_file
    )
    assert "Open Setup" in i18n_file
    assert "Go to Analyze" in i18n_file
    assert "Open Review" in i18n_file
    assert "Open Apply" in i18n_file
    assert "Open Report" in i18n_file
    assert "Recent Jobs" in i18n_file
    assert "Quick Actions" in i18n_file
    assert "Report Insights" in i18n_file
    assert "Retry loading" in i18n_file
    assert "Filter report rows" in i18n_file
    assert "No rows match the current filters." in i18n_file
    assert "先 Analyze，再 Apply" not in dashboard_page
    assert "快速入口" not in dashboard_page

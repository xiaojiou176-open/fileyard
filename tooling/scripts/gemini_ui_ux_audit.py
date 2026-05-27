#!/usr/bin/env python3
"""Gemini-powered UI/UX semantic audit gate for frontend changes."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

FRONTEND_EXTENSIONS = {
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".html",
    ".vue",
    ".svelte",
    ".astro",
}

ALLOWED_ISSUE_CATEGORIES = {
    "a11y",
    "design-system",
    "responsive",
    "dark-mode",
    "performance-perception",
    "maintainability",
    "ux",
}

ALLOWED_SEVERITIES = {"error", "warning"}
DEFAULT_HTTP_TIMEOUT_MS = 90_000


class AuditIssue(BaseModel):
    file: str
    line: int = Field(ge=1)
    severity: str
    category: str
    rule_id: str
    evidence_snippet: str
    confidence: float = Field(ge=0.0, le=1.0)
    description: str = ""
    fix: str = ""


class AuditResult(BaseModel):
    passed: bool = True
    summary: str = "no summary"
    issues: list[AuditIssue] = Field(default_factory=list)


def _build_genai_client(api_key: str, timeout_ms: int = DEFAULT_HTTP_TIMEOUT_MS):
    try:
        from google import genai
        from google.genai import types
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("google-genai 未安装，无法执行 Gemini UI/UX 审计") from exc
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_ms)), types


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run_git(repo_root: Path, *args: str) -> str:
    cmd = ["git", *args]
    return subprocess.check_output(cmd, cwd=repo_root, text=True).strip()


def _read_dotenv_value(dotenv_path: Path, key: str) -> str:
    if not dotenv_path.exists():
        return ""
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() != key:
            continue
        value = v.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value.strip()
    return ""


def _resolve_api_key(repo_root: Path) -> str:
    env_key = os.getenv("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key
    workspace_root = Path(os.getenv("FILEMAN_WORKSPACE_ROOT", "~/.fileman/workspaces/default")).expanduser()
    return _read_dotenv_value(workspace_root / ".fileman" / "env" / "runtime.env", "GEMINI_API_KEY")


def _candidate_files(repo_root: Path, filenames: list[str], max_files: int) -> list[Path]:
    raw_files: list[str]
    if filenames:
        raw_files = filenames
    else:
        raw = _run_git(repo_root, "diff", "--cached", "--name-only")
        raw_files = [line for line in raw.splitlines() if line.strip()]

    result: list[Path] = []
    seen: set[Path] = set()
    for raw_file in raw_files:
        rel = Path(raw_file)
        if rel.suffix.lower() not in FRONTEND_EXTENSIONS:
            continue
        abs_path = repo_root / rel
        if abs_path.exists() and abs_path.is_file():
            if abs_path in seen:
                continue
            seen.add(abs_path)
            result.append(abs_path)
        if max_files > 0 and len(result) >= max_files:
            break
    return result


def _iter_file_batches(file_paths: list[Path], batch_size: int) -> list[list[Path]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")
    return [file_paths[index : index + batch_size] for index in range(0, len(file_paths), batch_size)]


def _staged_diff(repo_root: Path, file_paths: list[Path]) -> str:
    rel_paths = [str(path.relative_to(repo_root)) for path in file_paths]
    cmd = ["git", "diff", "--cached", "--unified=1", "--", *rel_paths]
    return subprocess.check_output(cmd, cwd=repo_root, text=True)


def _full_snapshot(repo_root: Path, file_paths: list[Path]) -> str:
    chunks: list[str] = []
    for path in file_paths:
        rel = str(path.relative_to(repo_root))
        content = path.read_text(encoding="utf-8", errors="ignore")
        chunks.append(f"### FILE: {rel}\n{content}\n")
    return "\n".join(chunks)


def _try_parse_json(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if not text:
        return {"passed": True, "issues": [], "summary": "empty response"}
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    return json.loads(text)


def _validate_schema(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("response must be object")
    issues = payload.get("issues", [])
    if issues is None:
        issues = []
    if not isinstance(issues, list):
        raise ValueError("issues must be list")
    normalized: list[dict[str, Any]] = []
    for item in issues:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity", "warning")).strip().lower()
        if severity not in ALLOWED_SEVERITIES:
            raise ValueError(f"invalid severity: {severity}")
        category = str(item.get("category", "")).strip().lower()
        if category not in ALLOWED_ISSUE_CATEGORIES:
            raise ValueError(f"invalid category: {category}")
        file_path = str(item.get("file", "")).strip()
        if not file_path:
            raise ValueError("file must be non-empty")
        line_raw = item.get("line")
        if isinstance(line_raw, bool):
            raise ValueError("line must be integer >= 1")
        if line_raw is None:
            raise ValueError("line must be integer >= 1")
        try:
            line = int(line_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("line must be integer >= 1") from exc
        if line < 1:
            raise ValueError("line must be integer >= 1")
        rule_id = str(item.get("rule_id", "")).strip()
        if not rule_id:
            raise ValueError("rule_id must be non-empty")
        evidence_snippet = str(item.get("evidence_snippet", "")).strip()
        if not evidence_snippet:
            raise ValueError("evidence_snippet must be non-empty")
        confidence_raw = item.get("confidence")
        if confidence_raw is None or isinstance(confidence_raw, bool):
            raise ValueError("confidence must be number in [0, 1]")
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("confidence must be number in [0, 1]") from exc
        if not (0.0 <= confidence <= 1.0):
            raise ValueError("confidence must be number in [0, 1]")
        normalized.append(
            {
                "file": file_path,
                "line": line,
                "severity": severity,
                "category": category,
                "rule_id": rule_id,
                "evidence_snippet": evidence_snippet,
                "confidence": confidence,
                "description": str(item.get("description", "")),
                "fix": str(item.get("fix", "")),
            }
        )
    return {
        "passed": bool(payload.get("passed", True)),
        "summary": str(payload.get("summary", "")).strip() or "no summary",
        "issues": normalized,
    }


def _normalize_structured_result(parsed: AuditResult | dict[str, Any]) -> dict[str, Any]:
    if isinstance(parsed, AuditResult):
        payload = parsed.model_dump()
    else:
        payload = parsed
    return _validate_schema(payload)


def _build_prompt(model: str, diff_text: str, changed_files: list[str]) -> str:
    files_text = "\n".join(f"- {path}" for path in changed_files)
    return (
        "你是前端 UI/UX 代码审计专家。请只基于以下 staged diff 做审计。\n"
        f"模型要求: {model}\n"
        "目标: 发现会影响可访问性、设计一致性、响应式和可维护性的真实问题。\n\n"
        "审计规则:\n"
        "1. WCAG 2.2 AA: alt/aria/键盘可达/语义标签/颜色对比度风险，重点核查 2.4.11(焦点不被遮挡) 与 2.5.8(最小触控目标24x24 CSS px)。\n"
        "2. 焦点可见性: 禁止仅移除 outline 而没有替代焦点指示（ring/border/shadow）。\n"
        "3. 触控目标: 除 WCAG 最小 24x24 外，移动端优先 44x44（Apple HIG）与 48x48dp（Material）建议。\n"
        "4. 动效可达性: 动画/过渡应兼容 prefers-reduced-motion，避免强制动效。\n"
        "5. 设计系统: 避免硬编码颜色/间距/字体，优先 token/theme；优先复用组件库语义（如 Ant/Tailwind 约定）。\n"
        "6. 交互可用性: 表单可读性、按钮语义、错误提示清晰度。\n"
        "7. 响应式: 小屏断点布局稳定性、触控目标尺寸与溢出风险。\n"
        "8. 暗黑模式: 避免浅色硬编码导致深色主题不可读，检查 token/theme 可切换性。\n"
        "9. 性能感知: 首屏骨架/加载反馈、布局抖动(CLS)风险、阻塞式大资源提示。\n"
        "10. 可维护性: 重复样式、过度复杂类名、难以复用的结构。\n"
        "11. 只报告高价值问题，避免泛化建议。\n\n"
        "输出要求:\n"
        "只输出 JSON，不要 markdown，不要解释文本。\n"
        "line 必须是 >=1 的整数；confidence 必须在 0~1 之间。\n"
        "{\n"
        '  "passed": true|false,\n'
        '  "summary": "一句话总结",\n'
        '  "issues": [\n'
        "    {\n"
        '      "file": "path",\n'
        '      "line": 123,\n'
        '      "severity": "error|warning",\n'
        '      "category": "a11y|design-system|responsive|dark-mode|performance-perception|maintainability|ux",\n'
        '      "rule_id": "wcag-2.4.11|wcag-2.5.8|design-token-hardcode|...",\n'
        '      "evidence_snippet": "来自diff的证据片段（简短精确）",\n'
        '      "confidence": 0.0,\n'
        '      "description": "问题描述",\n'
        '      "fix": "可执行修复建议"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "changed_files:\n"
        f"{files_text}\n\n"
        "staged_diff:\n"
        f"{diff_text}"
    )


def _print_issues(data: dict[str, Any]) -> None:
    summary = str(data.get("summary", "")).strip() or "no summary"
    issues = data.get("issues", [])
    print(f"Gemini UI/UX summary: {summary}")
    if not isinstance(issues, list) or not issues:
        print("Gemini UI/UX issues: none")
        return
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        file_path = issue.get("file", "unknown")
        line = issue.get("line", "?")
        severity = issue.get("severity", "warning")
        category = issue.get("category", "ux")
        rule_id = issue.get("rule_id", "unknown-rule")
        evidence_snippet = issue.get("evidence_snippet", "")
        confidence = issue.get("confidence", 0.0)
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 0.0
        desc = issue.get("description", "")
        fix = issue.get("fix", "")
        print(f"[{severity}] {category} {file_path}:{line} ({rule_id}, confidence={confidence_value:.2f}) {desc}")
        if evidence_snippet:
            print(f"  evidence: {evidence_snippet}")
        if fix:
            print(f"  fix: {fix}")


def _aggregate_batch_results(batch_results: list[dict[str, Any]]) -> dict[str, Any]:
    merged_issues: list[dict[str, Any]] = []
    summaries: list[str] = []

    for batch in batch_results:
        summary = str(batch.get("summary", "")).strip()
        if summary:
            summaries.append(summary)
        issues = batch.get("issues", [])
        if isinstance(issues, list):
            for issue in issues:
                if isinstance(issue, dict):
                    merged_issues.append(issue)

    has_error = any(issue.get("severity") == "error" for issue in merged_issues if isinstance(issue, dict))

    summary_text = "; ".join(summaries[:5]) if summaries else "no summary"
    if len(summaries) > 5:
        summary_text += f" ... (+{len(summaries) - 5} batches)"

    return {
        "passed": not has_error,
        "summary": summary_text,
        "issues": merged_issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Gemini UI/UX staged audit gate.")
    parser.add_argument(
        "--model",
        default="gemini-3-flash-preview",
        help="Gemini model name (default: gemini-3-flash-preview)",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Max number of frontend files to audit in one run. 0 means no limit.",
    )
    parser.add_argument("--batch-size", type=int, default=20, help="Frontend files per Gemini request batch.")
    parser.add_argument("--max-attempts", type=int, default=2, help="Gemini request/parse retry attempts")
    parser.add_argument(
        "--http-timeout-ms",
        type=int,
        default=int(os.getenv("GEMINI_UI_AUDIT_TIMEOUT_MS", DEFAULT_HTTP_TIMEOUT_MS)),
        help="HTTP timeout for each Gemini request in milliseconds.",
    )
    parser.add_argument("filenames", nargs="*", help="Optional file list from pre-commit.")
    args = parser.parse_args()

    repo_root = _repo_root()
    files = _candidate_files(repo_root, args.filenames, args.max_files)
    if not files:
        print("gemini_ui_ux_audit: no frontend files in scope, skip")
        return 0

    api_key = _resolve_api_key(repo_root)
    if not api_key:
        print("❌ gemini_ui_ux_audit: GEMINI_API_KEY missing (workspace runtime env file or env var required)", file=sys.stderr)
        return 1

    try:
        client, types_module = _build_genai_client(api_key, timeout_ms=args.http_timeout_ms)
    except RuntimeError as exc:
        print(f"❌ gemini_ui_ux_audit: {exc}", file=sys.stderr)
        return 1

    try:
        batches = _iter_file_batches(files, args.batch_size)
    except ValueError as exc:
        print(f"❌ gemini_ui_ux_audit: {exc}", file=sys.stderr)
        return 1

    parsed_batches: list[dict[str, Any]] = []
    for batch_index, batch_files in enumerate(batches, start=1):
        try:
            diff_text = _staged_diff(repo_root, batch_files)
        except subprocess.CalledProcessError:
            diff_text = ""
        if not diff_text.strip():
            diff_text = _full_snapshot(repo_root, batch_files)
            if not diff_text.strip():
                print(f"gemini_ui_ux_audit: empty source payload for batch {batch_index}, skip")
                continue

        changed_files = [str(path.relative_to(repo_root)) for path in batch_files]
        prompt = _build_prompt(args.model, diff_text, changed_files)

        parsed: dict[str, Any] | None = None
        last_error: Exception | None = None
        raw = ""
        for _ in range(max(1, args.max_attempts)):
            try:
                response = client.models.generate_content(
                    model=args.model,
                    contents=prompt,
                    config=types_module.GenerateContentConfig(
                        temperature=0.0,
                        response_mime_type="application/json",
                        response_schema=AuditResult,
                    ),
                )
                structured = getattr(response, "parsed", None)
                if isinstance(structured, (AuditResult, dict)):
                    parsed = _normalize_structured_result(structured)
                    raw = response.text or ""
                else:
                    raw = response.text or ""
                    parsed = _validate_schema(_try_parse_json(raw))
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue

        if parsed is None:
            print(f"❌ gemini_ui_ux_audit: batch {batch_index}/{len(batches)} failed after retries", file=sys.stderr)
            if last_error is not None:
                print(f"error={last_error}", file=sys.stderr)
            if raw:
                print("raw_response_start", file=sys.stderr)
                print(raw[:1200], file=sys.stderr)
                print("raw_response_end", file=sys.stderr)
            return 1

        parsed_batches.append(parsed)

    if not parsed_batches:
        print("gemini_ui_ux_audit: empty audit result after batch processing, skip")
        return 0

    merged_result = _aggregate_batch_results(parsed_batches)
    _print_issues(merged_result)
    issues = merged_result.get("issues", [])
    if not isinstance(issues, list):
        issues = []
    has_error = any(isinstance(item, dict) and item.get("severity") == "error" for item in issues)
    passed_flag = bool(merged_result.get("passed", not has_error))
    if has_error or not passed_flag:
        print("❌ gemini_ui_ux_audit: blocked by Gemini UI/UX findings", file=sys.stderr)
        return 1

    print("✅ gemini_ui_ux_audit: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from tooling.scripts import run_ai_eval


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _poison_run_bundle_root(base: Path, run_id: str) -> Path:
    summary_path = base / run_id / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("", encoding="utf-8")
    return base


def _write_live_only_spec(tmp_path: Path) -> tuple[Path, Path]:
    spec = tmp_path / "eval_cases.yaml"
    baseline = tmp_path / "eval_baseline.yaml"
    spec.write_text(
        textwrap.dedent(
            """
            version: 1
            suites:
              - id: live-rubric
                mode: live
                input_dir: tests/fixtures/golden_input
                cases:
                  - id: live-doc-kind
                    row: doc.pdf
                    kind: equals
                    field: ai.kind
                    expected: 文档
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    baseline.write_text(
        textwrap.dedent(
            """
            version: 1
            review_confidence_threshold: 0.6
            human_rubric_template: contracts/ai/human_rubric.example.json
            suites:
              live-rubric:
                min_pass_rate: 0.9
                allow_skip_without_credentials: true
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return spec, baseline


def _write_runner_smoke_spec(tmp_path: Path) -> tuple[Path, Path]:
    spec = tmp_path / "runner_eval_cases.yaml"
    baseline = tmp_path / "runner_eval_baseline.yaml"
    spec.write_text(
        textwrap.dedent(
            """
            version: 1
            suites:
              - id: offline-audio-contract
                mode: offline
                synthetic_audio:
                  filename: 语音样例.wav
                  duration_seconds: 0.25
                  frequency_hz: 440.0
                cases:
                  - id: offline-audio-media-type
                    row: 语音样例.wav
                    kind: equals
                    field: media_type
                    expected: audio
                  - id: offline-audio-status
                    row: 语音样例.wav
                    kind: equals
                    field: status
                    expected: pending
              - id: live-rubric
                mode: live
                input_dir: tests/fixtures/golden_input
                cases:
                  - id: live-doc-kind
                    row: doc.pdf
                    kind: equals
                    field: ai.kind
                    expected: 文档
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    baseline.write_text(
        textwrap.dedent(
            """
            version: 1
            review_confidence_threshold: 0.6
            human_rubric_template: contracts/ai/human_rubric.example.json
            suites:
              offline-audio-contract:
                min_pass_rate: 1.0
                allow_skip: false
              live-rubric:
                min_pass_rate: 0.9
                allow_skip_without_credentials: true
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return spec, baseline


def test_ai_eval_runner_passes_offline_mode(tmp_path: Path) -> None:
    repo_root = _repo_root()
    output = tmp_path / "summary.json"
    spec, baseline = _write_runner_smoke_spec(tmp_path)
    env = os.environ.copy()
    env["FILEORGANIZE_ALLOW_HOST_EXECUTION"] = "1"

    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tooling" / "scripts" / "run_ai_eval.py"),
            "--root",
            str(repo_root),
            "--spec",
            str(spec),
            "--baseline",
            str(baseline),
            "--mode",
            "offline",
            "--output",
            str(output),
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["overall_status"] == "passed"
    assert payload["runtime"]["review_confidence_threshold"] == 0.6
    assert "durable_artifacts_root" in payload
    assert payload["review_gate"]["manual_review_required_rows"] >= 0
    assert payload["evidence_tiers"]["canonical_pack_tier"] == "smoke"
    assert payload["evidence_tiers"]["attained_tier_this_run"] == "smoke"
    assert payload["live_receipt"]["status"] == "skipped"
    assert payload["live_receipt"]["gate"] == "run_mode_offline"
    assert payload["live_receipt"]["claim_cap"] == "smoke"
    assert payload["human_rubric"]["template"] == "contracts/ai/human_rubric.example.json"
    assert payload["human_rubric"]["gate"] == "missing"
    assert payload["human_rubric"]["claim_cap"] == "interview"
    assert payload["upgrade_pack"]["pack_id"] == "ai-eval-upgrade-pack"
    assert payload["upgrade_pack"]["current_claim_tier_cap"] == "smoke"
    assert payload["upgrade_pack"]["recorded_input_status_required"] == "recorded"
    assert payload["upgrade_pack"]["recorded_input_unlocks_tier"] == "public"
    assert payload["upgrade_pack"]["prerequisite_before_recorded_input_unlocks"] == ["live_receipt.status == passed"]
    assert payload["privacy_truth"]["credential_values_stored"] is False
    assert payload["privacy_truth"]["gemini_called_in_this_run"] is False
    assert payload["proof_boundaries"]["does_not_prove"]
    assert payload["claim_readiness"]["status"] == "smoke_only"
    assert payload["claim_readiness"]["max_safe_claim_tier"] == "smoke"
    assert payload["claim_readiness"]["blocked_tiers"] == ["interview", "public"]
    assert payload["claim_readiness"]["fail_close"] is True
    assert {suite["id"] for suite in payload["suites"]} == {"offline-audio-contract", "live-rubric"}
    live_suite = next(suite for suite in payload["suites"] if suite["id"] == "live-rubric")
    assert live_suite["status"] == "skipped"
    assert "duration_ms" in live_suite
    assert live_suite["metrics"]["review_confidence_threshold"] == 0.6
    assert payload["human_rubric"]["template"] == "contracts/ai/human_rubric.example.json"
    offline_suite = next(suite for suite in payload["suites"] if suite["id"] == "offline-audio-contract")
    assert "/tmp/" not in json.dumps(offline_suite["artifacts"], ensure_ascii=False)


def test_ai_eval_runner_skips_live_suite_without_credentials(tmp_path: Path) -> None:
    repo_root = _repo_root()
    output = tmp_path / "summary.json"
    spec, baseline = _write_live_only_spec(tmp_path)
    env = os.environ.copy()
    env["FILEORGANIZE_ALLOW_HOST_EXECUTION"] = "1"
    env.pop("GEMINI_API_KEY", None)
    env.pop("GEMINI_MODEL", None)

    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tooling" / "scripts" / "run_ai_eval.py"),
            "--root",
            str(repo_root),
            "--spec",
            str(spec),
            "--baseline",
            str(baseline),
            "--mode",
            "auto",
            "--output",
            str(output),
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    live_suite = next(suite for suite in payload["suites"] if suite["id"] == "live-rubric")
    assert live_suite["status"] == "skipped"
    assert live_suite["reason"] == "missing credentials"
    assert payload["runtime"]["credentials_present"] is False
    assert payload["live_receipt"]["status"] == "skipped"
    assert payload["live_receipt"]["gate"] == "credentials_missing"
    assert payload["live_receipt"]["claim_cap"] == "smoke"
    assert "没有凭证" in payload["live_receipt"]["honest_statement"]


def test_run_ai_eval_analyze_uses_isolated_run_bundle_root(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd, cwd, text, capture_output, check, env):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(run_ai_eval.subprocess, "run", fake_run)

    manifest_path = run_ai_eval._run_analyze(
        _repo_root(),
        tmp_path / "input",
        offline=True,
        run_id="ai_eval_offline-audio-contract",
        run_bundle_root=tmp_path / ".fileorganize" / "runs",
    )

    env = captured["env"]
    assert isinstance(env, dict)
    assert env["FILEORGANIZE_RUN_BUNDLE_ROOT"] == str((tmp_path / ".fileorganize" / "runs").resolve())
    assert manifest_path.name == "manifest.jsonl"


def test_ai_eval_runner_recreates_nested_output_parent(tmp_path: Path) -> None:
    repo_root = _repo_root()
    output = tmp_path / "nested" / "ai-eval" / "summary.json"
    spec, baseline = _write_live_only_spec(tmp_path)
    env = os.environ.copy()
    env["FILEORGANIZE_ALLOW_HOST_EXECUTION"] = "1"
    env.pop("GEMINI_API_KEY", None)
    env.pop("GEMINI_MODEL", None)

    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tooling" / "scripts" / "run_ai_eval.py"),
            "--root",
            str(repo_root),
            "--spec",
            str(spec),
            "--baseline",
            str(baseline),
            "--mode",
            "auto",
            "--output",
            str(output),
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["live_receipt"]["status"] == "skipped"


def test_ai_eval_runner_rejects_template_human_rubric(tmp_path: Path) -> None:
    repo_root = _repo_root()
    output = tmp_path / "summary.json"
    spec, baseline = _write_live_only_spec(tmp_path)
    env = os.environ.copy()
    env["FILEORGANIZE_ALLOW_HOST_EXECUTION"] = "1"
    env.pop("GEMINI_API_KEY", None)
    env.pop("GEMINI_MODEL", None)

    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tooling" / "scripts" / "run_ai_eval.py"),
            "--root",
            str(repo_root),
            "--spec",
            str(spec),
            "--baseline",
            str(baseline),
            "--mode",
            "auto",
            "--output",
            str(output),
            "--human-rubric-json",
            str(repo_root / "contracts" / "ai" / "human_rubric.example.json"),
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode != 0
    assert "template" in proc.stderr
    assert "recorded rubric" in proc.stderr


def test_ai_eval_runner_rejects_placeholder_recorded_human_rubric(tmp_path: Path) -> None:
    repo_root = _repo_root()
    output = tmp_path / "summary.json"
    spec, baseline = _write_live_only_spec(tmp_path)
    rubric = tmp_path / "human-rubric.json"
    rubric.write_text(
        json.dumps(
            {
                "status": "recorded",
                "reviewer": "human_reviewer",
                "captured_at": "2026-03-20T10:00:00-07:00",
                "agreement_rate": 0.8,
                "notes": "replace this example with a real human assessment",
                "rows": [
                    {
                        "row": "example-row",
                        "status": "borderline",
                        "notes": "replace this example with a real human assessment",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["FILEORGANIZE_ALLOW_HOST_EXECUTION"] = "1"
    env.pop("GEMINI_API_KEY", None)
    env.pop("GEMINI_MODEL", None)

    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tooling" / "scripts" / "run_ai_eval.py"),
            "--root",
            str(repo_root),
            "--spec",
            str(spec),
            "--baseline",
            str(baseline),
            "--mode",
            "auto",
            "--output",
            str(output),
            "--human-rubric-json",
            str(rubric),
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode != 0
    assert "placeholder" in proc.stderr


def test_ai_eval_runner_accepts_recorded_human_rubric(tmp_path: Path) -> None:
    repo_root = _repo_root()
    output = tmp_path / "summary.json"
    spec, baseline = _write_live_only_spec(tmp_path)
    rubric = tmp_path / "human-rubric.json"
    rubric.write_text(
        json.dumps(
            {
                "status": "recorded",
                "reviewer": "terry",
                "captured_at": "2026-03-20T10:00:00-07:00",
                "agreement_rate": 0.8,
                "notes": "reviewed against a real live run export",
                "rows": [
                    {
                        "row": "doc.pdf",
                        "status": "pass",
                        "notes": "category and title are acceptable",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["FILEORGANIZE_ALLOW_HOST_EXECUTION"] = "1"
    env.pop("GEMINI_API_KEY", None)
    env.pop("GEMINI_MODEL", None)

    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tooling" / "scripts" / "run_ai_eval.py"),
            "--root",
            str(repo_root),
            "--spec",
            str(spec),
            "--baseline",
            str(baseline),
            "--mode",
            "auto",
            "--output",
            str(output),
            "--human-rubric-json",
            str(rubric),
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["human_rubric"]["status"] == "recorded"
    assert payload["human_rubric"]["gate"] == "recorded"
    assert payload["human_rubric"]["claim_cap"] == "public"
    assert payload["upgrade_pack"]["recorded_input_unlocks_tier"] == "public"
    assert payload["human_rubric"]["rows_count"] == 1
    assert payload["human_rubric"]["source"] == str(rubric.resolve())


def test_ai_eval_runner_uses_isolated_run_bundle_root(tmp_path: Path) -> None:
    repo_root = _repo_root()
    output = tmp_path / "summary.json"
    spec, baseline = _write_runner_smoke_spec(tmp_path)
    poisoned_root = _poison_run_bundle_root(tmp_path / "poisoned-runs", "ai_eval_offline-audio-contract")
    env = os.environ.copy()
    env["FILEORGANIZE_ALLOW_HOST_EXECUTION"] = "1"
    env["FILEORGANIZE_RUN_BUNDLE_ROOT"] = str(poisoned_root)

    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tooling" / "scripts" / "run_ai_eval.py"),
            "--root",
            str(repo_root),
            "--spec",
            str(spec),
            "--baseline",
            str(baseline),
            "--mode",
            "offline",
            "--output",
            str(output),
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["overall_status"] == "passed"
    assert (poisoned_root / "ai_eval_offline-audio-contract" / "summary.json").read_text(encoding="utf-8") == ""

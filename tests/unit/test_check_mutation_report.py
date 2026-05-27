from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "tooling" / "scripts" / "check_mutation_report.py"
    spec = importlib.util.spec_from_file_location("check_mutation_report", script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_parse_mutmut_results_supports_keyword_lines() -> None:
    mod = _load_module()
    parsed = mod._parse_mutmut_results(
        """
        survived mutant #1
        timed out mutant #2
        suspicious mutant #3
        killed mutant #4
        """
    )
    assert parsed["survived"] == 1
    assert parsed["timed_out"] == 1
    assert parsed["suspicious"] == 1
    assert parsed["killed"] == 1


def test_parse_mutmut_results_supports_summary_counts() -> None:
    mod = _load_module()
    parsed = mod._parse_mutmut_results(
        """
        survived: 2
        timed out: 1
        suspicious: 3
        killed: 5
        """
    )
    assert parsed == {"survived": 2, "timed_out": 1, "suspicious": 3, "killed": 5}


def test_parse_mutmut_results_supports_heading_counts() -> None:
    mod = _load_module()
    parsed = mod._parse_mutmut_results(
        """
        Timed out ⏰ (1)
        Suspicious 🤔 (3)
        Survived 🙁 (149)
        """
    )
    assert parsed["survived"] == 149
    assert parsed["timed_out"] == 1
    assert parsed["suspicious"] == 3
    assert parsed["killed"] == 0


def test_mutation_report_main_applies_thresholds_and_json_output(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    input_file = tmp_path / "mutmut-results.txt"
    input_file.write_text("killed: 10\nsurvived: 0\ntimed out: 0\nsuspicious: 0\n", encoding="utf-8")
    output_file = tmp_path / "mutation-report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_mutation_report.py",
            "--input",
            str(input_file),
            "--max-survived",
            "0",
            "--max-timed-out",
            "0",
            "--max-suspicious",
            "0",
            "--min-killed",
            "5",
            "--json-output",
            str(output_file),
        ],
    )
    assert mod.main() == 0
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["summary"]["total"] == 10
    assert payload["summary"]["killed"] == 10
    assert payload["summary"]["kill_rate"] == 1.0
    assert payload["summary"]["operator_coverage"] == 0.0
    assert payload["violations"] == []


def test_mutation_report_main_fails_when_threshold_exceeded(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    input_file = tmp_path / "mutmut-results.txt"
    input_file.write_text("survived: 1\nkilled: 2\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_mutation_report.py",
            "--input",
            str(input_file),
            "--max-survived",
            "0",
        ],
    )
    assert mod.main() == 1


def test_mutation_report_operator_coverage_threshold(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    input_file = tmp_path / "mutmut-results.txt"
    input_file.write_text(
        "killed: 5\noperator: compare\noperator_type: boolean\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_mutation_report.py",
            "--input",
            str(input_file),
            "--max-survived",
            "0",
            "--expected-operators",
            "compare,boolean,arith",
            "--min-operator-coverage",
            "0.8",
        ],
    )
    assert mod.main() == 1


def test_parse_mutmut_results_supports_hyphenated_status_keys() -> None:
    mod = _load_module()
    parsed = mod._parse_mutmut_results(
        """
        timed-out: 2
        suspicious=3
        suspicious-result=9
        """
    )
    assert parsed["timed_out"] == 2
    assert parsed["suspicious"] == 3


def test_parse_operator_hints_normalizes_deduplicates_variants() -> None:
    mod = _load_module()
    operators = mod._parse_operator_hints(
        """
        operator: Boundary Compare
        mutation_type = boundary-compare
        mutation type: boolean flip
        """
    )
    # Counterfactual: 若去掉 normalize/deduplicate，该断言会失败。
    assert operators == {"boundary_compare", "boolean_flip"}


def test_build_summary_computes_operator_coverage_with_expected_set() -> None:
    mod = _load_module()
    summary = mod._build_summary(
        {"survived": 1, "timed_out": 0, "suspicious": 1, "killed": 8},
        {"boolean_flip", "boundary_compare"},
        {"boolean_flip", "boundary_compare", "arithmetic_swap"},
    )
    assert summary["total"] == 10
    assert summary["kill_rate"] == 0.8
    assert summary["operator_detected_count"] == 2
    assert summary["operator_expected_count"] == 3
    assert summary["operator_coverage"] == 0.6667


def test_mutation_report_main_returns_2_when_input_file_missing(monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_mutation_report.py",
            "--input",
            "missing-mutmut-results.txt",
        ],
    )
    assert mod.main() == 2


def test_mutation_report_main_reports_multiple_violations(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    input_file = tmp_path / "mutmut-results.txt"
    input_file.write_text(
        "survived: 2\ntimed out: 1\nsuspicious: 1\nkilled: 0\noperator: boundary_compare\n",
        encoding="utf-8",
    )
    output_file = tmp_path / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_mutation_report.py",
            "--input",
            str(input_file),
            "--max-survived",
            "0",
            "--max-timed-out",
            "0",
            "--max-suspicious",
            "0",
            "--min-killed",
            "1",
            "--expected-operators",
            "boundary_compare,boolean_flip",
            "--min-operator-coverage",
            "1.0",
            "--json-output",
            str(output_file),
        ],
    )
    assert mod.main() == 1
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert len(payload["violations"]) == 5
    assert payload["summary"]["operator_coverage"] == 0.5


def test_mutation_report_main_fails_on_empty_sample_when_required(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    input_file = tmp_path / "mutmut-results.txt"
    input_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_mutation_report.py",
            "--input",
            str(input_file),
            "--min-killed",
            "1",
            "--require-non-empty-sample",
        ],
    )
    assert mod.main() == 1

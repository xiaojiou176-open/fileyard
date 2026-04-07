import subprocess
import sys
from pathlib import Path


def _checker(script_root: Path) -> Path:
    return script_root / "tooling" / "scripts" / "check_coverage_thresholds.py"


def _python_bin(script_root: Path) -> Path:
    repo_root = script_root.parent
    venv_python = repo_root / ".venv" / "bin" / "python"
    return venv_python if venv_python.exists() else Path(sys.executable)


def _write_coverage_xml(path: Path, *, total: float, branch_total: float, modules: dict[str, float]) -> None:
    classes = "\n".join(
        f'<class name="{name}" filename="packages/application/{name}" line-rate="{rate:.4f}" />' for name, rate in modules.items()
    )
    content = (
        '<?xml version="1.0" ?>\n'
        f'<coverage line-rate="{total:.4f}" branch-rate="{branch_total:.4f}">\n'
        "  <packages>\n"
        '    <package name="pipeline">\n'
        "      <classes>\n"
        f"{classes}\n"
        "      </classes>\n"
        "    </package>\n"
        "  </packages>\n"
        "</coverage>\n"
    )
    path.write_text(content, encoding="utf-8")


def test_check_coverage_thresholds_passes_with_default_total95_and_key95(tmp_path: Path):
    coverage_xml = tmp_path / "coverage.xml"
    _write_coverage_xml(
        coverage_xml,
        total=0.95,
        branch_total=0.80,
        modules={
            "apply_command.py": 0.95,
            "analyze_media.py": 0.90,
            "cli_app.py": 0.95,
            "config_loader.py": 0.95,
            "gemini_client.py": 0.96,
            "logging_utils.py": 0.94,
            "manifest_store.py": 0.99,
            "pipeline_config.py": 0.97,
        },
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--coverage-xml",
            str(coverage_xml),
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0
    out = proc.stdout + proc.stderr
    assert "coverage-threshold: passed" in out
    assert "[PASS] overall=95.00%" in out


def test_check_coverage_thresholds_fails_when_key_module_missing(tmp_path: Path):
    coverage_xml = tmp_path / "coverage.xml"
    _write_coverage_xml(
        coverage_xml,
        total=0.90,
        branch_total=0.90,
        modules={
            "apply_command.py": 0.99,
            "analyze_media.py": 0.99,
            "cli_app.py": 0.99,
            "config_loader.py": 0.99,
            "gemini_client.py": 0.99,
            "logging_utils.py": 0.99,
            "manifest_store.py": 0.99,
        },
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--coverage-xml",
            str(coverage_xml),
            "--min-total",
            "80",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "missing module coverage entry: pipeline_config.py" in out


def test_check_coverage_thresholds_handles_invalid_xml(tmp_path: Path):
    coverage_xml = tmp_path / "coverage.xml"
    coverage_xml.write_text("<coverage", encoding="utf-8")

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--coverage-xml",
            str(coverage_xml),
            "--min-total",
            "80",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "invalid xml" in out


def test_check_coverage_thresholds_prefers_exact_match_over_alias(tmp_path: Path):
    coverage_xml = tmp_path / "coverage.xml"
    coverage_xml.write_text(
        """<?xml version="1.0" ?>
<coverage line-rate="0.9500" branch-rate="0.9100">
  <packages>
    <package name="pipeline">
      <classes>
        <class name="cli_app.py" filename="apps/cli/cli_app.py" line-rate="0.9900" />
        <class name="cli_app.py" filename="apps/cli/movi_organizer.py" line-rate="0.4000" />
        <class name="apply_command.py" filename="packages/application/apply_command.py" line-rate="0.9900" />
        <class name="analyze_media.py" filename="packages/application/analyze_media.py" line-rate="0.9900" />
        <class name="config_loader.py" filename="packages/infrastructure/config_loader.py" line-rate="0.9900" />
        <class name="gemini_client.py" filename="packages/infrastructure/gemini_client.py" line-rate="0.9900" />
        <class name="logging_utils.py" filename="packages/observability/logging_utils.py" line-rate="0.9900" />
        <class name="manifest_store.py" filename="packages/infrastructure/manifest_store.py" line-rate="0.9900" />
        <class name="pipeline_config.py" filename="packages/domain/pipeline_config.py" line-rate="0.9900" />
      </classes>
    </package>
  </packages>
</coverage>
""",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--coverage-xml",
            str(coverage_xml),
            "--min-total",
            "80",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0
    out = proc.stdout + proc.stderr
    assert "coverage-threshold: passed" in out
    assert "[PASS] cli_app.py=99.00%" in out


def test_check_coverage_thresholds_ignores_transient_fixture_paths_for_module_resolution(tmp_path: Path):
    coverage_xml = tmp_path / "coverage.xml"
    transient_apply_path = (
        "/root/.cache/movi-organizer/xdg/pytest-runtime/run.Xe4qrF/"
        "pytest-of-root/pytest-0/test_hotspot_budget_gate_rejec0/"
        "repo/packages/application/apply_command.py"
    )
    coverage_xml.write_text(
        f"""<?xml version="1.0" ?>
<coverage line-rate="0.9500" branch-rate="0.9100">
  <packages>
    <package name="pipeline">
      <classes>
        <class name="apply_command.py" filename="{transient_apply_path}" line-rate="0.0100" />
        <class name="apply_command.py" filename="packages/application/apply_command.py" line-rate="0.9900" />
        <class name="analyze_media.py" filename="packages/application/analyze_media.py" line-rate="0.9900" />
        <class name="cli_app.py" filename="apps/cli/cli_app.py" line-rate="0.9900" />
        <class name="cli_app.py" filename="apps/cli/movi_organizer.py" line-rate="0.4000" />
        <class name="config_loader.py" filename="packages/infrastructure/config_loader.py" line-rate="0.9900" />
        <class name="gemini_client.py" filename="packages/infrastructure/gemini_client.py" line-rate="0.9900" />
        <class name="logging_utils.py" filename="packages/observability/logging_utils.py" line-rate="0.9900" />
        <class name="manifest_store.py" filename="packages/infrastructure/manifest_store.py" line-rate="0.9900" />
        <class name="pipeline_config.py" filename="packages/domain/pipeline_config.py" line-rate="0.9900" />
      </classes>
    </package>
  </packages>
</coverage>
""",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--coverage-xml",
            str(coverage_xml),
            "--min-total",
            "80",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0
    out = proc.stdout + proc.stderr
    assert "coverage-threshold: passed" in out
    assert "[PASS] apply_command.py=99.00%" in out


def test_check_coverage_thresholds_fails_on_duplicate_filename_entries(tmp_path: Path):
    coverage_xml = tmp_path / "coverage.xml"
    coverage_xml.write_text(
        """<?xml version="1.0" ?>
<coverage line-rate="0.9500" branch-rate="0.9100">
  <packages>
    <package name="pipeline">
      <classes>
        <class name="cli_app.py" filename="apps/cli/cli_app.py" line-rate="0.4000" />
        <class name="cli_app.py" filename="apps/cli/cli_app.py" line-rate="0.9900" />
        <class name="apply_command.py" filename="packages/application/apply_command.py" line-rate="0.9900" />
        <class name="analyze_media.py" filename="packages/application/analyze_media.py" line-rate="0.9900" />
        <class name="config_loader.py" filename="packages/infrastructure/config_loader.py" line-rate="0.9900" />
        <class name="gemini_client.py" filename="packages/infrastructure/gemini_client.py" line-rate="0.9900" />
        <class name="logging_utils.py" filename="packages/observability/logging_utils.py" line-rate="0.9900" />
        <class name="manifest_store.py" filename="packages/infrastructure/manifest_store.py" line-rate="0.9900" />
        <class name="pipeline_config.py" filename="packages/domain/pipeline_config.py" line-rate="0.9900" />
      </classes>
    </package>
  </packages>
</coverage>
""",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--coverage-xml",
            str(coverage_xml),
            "--min-total",
            "80",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "duplicate class filename entries found in coverage xml" in out
    assert "apps/cli/cli_app.py" in out


def test_check_coverage_thresholds_rejects_invalid_min_total(tmp_path: Path):
    coverage_xml = tmp_path / "coverage.xml"
    _write_coverage_xml(
        coverage_xml,
        total=0.95,
        branch_total=0.95,
        modules={
            "apply_command.py": 0.99,
            "analyze_media.py": 0.99,
            "cli_app.py": 0.99,
            "config_loader.py": 0.99,
            "gemini_client.py": 0.99,
            "logging_utils.py": 0.99,
            "manifest_store.py": 0.99,
            "pipeline_config.py": 0.99,
        },
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--coverage-xml",
            str(coverage_xml),
            "--min-total",
            "120",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    out = proc.stdout + proc.stderr
    assert "invalid --min-total" in out


def test_check_coverage_thresholds_rejects_invalid_min_branch(tmp_path: Path):
    coverage_xml = tmp_path / "coverage.xml"
    _write_coverage_xml(
        coverage_xml,
        total=0.95,
        branch_total=0.95,
        modules={
            "apply_command.py": 0.99,
            "analyze_media.py": 0.99,
            "cli_app.py": 0.99,
            "config_loader.py": 0.99,
            "gemini_client.py": 0.99,
            "logging_utils.py": 0.99,
            "manifest_store.py": 0.99,
            "pipeline_config.py": 0.99,
        },
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--coverage-xml",
            str(coverage_xml),
            "--min-branch",
            "120",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    out = proc.stdout + proc.stderr
    assert "invalid --min-branch" in out

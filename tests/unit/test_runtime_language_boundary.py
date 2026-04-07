from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_checker(*, root: Path, policy: Path | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "tooling" / "scripts" / "check_runtime_language_boundary.py"),
        "--root",
        str(root),
    ]
    if policy is not None:
        cmd.extend(["--policy", str(policy.relative_to(root))])
    return subprocess.run(cmd, cwd=root, text=True, capture_output=True, check=False)


def test_runtime_language_boundary_script_passes_for_current_repo() -> None:
    result = _run_checker(root=REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "runtime-language-boundary: passed" in result.stdout


def test_runtime_language_boundary_rejects_localized_maintainer_diagnostics(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "contracts" / "governance").mkdir(parents=True)
    (repo / "pkg").mkdir(parents=True)

    (repo / "contracts" / "governance" / "runtime_language_boundary_policy.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "targets:",
                "  - path: pkg/diag.py",
                "    class: maintainer-facing",
                "    required_substrings:",
                '      - "Invalid run id"',
                "    forbidden_regex:",
                '      - "[\\\\u3400-\\\\u4dbf\\\\u4e00-\\\\u9fff\\\\uf900-\\\\ufaff\\\\u3040-\\\\u30ff]"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "pkg" / "diag.py").write_text('raise RuntimeError("非法 run_id")\n', encoding="utf-8")

    result = _run_checker(root=repo, policy=repo / "contracts" / "governance" / "runtime_language_boundary_policy.yaml")
    assert result.returncode == 1
    assert "runtime-language-boundary: failed" in (result.stdout + result.stderr)


def test_runtime_language_boundary_allows_explicit_localized_literals_in_mixed_surface(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "contracts" / "governance").mkdir(parents=True)
    (repo / "pkg").mkdir(parents=True)

    (repo / "contracts" / "governance" / "runtime_language_boundary_policy.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "targets:",
                "  - path: pkg/view.ts",
                "    class: mixed-with-allowed-localized-literals",
                "    required_substrings:",
                '      - "Batch save failed:"',
                '      - "\\"其他\\""',
                "    allowed_regex:",
                '      - "其他"',
                "    forbidden_regex:",
                '      - "[\\\\u3400-\\\\u4dbf\\\\u4e00-\\\\u9fff\\\\uf900-\\\\ufaff\\\\u3040-\\\\u30ff]"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "pkg" / "view.ts").write_text(
        'throw new Error("Batch save failed: backend mismatch");\nconst fallback = "其他";\n',
        encoding="utf-8",
    )

    result = _run_checker(root=repo, policy=repo / "contracts" / "governance" / "runtime_language_boundary_policy.yaml")
    assert result.returncode == 0, result.stdout + result.stderr

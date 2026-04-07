from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_checker(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tooling" / "scripts" / "check_patch_registry_alignment.py"),
            "--root",
            str(root),
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_package(path: Path, overrides: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"name": path.stem, "overrides": overrides}, indent=2) + "\n", encoding="utf-8")


def test_patch_registry_alignment_passes_for_current_repo() -> None:
    result = _run_checker(REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "patch-registry-alignment passed" in (result.stdout + result.stderr)


def test_patch_registry_alignment_fails_on_value_drift(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "contracts" / "upstreams").mkdir(parents=True)
    (repo / "apps" / "webui").mkdir(parents=True)

    (repo / "contracts" / "upstreams" / "patch_registry.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "patches:",
                "  - id: npm-override-flatted-root",
                "    upstream_id: node-lock",
                "    surface: package.json",
                "    mechanism: npm-overrides",
                "    target: flatted",
                "    pinned_value: 3.4.1",
                "    reason: audited-transitive-fix",
                "    rollback: restore package.json",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _write_package(repo / "package.json", {"flatted": "3.4.2"})
    _write_package(repo / "apps" / "webui" / "package.json", {})

    result = _run_checker(repo)
    assert result.returncode == 1
    assert "pinned_value drift for package.json -> flatted" in (result.stdout + result.stderr)

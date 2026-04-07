from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False, env=merged_env)


def _init_repo(tmp_path: Path) -> tuple[Path, Path, str]:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True)
    subprocess.run(["git", "init", str(repo)], check=True, text=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Codex"], check=True, text=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "codex@example.com"], check=True, text=True, capture_output=True)
    (repo / "tracked.txt").write_text("release\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True, text=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, text=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(remote)], check=True, text=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "push", "-u", "origin", "HEAD:main"], check=True, text=True, capture_output=True)
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    return repo, remote, head


def test_materialize_release_tag_requires_apply_before_remote_creation(tmp_path: Path) -> None:
    repo, _remote, head = _init_repo(tmp_path)
    proc = _run(
        ["bash", str(REPO_ROOT / "tooling" / "ci" / "materialize_release_tag.sh"), "v1.2.3", head],
        repo,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "release tag is not materialized" in out


def test_materialize_release_tag_creates_and_pushes_remote_tag_when_apply_enabled(tmp_path: Path) -> None:
    repo, remote, head = _init_repo(tmp_path)
    proc = _run(
        ["bash", str(REPO_ROOT / "tooling" / "ci" / "materialize_release_tag.sh"), "v1.2.3", head],
        repo,
        env={"RELEASE_TAG_APPLY": "1"},
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "release tag materialized" in out
    remote_refs = subprocess.run(
        ["git", "ls-remote", "--tags", str(remote), "refs/tags/v1.2.3"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    assert "refs/tags/v1.2.3" in remote_refs


def test_materialize_release_tag_bootstraps_git_identity_when_missing(tmp_path: Path) -> None:
    repo, remote, head = _init_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "config", "--unset", "user.name"], check=True, text=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "--unset", "user.email"], check=True, text=True, capture_output=True)

    proc = _run(
        ["bash", str(REPO_ROOT / "tooling" / "ci" / "materialize_release_tag.sh"), "v1.2.4", head],
        repo,
        env={"RELEASE_TAG_APPLY": "1"},
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        == "github-actions[bot]"
    )
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        == "41898282+github-actions[bot]@users.noreply.github.com"
    )
    remote_refs = subprocess.run(
        ["git", "ls-remote", "--tags", str(remote), "refs/tags/v1.2.4"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    assert "refs/tags/v1.2.4" in remote_refs

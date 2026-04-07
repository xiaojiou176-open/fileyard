from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _user_home_path(user: str, *parts: str) -> str:
    return "/" + "/".join(("Users", user, *parts))


def _workspace_path(*parts: str) -> str:
    return "/" + "/".join(("workspace-fixture", *parts))


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", str(repo)], check=True, text=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Codex"], check=True, text=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "codex@example.com"], check=True, text=True, capture_output=True)
    (repo / "README.md").write_text("# fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True, text=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, text=True, capture_output=True)
    return repo


def _run_gate(repo: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            sys.executable,
            str(REPO_ROOT / "tooling" / "scripts" / "check_sensitive_surface.py"),
            "--root",
            str(repo),
            *extra_args,
        ],
        repo,
    )


def test_sensitive_surface_gate_passes_clean_repo(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    proc = _run_gate(repo)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "sensitive-surface gate passed" in (proc.stdout + proc.stderr)


def test_sensitive_surface_gate_blocks_absolute_private_path(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    docs = repo / "docs"
    docs.mkdir()
    source_path = _user_home_path("case-user", "private", "photos", "image.png")
    (docs / "notes.md").write_text(f"source={source_path}\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "docs/notes.md"], check=True, text=True, capture_output=True)

    proc = _run_gate(repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "ABSOLUTE_PRIVATE_PATH" in out
    assert "docs/notes.md:1" in out


def test_sensitive_surface_gate_allows_generic_workspace_paths_in_tests(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    tests_dir = repo / "tests" / "unit"
    tests_dir.mkdir(parents=True)
    fixture_path = _workspace_path("private", "photos", "image.png")
    docker_socket = "unix://" + _workspace_path(".docker", "run", "docker.sock")
    (tests_dir / "test_redaction.py").write_text(
        f'PATH = "{fixture_path}"\nOTHER = "{docker_socket}"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "add", "tests/unit/test_redaction.py"], check=True, text=True, capture_output=True)

    proc = _run_gate(repo)

    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_sensitive_surface_gate_blocks_personal_email_and_phone(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    docs = repo / "docs"
    docs.mkdir()
    email = "@".join(("terry", "gmail.com"))
    phone = "-".join(("206", "555", "1212"))
    (docs / "contacts.md").write_text(
        f"reach {email} or call {phone}\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "add", "docs/contacts.md"], check=True, text=True, capture_output=True)

    proc = _run_gate(repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "PERSONAL_EMAIL" in out
    assert "PHONE_NUMBER" in out


def test_sensitive_surface_gate_blocks_real_authorization_header_dump(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    docs = repo / "docs"
    docs.mkdir()
    token = "".join(("abcdefghijkl", "mnopqrstuvwx"))
    (docs / "headers.md").write_text(
        f"Authorization: Bearer {token}\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "add", "docs/headers.md"], check=True, text=True, capture_output=True)

    proc = _run_gate(repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "SENSITIVE_HEADER_DUMP" in out


def test_sensitive_surface_gate_blocks_forbidden_tracked_artifact_extension(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    logs_dir = repo / "logs"
    logs_dir.mkdir()
    (logs_dir / "app.log").write_text("trace\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "logs/app.log"], check=True, text=True, capture_output=True)

    proc = _run_gate(repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "FORBIDDEN_TRACKED_ARTIFACT" in out
    assert "logs/app.log" in out

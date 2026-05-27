from __future__ import annotations

from pathlib import Path

from packages.infrastructure import runtime_env


def test_workspace_root_runtime_env_and_resolve_helpers(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_file = workspace / ".fileyard" / "env" / "runtime.env"
    runtime_file.parent.mkdir(parents=True)
    runtime_file.write_text(
        "\n".join(
            [
                "# comment",
                "GEMINI_API_KEY=' from_runtime_env '",
                'FILEYARD_INPUT_ROOT="/tmp/input root"',
                "IGNORED_LINE",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FILEYARD_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("GEMINI_API_KEY", "from_env")
    monkeypatch.delenv("FILEYARD_INPUT_ROOT", raising=False)

    assert runtime_env.workspace_root() == workspace
    assert runtime_env.runtime_env_file() == runtime_file
    assert runtime_env.read_runtime_env() == {
        "GEMINI_API_KEY": "from_runtime_env",
        "FILEYARD_INPUT_ROOT": "/tmp/input root",
    }
    assert runtime_env.resolve_env_value("GEMINI_API_KEY", root=workspace) == "from_env"
    assert runtime_env.resolve_env_value("MISSING", "fallback", root=workspace) == "fallback"
    assert runtime_env.resolve_path_value("FILEYARD_INPUT_ROOT", "/tmp/default", root=workspace) == Path("/tmp/input root")


def test_upsert_runtime_env_merges_and_drops_blank_values(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    env_path = workspace / ".fileyard" / "env" / "runtime.env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text(
        "\n".join(
            [
                "# keep me",
                "EXISTING=value",
                "REMOVE_ME=gone",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    written = runtime_env.upsert_runtime_env(
        {
            "EXISTING": "new value",
            "REMOVE_ME": "",
            "NEW_KEY": "needs quotes # here",
        },
        root=workspace,
    )

    assert written == env_path
    assert env_path.read_text(encoding="utf-8").splitlines() == [
        "# keep me",
        'EXISTING="new value"',
        'NEW_KEY="needs quotes # here"',
    ]


def test_mask_secret_handles_short_and_long_values() -> None:
    assert runtime_env.mask_secret("") == ""
    assert runtime_env.mask_secret("abcd", prefix=2, suffix=2) == "****"
    assert runtime_env.mask_secret("secret-token", prefix=2, suffix=3) == "se*******ken"

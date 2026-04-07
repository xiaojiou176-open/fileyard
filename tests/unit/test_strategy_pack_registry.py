from __future__ import annotations

from pathlib import Path

from packages.domain.strategy_pack_registry import load_strategy_packs, strategy_pack_by_id, strategy_pack_paths


def test_strategy_pack_registry_loads_repo_shipped_yaml_files() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    packs = load_strategy_packs(repo_root)
    ids = {pack.id for pack in packs}
    assert {"travel", "receipts", "chat-export", "meeting-notes"} <= ids
    travel = next(pack for pack in packs if pack.id == "travel")
    assert travel.to_dict()["defaults"]["workers"] >= 1
    assert "setup_note" in travel.to_dict()["explainability"]


def test_strategy_pack_registry_handles_missing_root_and_lookup() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    assert strategy_pack_paths(repo_root / "missing-root") == []
    assert strategy_pack_by_id(repo_root, "travel") is not None
    assert strategy_pack_by_id(repo_root, "missing") is None


def test_strategy_pack_registry_skips_non_dict_yaml_payloads(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    strategy_dir = repo / "contracts" / "strategies"
    strategy_dir.mkdir(parents=True)
    (strategy_dir / "invalid.yaml").write_text("- item\n", encoding="utf-8")
    (strategy_dir / "valid.yaml").write_text(
        "\n".join(
            [
                "id: valid",
                "name: Valid",
                "description: test",
                "categories:",
                "  - 工作",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    packs = load_strategy_packs(repo)
    assert [pack.id for pack in packs] == ["valid"]

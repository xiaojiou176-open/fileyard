from __future__ import annotations

import json
from pathlib import Path

from packages.infrastructure.learned_rule_store import LearnedRule, learned_rule_path, load_learned_rules, save_learned_rules
from packages.infrastructure.preference_store import (
    legacy_preference_file,
    migrate_legacy_named_items,
    preference_file,
    read_named_items,
    write_named_items,
)
from packages.infrastructure.strategy_pack_store import (
    get_active_strategy_pack,
    get_active_strategy_pack_id,
    list_strategy_pack_payloads,
    set_active_strategy_pack_id,
)


def test_learned_rule_store_round_trips_and_filters_invalid_payloads(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    rule = LearnedRule(
        id="rule-1",
        signal_key="media_type",
        signal_value="image",
        suggestion_type="category",
        suggestion_value="旅行",
        confidence=0.8,
        count=3,
        confidence_label="medium",
        strength="medium",
        reuse_scope="reusable",
        source="workspace_review_learning_v1",
        reason="Observed 3 accepted review edit(s) mapping media_type=image to 旅行.",
        explanation="Observed 3 accepted review edit(s) mapping media_type=image to 旅行.",
        updated_at="2026-03-29T00:00:00Z",
    )
    path = save_learned_rules(workspace, [rule], updated_at="2026-03-29T00:00:00Z")
    assert path == learned_rule_path(workspace)
    loaded = load_learned_rules(workspace)
    assert loaded == [rule]

    path.write_text(json.dumps({"items": ["bad", {"id": "", "signal_key": "x"}]}, ensure_ascii=False), encoding="utf-8")
    assert load_learned_rules(workspace) == []

    path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "rule-2",
                        "signal_key": "x",
                        "signal_value": "y",
                        "suggestion_type": "category",
                        "suggestion_value": "旅行",
                        "confidence": "bad",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert load_learned_rules(workspace) == []
    assert rule.to_dict()["id"] == "rule-1"
    assert rule.to_dict()["strength"] == "medium"
    assert rule.to_dict()["reuse_scope"] == "reusable"
    assert rule.to_dict()["explanation"] == rule.reason


def test_preference_store_reads_writes_and_migrates_legacy_payloads(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    items = {"view-1": {"value": {"name": "Default"}, "created_at": "t1", "updated_at": "t2"}}
    current = write_named_items(workspace, "views", items, updated_at="t2")
    assert current == preference_file(workspace, "views")
    assert read_named_items(workspace, "views") == items

    legacy_path = legacy_preference_file(workspace, "review_rules")
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(json.dumps({"items": {"rule-1": {"value": {"name": "legacy"}}}}, ensure_ascii=False), encoding="utf-8")
    migrated = migrate_legacy_named_items(workspace, "review_rules", updated_at="t3")
    assert migrated == preference_file(workspace, "review_rules")
    assert read_named_items(workspace, "review_rules") == {"rule-1": {"value": {"name": "legacy"}}}
    assert migrate_legacy_named_items(workspace, "review_rules", updated_at="t4") is None

    broken = preference_file(workspace, "broken")
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text(json.dumps({"items": []}, ensure_ascii=False), encoding="utf-8")
    assert read_named_items(workspace, "broken") == {}
    assert migrate_legacy_named_items(workspace, "missing", updated_at="t5") is None


def test_strategy_pack_store_reads_and_writes_active_pack(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    workspace = tmp_path / "workspace"
    set_active_strategy_pack_id(workspace, "travel", updated_at="2026-03-29T00:00:00Z")
    assert get_active_strategy_pack_id(workspace) == "travel"
    assert get_active_strategy_pack(repo_root, workspace).id == "travel"  # type: ignore[union-attr]
    payloads = list_strategy_pack_payloads(repo_root)
    assert any(item["id"] == "travel" for item in payloads)
    travel = next(item for item in payloads if item["id"] == "travel")
    assert travel["defaults"]["workers"] >= 1
    assert "inbox_note" in travel["explainability"]

    invalid_path = preference_file(workspace, "strategy_packs")
    invalid_path.write_text(json.dumps({"items": {"active": {"value": "bad"}}}, ensure_ascii=False), encoding="utf-8")
    assert get_active_strategy_pack_id(workspace) == ""
    assert get_active_strategy_pack(repo_root, workspace) is None

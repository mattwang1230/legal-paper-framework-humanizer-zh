#!/usr/bin/env python3
"""Validate whether a claimed framework edit contains real node changes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


STRUCTURAL_ACTIONS = {"move", "merge", "split"}


def _nodes(outline: list[dict]) -> dict[str, tuple[str | None, int, int]]:
    result: dict[str, tuple[str | None, int, int]] = {}
    for chapter_index, chapter in enumerate(outline):
        chapter_id = chapter.get("id")
        if chapter_id:
            result[chapter_id] = (None, chapter_index, 1)
        for child_index, child in enumerate(chapter.get("children", [])):
            child_id = child.get("id")
            if child_id:
                result[child_id] = (chapter_id, child_index, 2)
    return result


def _shape(outline: list[dict]) -> list[int]:
    return [len(chapter.get("children", [])) for chapter in outline]


def evaluate_case(case: dict) -> dict:
    baseline = case["baseline_outline"]
    revision = case["revision_outline"]
    claim = case["claim"]
    before = _nodes(baseline)
    after = _nodes(revision)
    shared = set(before) & set(after)
    moved = sorted(node_id for node_id in shared if before[node_id] != after[node_id])
    removed = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))
    shape_changed = _shape(baseline) != _shape(revision)
    real_change = shape_changed or bool(moved or removed or added)
    declared = case.get("structural_diff", [])
    declared_action = any(item.get("action") in STRUCTURAL_ACTIONS for item in declared)

    if claim == "retain_structure":
        accepted = not real_change
        classification = "retain_structure" if accepted else "undeclared_structural_change"
    elif claim == "structural_change":
        accepted = real_change and declared_action
        classification = "structural_change" if accepted else "token_swap_only"
    else:
        accepted = not real_change
        classification = "local_edit" if accepted else "undeclared_structural_change"

    return {
        "id": case.get("id"),
        "accepted": accepted,
        "classification": classification,
        "real_structural_change": real_change,
        "token_swap_only": claim == "structural_change" and not real_change,
        "shape_before": _shape(baseline),
        "shape_after": _shape(revision),
        "moved": moved,
        "removed": removed,
        "added": added,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    cases = payload.get("structural_cases", [payload])
    results = [evaluate_case(case) for case in cases]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    ok = all(
        result["accepted"] == case.get("expected", {}).get("accepted", result["accepted"])
        for case, result in zip(cases, results)
    )
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()

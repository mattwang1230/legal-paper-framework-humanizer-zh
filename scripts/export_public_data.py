#!/usr/bin/env python3
"""Export a copyright-safer public subset from the internal vocabulary data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


BLOCKED_TERMS = ("界分", "生成链条", "争点")


def canonical_text_bytes(path: Path) -> bytes:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return text.encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(canonical_text_bytes(path)).hexdigest()


def nonempty_line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def labels(values: object) -> str:
    if not isinstance(values, list):
        return ""
    found = []
    for item in values:
        if isinstance(item, dict) and item.get("label"):
            found.append(str(item["label"]))
    return ";".join(sorted(set(found)))


def export_lexical(source: Path, destination: Path) -> tuple[int, int]:
    fields = [
        "candidate_id",
        "term",
        "candidate_kind",
        "extraction_method",
        "paper_count",
        "occurrences",
        "levels",
        "level_distribution",
        "task_labels",
        "domain_tags",
        "risk_flags",
        "noise_flags",
        "wordhood_score",
        "year_distribution",
        "paper_ids",
        "source_level",
        "status",
    ]
    rows: list[dict[str, object]] = []
    excluded = 0
    with source.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            term = str(record.get("normalized_form", "")).strip()
            if not term or any(blocked in term for blocked in BLOCKED_TERMS):
                excluded += 1
                continue
            rows.append(
                {
                    "candidate_id": record.get("record_id", ""),
                    "term": term,
                    "candidate_kind": record.get("candidate_kind", record.get("kind", "")),
                    "extraction_method": record.get("extraction_method", ""),
                    "paper_count": record.get("paper_count", 0),
                    "occurrences": record.get("occurrences", 0),
                    "levels": ";".join(map(str, record.get("levels", []))),
                    "level_distribution": compact_json(record.get("level_distribution", {})),
                    "task_labels": labels(record.get("task_labels", [])),
                    "domain_tags": ";".join(sorted(map(str, record.get("domain_tags", [])))),
                    "risk_flags": ";".join(sorted(map(str, record.get("risk_flags", [])))),
                    "noise_flags": ";".join(sorted(map(str, record.get("noise_flags", [])))),
                    "wordhood_score": (record.get("wordhood") or {}).get("score", ""),
                    "year_distribution": compact_json(record.get("year_distribution", {})),
                    "paper_ids": ";".join(sorted(map(str, record.get("paper_ids", [])))),
                    "source_level": record.get("source_level", "A1/A2"),
                    "status": "pending_human_review",
                }
            )
    rows.sort(key=lambda row: (str(row["term"]), str(row["candidate_id"])))
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows), excluded


def export_keywords(source: Path, destination: Path) -> int:
    rows: list[dict[str, str]] = []
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            keyword = (row.get("keyword") or "").strip()
            if not keyword or any(blocked in keyword for blocked in BLOCKED_TERMS):
                continue
            rows.append(
                {
                    "keyword": keyword,
                    "occurrences": row.get("occurrences", ""),
                    "paper_count": row.get("paper_count", ""),
                    "source_level": "B",
                    "use_limit": "routing_only",
                }
            )
    rows.sort(key=lambda row: (-int(row["paper_count"] or 0), row["keyword"]))
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["keyword", "occurrences", "paper_count", "source_level", "use_limit"],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lexical-candidates", type=Path, required=True)
    parser.add_argument("--keyword-frequency", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    lexical_out = args.out_dir / "lexical_candidates.tsv"
    keyword_out = args.out_dir / "keyword_router_frequency.tsv"
    lexical_count, excluded_count = export_lexical(args.lexical_candidates, lexical_out)
    keyword_count = export_keywords(args.keyword_frequency, keyword_out)

    title_patterns = args.out_dir / "title_patterns.jsonl"
    routing_index = args.out_dir / "routing_index.json"
    route_files = sorted(path for path in (args.out_dir / "routes").rglob("*") if path.is_file())
    title_pattern_count = nonempty_line_count(title_patterns) if title_patterns.is_file() else 0

    manifest = {
        "schema_version": "public-data.v2",
        "scope": "scope_limited: mainly Journal of Law (法学), single-journal snapshot",
        "evidence": {
            "lexical_candidates": "A1/A2 body TOC; pending human review; not recommendations",
            "keyword_router": "B-level metadata/abstract keywords; routing only",
            "title_patterns": "A1/A2 body-TOC-derived structural skeletons; no raw headings; pending human review",
            "routing_shards": "static pattern selection by department, research type, and heading level",
        },
        "counts": {
            "lexical_candidates_public": lexical_count,
            "lexical_candidates_blocked_or_empty": excluded_count,
            "keyword_router_terms_public": keyword_count,
            "private_pipeline_candidates": 1837,
            "private_pipeline_recommendations": 0,
            "title_patterns_public": title_pattern_count,
            "routing_shards_public": len(route_files),
        },
        "privacy": {
            "raw_headings_included": False,
            "abstract_spans_included": False,
            "source_urls_included": False,
            "local_paths_included": False,
            "raw_title_patterns_included": False,
        },
        "outputs": {
            lexical_out.name: {"sha256": sha256(lexical_out), "bytes": len(canonical_text_bytes(lexical_out))},
            keyword_out.name: {"sha256": sha256(keyword_out), "bytes": len(canonical_text_bytes(keyword_out))},
            **(
                {
                    title_patterns.name: {
                        "sha256": sha256(title_patterns),
                        "bytes": len(canonical_text_bytes(title_patterns)),
                    }
                }
                if title_patterns.is_file()
                else {}
            ),
            **(
                {
                    routing_index.name: {
                        "sha256": sha256(routing_index),
                        "bytes": len(canonical_text_bytes(routing_index)),
                    }
                }
                if routing_index.is_file()
                else {}
            ),
            "routing_shards": {
                "files": len(route_files),
                "bytes": sum(len(canonical_text_bytes(path)) for path in route_files),
            },
        },
    }
    manifest_path = args.out_dir / "public_data_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["counts"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

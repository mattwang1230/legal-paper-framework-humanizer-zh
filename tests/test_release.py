from __future__ import annotations

import csv
import hashlib
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def canonical_text_bytes(path: Path) -> bytes:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


class ReleaseTest(unittest.TestCase):
    def test_required_files(self) -> None:
        for relative in (
            "README.md",
            "LICENSE",
            "NOTICE.md",
            "SKILL.md",
            "references/corpus_methodology.md",
            "data/lexical_candidates.tsv",
            "data/keyword_router_frequency.tsv",
            "data/public_data_manifest.json",
            "data/title_patterns.jsonl",
            "data/routing_index.json",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_only_one_skill_entrypoint(self) -> None:
        self.assertEqual([ROOT / "SKILL.md"], list(ROOT.rglob("SKILL.md")))

    def test_no_private_paths_or_opaque_cnki_queries(self) -> None:
        forbidden = (
            "C:" + "\\Users\\" + "22695",
            "Users" + "/" + "22695",
            "App" + "Data",
            "kns.cnki.net" + "/kcms2/article/abstract" + "?v=",
        )
        for path in ROOT.rglob("*"):
            if (
                not path.is_file()
                or ".git" in path.parts
                or "__pycache__" in path.parts
                or path.suffix in {".pyc", ".png", ".jpg", ".jpeg"}
            ):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for value in forbidden:
                self.assertNotIn(value, text, f"{value!r} in {path.relative_to(ROOT)}")

    def test_public_candidates_are_pending_and_context_free(self) -> None:
        with (ROOT / "data/lexical_candidates.tsv").open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        self.assertGreater(len(rows), 1000)
        self.assertTrue(all(row["status"] == "pending_human_review" for row in rows))
        forbidden_columns = {"raw_heading", "heading", "abstract", "source_url", "source_file", "title_context"}
        self.assertTrue(forbidden_columns.isdisjoint(rows[0]))

    def test_manifest_matches_public_data(self) -> None:
        manifest = json.loads((ROOT / "data/public_data_manifest.json").read_text(encoding="utf-8"))
        with (ROOT / "data/lexical_candidates.tsv").open(encoding="utf-8") as handle:
            lexical_lines = sum(1 for _ in handle) - 1
        with (ROOT / "data/keyword_router_frequency.tsv").open(encoding="utf-8") as handle:
            keyword_lines = sum(1 for _ in handle) - 1
        self.assertEqual(lexical_lines, manifest["counts"]["lexical_candidates_public"])
        self.assertEqual(keyword_lines, manifest["counts"]["keyword_router_terms_public"])
        self.assertEqual(0, manifest["counts"]["private_pipeline_recommendations"])
        pattern_lines = sum(
            1 for line in (ROOT / "data/title_patterns.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()
        )
        route_files = [path for path in (ROOT / "data/routes").rglob("*") if path.is_file()]
        self.assertEqual(pattern_lines, manifest["counts"]["title_patterns_public"])
        self.assertEqual(len(route_files), manifest["counts"]["routing_shards_public"])
        self.assertEqual(
            sum(len(canonical_text_bytes(path)) for path in route_files),
            manifest["outputs"]["routing_shards"]["bytes"],
        )
        for relative in ("title_patterns.jsonl", "routing_index.json"):
            path = ROOT / "data" / relative
            digest = hashlib.sha256(canonical_text_bytes(path)).hexdigest()
            self.assertEqual(digest, manifest["outputs"][relative]["sha256"])

    def test_title_patterns_are_structure_only_and_context_free(self) -> None:
        records = [
            json.loads(line)
            for line in (ROOT / "data/title_patterns.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(32, len(records))
        self.assertEqual(len(records), len({record["pattern_id"] for record in records}))
        self.assertIn("〔规范对象〕＋法律动作", {record["skeleton"] for record in records})
        self.assertIn("〔适用条件〕＋法律效果", {record["skeleton"] for record in records})
        forbidden_fields = {"raw_heading", "heading", "title", "abstract", "author", "source_url", "source_file"}
        for record in records:
            self.assertTrue(forbidden_fields.isdisjoint(record))
            self.assertEqual("pending_human_review", record["review_status"])
            self.assertEqual("structure_only", record["use_limit"])
            self.assertEqual("不含期刊原始标题", record["source_exposure"])
        published_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [ROOT / "data/title_patterns.jsonl", *sorted((ROOT / "data/routes").rglob("*"))]
            if path.is_file()
        )
        for forbidden in ("界分", "生成链条", "争点"):
            self.assertNotIn(forbidden, published_text)

    def test_static_routing_index_and_shards_are_consistent(self) -> None:
        index = json.loads((ROOT / "data/routing_index.json").read_text(encoding="utf-8"))
        self.assertFalse(index["runtime"]["script_required"])
        self.assertEqual([], index["runtime"]["third_party_dependencies"])
        self.assertEqual(8, len(index["axes"]["departments"]))
        self.assertEqual(6, len(index["axes"]["research_types"]))
        self.assertEqual(3, len(index["axes"]["levels"]))

        patterns = {
            record["pattern_id"]: record
            for record in (
                json.loads(line)
                for line in (ROOT / "data/title_patterns.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        }
        root_resolved = ROOT.resolve()
        for axis in ("departments", "research_types"):
            for route in index["axes"][axis].values():
                relative = Path(route["file"])
                self.assertFalse(relative.is_absolute())
                shard = (ROOT / relative).resolve()
                self.assertTrue(shard.is_relative_to(root_resolved))
                self.assertTrue(shard.is_file())
                record = json.loads(shard.read_text(encoding="utf-8"))
                self.assertTrue(set(record["preferred_pattern_ids"]).issubset(patterns))
                self.assertLess(shard.stat().st_size, 30_000)

        for level_text, route in index["axes"]["levels"].items():
            level = int(level_text)
            shard = ROOT / route["file"]
            records = [json.loads(line) for line in shard.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(
                {pattern_id for pattern_id, record in patterns.items() if level in record["levels"]},
                {record["pattern_id"] for record in records},
            )
            self.assertLess(shard.stat().st_size, 30_000)

    def test_skill_contract_markers(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for marker in (
            "结构层",
            "标题层",
            "术语层",
            "论证层",
            "研究背景与意义",
            "国内外研究现状",
            "retain_structure",
            "token_swap_only",
            "structural_diff",
            "待人工审核候选",
        ):
            self.assertIn(marker, text)
        self.assertRegex(text, re.compile(r"(?:生成推荐|推荐库)为0"))


if __name__ == "__main__":
    unittest.main()

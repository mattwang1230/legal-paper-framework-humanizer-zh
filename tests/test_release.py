from __future__ import annotations

import csv
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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

import json
import unittest
from pathlib import Path

from scripts.validate_structural_edit import evaluate_case
from scripts.export_public_data import BLOCKED_TERMS


SKILL_ROOT = Path(__file__).resolve().parents[1]
SKILL_TEXT = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
DEFENSE_TEXT = (SKILL_ROOT / "references" / "ai_language_defense.md").read_text(encoding="utf-8")
FIXTURES = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "framework_edit_contract.json").read_text(encoding="utf-8")
)


class SkillContractTests(unittest.TestCase):
    def test_semantic_invariant_gate_is_explicit(self):
        for term in ("语义不变量", "法律主体", "构成要件", "抗辩", "证明责任", "救济类型", "法律后果"):
            self.assertIn(term, SKILL_TEXT)
        self.assertIn("输入没有提供的项目，修订稿不得自行补入", SKILL_TEXT)

    def test_same_structure_token_swap_is_not_accepted(self):
        self.assertIn("应判为无效修改并重做", SKILL_TEXT)
        self.assertIn("拒绝同构换词", DEFENSE_TEXT)

    def test_normative_headings_are_protected(self):
        case = next(item for item in FIXTURES["cases"] if item["id"] == "normative_title_protection")
        self.assertEqual("preserve_exact", case["expected"])
        for heading in case["input_headings"]:
            self.assertIn(heading, DEFENSE_TEXT)

    def test_dispute_term_is_protected(self):
        case = next(item for item in FIXTURES["cases"] if item["id"] == "dispute_term_protection")
        self.assertEqual("preserve_when_contextually_accurate", case["expected"])
        self.assertIn("“争点”属于可以保留的法学术语", SKILL_TEXT)
        self.assertIn("原文准确使用“争点”时予以保留", DEFENSE_TEXT)
        self.assertNotIn("争点", BLOCKED_TERMS)

    def test_humanizer_rules_are_selective(self):
        for pattern in ("填充短语", "模糊归因", "三段式", "否定式排比", "虚假范围", "同义词循环", "通用积极结论", "破折号"):
            self.assertIn(pattern, SKILL_TEXT + DEFENSE_TEXT)
        for boundary in ("不引入第一人称", "幽默", "故意混乱"):
            self.assertIn(boundary, DEFENSE_TEXT)

    def test_current_corpus_counts_are_consistent(self):
        for text in (SKILL_TEXT, (SKILL_ROOT / "references" / "quantitative_model.md").read_text(encoding="utf-8")):
            self.assertIn("236篇", text)
            self.assertIn("4509条", text)
            self.assertIn("4505条", text)

    def test_fixture_covers_all_new_regression_classes(self):
        ids = {item["id"] for item in FIXTURES["cases"]}
        self.assertEqual(
            {
                "normative_title_protection",
                "semantic_expansion_trap",
                "same_structure_token_swap",
                "dispute_term_protection",
                "humanizer_legal_boundary",
            },
            ids,
        )

    def test_structural_fixtures_are_executable(self):
        cases = {item["id"]: item for item in FIXTURES["structural_cases"]}
        self.assertEqual(
            {
                "nested_same_shape_token_swap",
                "natural_progression_noop",
                "merge_required_evidence_bundle",
                "reorder_only",
            },
            set(cases),
        )
        for case in cases.values():
            result = evaluate_case(case)
            self.assertEqual(case["expected"]["accepted"], result["accepted"], case["id"])
            self.assertEqual(case["expected"]["classification"], result["classification"], case["id"])

    def test_structural_claim_requires_real_node_change(self):
        case = next(item for item in FIXTURES["structural_cases"] if item["id"] == "nested_same_shape_token_swap")
        result = evaluate_case(case)
        self.assertFalse(result["accepted"])
        self.assertTrue(result["token_swap_only"])
        self.assertFalse(result["real_structural_change"])

    def test_natural_progression_can_retain_structure(self):
        case = next(item for item in FIXTURES["structural_cases"] if item["id"] == "natural_progression_noop")
        result = evaluate_case(case)
        self.assertTrue(result["accepted"])
        self.assertEqual("retain_structure", result["classification"])


if __name__ == "__main__":
    unittest.main()

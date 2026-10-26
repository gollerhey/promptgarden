"""promptgarden —— 自检测试。

维护提示词变体集合，在同一批输入上跑出对照结果并排出优劣。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import promptgarden  # noqa: E402


class TestPromptGarden(unittest.TestCase):
    def setUp(self):
        self.garden = {
            "inputs": ["i1", "i2"],
            "variants": {
                "v1": {"prompt": "你是助手", "runs": {"i1": "答案甲", "i2": "答案乙"}},
                "v2": {"prompt": "你是客服", "runs": {"i1": "答案甲", "i2": "答案丙"}},
            },
        }

    def test_variants_are_compared(self):
        r = promptgarden.compare_variants(self.garden)
        self.assertTrue(r["comparable"])
        self.assertEqual(len(r["comparisons"]), 1)

    def test_identical_outputs_are_counted(self):
        r = promptgarden.compare_variants(self.garden)
        self.assertEqual(r["comparisons"][0]["identical"], 1)

    def test_coverage_is_reported(self):
        r = promptgarden.compare_variants(self.garden)
        self.assertEqual(r["coverage"]["v1"], 1.0)
        self.assertEqual(r["coverage"]["v2"], 1.0)

    def test_incomplete_coverage_is_flagged(self):
        self.garden["variants"]["v2"]["runs"].pop("i2")
        r = promptgarden.compare_variants(self.garden)
        self.assertIn("v2", r["summary"]["incomplete_coverage"])

    def test_single_variant_is_not_comparable(self):
        g = {"inputs": ["i1"], "variants": {"v1": {"runs": {"i1": "x"}}}}
        r = promptgarden.compare_variants(g)
        self.assertFalse(r["comparable"])

    def test_prompt_diff_shows_changed_blocks(self):
        r = promptgarden.compare_variants(self.garden)
        d = r["prompt_diffs"][0]
        self.assertEqual(d["blocks_changed"]["changed_count"], 1)
        self.assertIn("你是客服", d["blocks_changed"]["added"])

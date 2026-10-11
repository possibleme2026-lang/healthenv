"""Mutation tests prove the README parity guard can fail for real drift."""

from __future__ import annotations

import unittest
from pathlib import Path

from check_readme_i18n import validate_texts

ROOT = Path(__file__).resolve().parents[1]
EN = (ROOT / "README.md").read_text(encoding="utf-8")
ZH = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")


class ReadmeGuardTests(unittest.TestCase):
    def test_control_passes(self) -> None:
        self.assertEqual(validate_texts(EN, ZH), [])

    def test_deleted_section_is_caught(self) -> None:
        mutated = ZH.replace("## 引用", "引用", 1)
        self.assertIn("heading level structure differs", validate_texts(EN, mutated))

    def test_deleted_table_row_is_caught(self) -> None:
        mutated = ZH.replace("| Runtime 外部依赖 | 0 |\n", "", 1)
        self.assertIn("table row count differs", validate_texts(EN, mutated))

    def test_changed_command_is_caught(self) -> None:
        mutated = ZH.replace("--port 8765", "--port 9999", 1)
        self.assertIn("bash command blocks differ", validate_texts(EN, mutated))

    def test_dead_link_shape_is_caught(self) -> None:
        mutated = ZH.replace("docs/TASK_IR.md", "docs/MISSING.md", 1)
        self.assertIn("relative link counts differ", validate_texts(EN, mutated))


if __name__ == "__main__":
    unittest.main()

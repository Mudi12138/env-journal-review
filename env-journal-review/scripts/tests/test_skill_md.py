"""SKILL.md stays loadable: agent hosts reject or truncate a description over 1,024 characters."""
import re
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "SKILL.md"


class SkillFile(unittest.TestCase):
    def test_frontmatter(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        front = text.split("---\n")[1]
        name = re.search(r"^name:\s*(\S+)\s*$", front, re.M).group(1)
        desc = re.search(r'^description:\s*"(.*)"\s*$', front, re.M).group(1)
        self.assertEqual(name, SKILL.parent.name)
        self.assertRegex(name, r"^[a-z0-9-]{1,64}$")
        self.assertLessEqual(len(desc), 1024)


if __name__ == "__main__":
    unittest.main()

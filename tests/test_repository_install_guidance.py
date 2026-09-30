import shlex
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryInstallGuidanceTests(unittest.TestCase):
    def test_readmes_install_only_the_core_skill_subtree(self) -> None:
        source = "https://github.com/YinXiaoyu-1998/smedc-mcp-skill.git"
        destination = "~/.agents/skills/smedc-mcp"
        for name in ("README.md", "README.zh.md"):
            with self.subTest(readme=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                commands = [
                    shlex.split(line) for line in text.splitlines()
                    if line.startswith(("git clone ", "cp "))
                ]
                clones = [args for args in commands if args[:3] == ["git", "clone", source]]
                self.assertEqual(len(clones), 1)
                self.assertEqual(len(clones[0]), 4)
                checkout = clones[0][3].rstrip("/")
                self.assertNotEqual(checkout, destination)
                self.assertIn(
                    ["cp", "-R", f"{checkout}/skills/smedc-mcp", destination], commands
                )


if __name__ == "__main__":
    unittest.main()

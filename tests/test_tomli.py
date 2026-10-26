import json
import sys
import unittest

from support import REPO

VENDOR = REPO / "third_party" / "tomli"
FILES = ("LICENSE", "__init__.py", "_parser.py", "_re.py", "_types.py", "py.typed")


def vendored():
    """Import the vendored parser the way the engine will: the third_party folder on the path."""
    sys.path.insert(0, str(REPO / "third_party"))
    try:
        import tomli
        return tomli
    finally:
        sys.path.remove(str(REPO / "third_party"))


class VendoredTomli(unittest.TestCase):
    def test_the_upstream_copy_is_complete(self):
        for name in FILES:
            with self.subTest(file=name):
                self.assertTrue((VENDOR / name).is_file(), name)

    def test_the_parser_reads_toml(self):
        tomli = vendored()
        doc = 'model = "gpt-5"\nthreads = 8\n\n[profile]\nenabled = true\n'
        self.assertEqual(tomli.loads(doc),
                         {"model": "gpt-5", "threads": 8, "profile": {"enabled": True}})

    def test_the_parser_reads_guide_text(self):
        tomli = vendored()
        guide = 'One "quoted" line and unicode \u03b5.\nA second line.\n'
        doc = 'developer_instructions = """\n' + guide + '"""\n'
        self.assertEqual(tomli.loads(doc), {"developer_instructions": guide})

    def test_provenance_and_notice_record_the_parser(self):
        components = json.loads((REPO / "third_party" / "provenance.json").read_text())["components"]
        entry = next((c for c in components if c.get("name") == "tomli"), None)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["licence"], "MIT")
        self.assertTrue((REPO / entry["licence_file"]).is_file())
        self.assertIn("tomli", (REPO / "NOTICE").read_text())


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# scar: 2026-10-16 — a router tested only against cases written after the script is policy by assertion.
# fixtures/routing/cases.json is plain JSON and cannot carry a comment; its cases are the ones this file runs.
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "route_risk.py"
CASES = json.loads((HERE / "fixtures/routing/cases.json").read_text())
CASES_52 = json.loads((HERE / "fixtures/routing/cases-5.2.json").read_text())
ALL_CASES = CASES["cases"] + CASES_52["cases"]
DOC = HERE.parent / "references/review-routing.md"
ROUTES = ["bounded-review", "deep-review", "escalate"]


def route(changes):
    result = subprocess.run([sys.executable, "-I", str(SCRIPT)], input=json.dumps({"changes": changes}),
                            capture_output=True, text=True, timeout=30)
    return result


class RouteRiskTest(unittest.TestCase):
    def test_every_fixture_case_routes_as_written_before_the_script_existed(self):
        self.assertEqual(CASES["routes"], ROUTES)
        for case in ALL_CASES:
            with self.subTest(case=case["name"]):
                result = route(case["changes"])
                self.assertEqual(result.returncode, 0, result.stderr)
                out = json.loads(result.stdout)
                self.assertEqual(out["route"], case["expect"], out)

    def test_every_route_carries_its_reasons(self):
        for case in ALL_CASES:
            with self.subTest(case=case["name"]):
                out = json.loads(route(case["changes"]).stdout)
                self.assertTrue(out["reasons"], "a route without a recorded reason cannot be audited")
                for reason in out["reasons"]:
                    self.assertTrue(reason["rule"] and reason["route"] in ROUTES)

    def test_no_route_approves_or_merges_anything(self):
        for case in ALL_CASES:
            with self.subTest(case=case["name"]):
                out = json.loads(route(case["changes"]).stdout)
                self.assertEqual(sorted(out), ["action", "reasons", "route"])
                self.assertEqual(out["action"], "route-only")
                self.assertIn(out["route"], ROUTES)
        self.assertFalse([r for r in ROUTES if re.search(r"approve|merge", r)])

    def test_the_lowest_route_is_still_a_review_never_an_approval(self):
        out = json.loads(route([{"path": "docs/usage.md", "added": ["typo"]}]).stdout)
        self.assertEqual(out["route"], "bounded-review")
        self.assertEqual(out["action"], "route-only")

    def test_a_rename_is_judged_on_both_paths(self):
        out = json.loads(route([{"path": "src/session.js", "old_path": "src/auth/session.js", "added": []}]).stdout)
        self.assertEqual(out["route"], "escalate")
        self.assertIn("src/auth/session.js", json.dumps(out["reasons"]))

    def test_a_malformed_request_never_defaults_to_the_lowest_route(self):
        for payload in ("", "not json", "[]", '{"changes": "x"}', '{"changes": [{"path": 7}]}',
                        '{"changes": [{"path": "a", "added": "x"}]}', '{"changes": [{"old_path": "a"}]}'):
            with self.subTest(payload=payload):
                result = subprocess.run([sys.executable, "-I", str(SCRIPT)], input=payload,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertNotIn("bounded-review", result.stdout)

    def test_an_unknown_change_field_is_refused_not_ignored(self):
        for change in ({"path": "src/a.py", "delete": ["if user.permission: go()"]},
                       {"path": "src/a.py", "removed": "if user.permission: go()"},
                       {"path": "src/a.py", "removed": [7]},
                       {"path": "src/a.py", "extra": []}):
            with self.subTest(change=change):
                result = route([change])
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertNotIn("bounded-review", result.stdout)

    def test_removed_lines_are_scanned_exactly_like_added_lines(self):
        for line in ("if user.permission: process(order)", "require_permission(user)", "@csrf_exempt", "return True  # login"):
            with self.subTest(line=line):
                added = json.loads(route([{"path": "src/orders/p.py", "added": [line]}]).stdout)["route"]
                removed = json.loads(route([{"path": "src/orders/p.py", "removed": [line]}]).stdout)["route"]
                self.assertEqual((added, removed), ("escalate", "escalate"))
        quiet = json.loads(route([{"path": "src/orders/p.py", "added": ["x = 1"], "removed": ["x = 2"]}]).stdout)
        self.assertEqual(quiet["route"], "bounded-review")

    def test_identifiers_are_split_into_words(self):
        sys.path.insert(0, str(HERE))
        import route_risk
        for text, expected in (("require_permission", ["require", "permission"]), ("checkAuth", ["check", "auth"]),
                               ("verifyJWTSignature", ["verify", "jwt", "signature"]), ("data-require-auth", ["data", "require", "auth"]),
                               ("OAuth2", ["o", "auth2"]), ("is_admin", ["is", "admin"])):
            with self.subTest(text=text):
                self.assertEqual(route_risk.words(text), expected)

    def test_each_vocabulary_word_escalates_on_its_own_in_content_and_in_a_path(self):
        lines = {"login": "do_login(request)", "logout": "logout_all()", "session": "reset_session()",
                 "jwt": "decode_jwt(raw)", "csrf": "csrf_check = off", "cors": "cors_origins = ()",
                 "sso": "sso_redirect(url)", "saml": "saml_assertion(xml)", "oidc": "oidc_discovery(url)",
                 "sudo": "sudo_run(cmd)", "privilege": "raise_privilege()", "verify_signature": "verify_signature(blob)"}
        for word, line in lines.items():
            with self.subTest(word=word, where="content"):
                out = json.loads(route([{"path": "src/format/date.py", "added": [line]}]).stdout)
                self.assertEqual(out["route"], "escalate", out)
            with self.subTest(word=word, where="path"):
                out = json.loads(route([{"path": f"src/{word}/handler.py", "added": ["x = 1"]}]).stdout)
                self.assertEqual(out["route"], "escalate", out)

    def test_a_word_that_merely_contains_a_vocabulary_word_is_not_a_match(self):
        for line in ('director = "scorsese"', "pseudo_code = render(value)", "sessionless = True", "ssoup = cook()"):
            with self.subTest(line=line):
                out = json.loads(route([{"path": "src/format/date.py", "added": [line]}]).stdout)
                self.assertEqual(out["route"], "bounded-review", out)

    def test_the_reference_states_the_input_contract_and_the_vocabulary(self):
        text = DOC.read_text()
        for needle in ("Pass both sides of every hunk", "Incomplete change evidence must never select a lower route",
                       "refused (exit 2)", '"removed"'):
            self.assertIn(needle, text)
        for word in ("login", "logout", "session", "JWT", "CSRF", "CORS", "SSO", "SAML", "OIDC", "sudo", "privilege",
                     "verify_signature"):
            self.assertIn(word, text, f"{word} is routed by the script but not listed in review-routing.md")

    def test_the_reference_table_names_every_rule_the_script_applies(self):
        text = DOC.read_text()
        rules = set(re.findall(r'^    \("([a-z-]+)", "', SCRIPT.read_text(), re.M))
        self.assertTrue(len(rules) >= 8, rules)
        for rule in sorted(rules):
            self.assertIn(f"`{rule}`", text, f"{rule} is applied by the script but missing from review-routing.md")
        for name in ROUTES:
            self.assertIn(f"`{name}`", text)
        self.assertIn("never approves", text)


if __name__ == "__main__":
    unittest.main()

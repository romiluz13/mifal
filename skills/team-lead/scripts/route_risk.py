#!/usr/bin/env python3
"""Route a change to a review depth. Reads {"changes": [{"path", "old_path"?, "added"?: [lines], "removed"?: [lines]}]} on
stdin and prints {"route", "reasons", "action"}. Callers pass both sides of every hunk: the content rules scan the added
and the removed lines. Unknown change fields are refused. It only routes: no route approves or merges, and anything it
cannot place goes upward. The rule table is documented in references/review-routing.md; keep the two in step (a test
checks it).
<!-- scar: 2026-10-16 — a change to instructions or tests that is called docs-only or tests-only excludes its effect on the gate -->
<!-- scar: 2026-10-16 — a deleted guard, a snake_case or camelCase guard and common auth words (jwt, csrf, login) routed to the lowest review -->
"""
import json
import re
import sys
from pathlib import PurePosixPath

ROUTES = ["bounded-review", "deep-review", "escalate"]
CODE = {".py", ".js", ".ts", ".go", ".rs", ".java", ".rb"}
AUTH_WORDS = (r"auth\w*|oauth|permission\w*|acl|rbac|secrets?|credentials?|login|logout|sessions?|jwt|csrf|cors|sso|saml|"
              r"oidc|sudo|privileges?|privileged")
CONTENT_WORDS = AUTH_WORDS + r"|role|is_?admin|admin|token|password|grant|owner\w*"
AUTH_CONTENT = re.compile(r"\b(" + CONTENT_WORDS + r")\b", re.I)
PATH_WORD = re.compile(AUTH_WORDS)
CONTENT_WORD = re.compile(CONTENT_WORDS)
CAMEL = [(re.compile(r"([a-z0-9])([A-Z])"), r"\1 \2"), (re.compile(r"([A-Z]+)([A-Z][a-z])"), r"\1 \2")]
CHANGE_FIELDS = {"path", "old_path", "added", "removed"}
LOCKFILES = {"package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "pyproject.toml", "poetry.lock",
             "uv.lock", "cargo.toml", "cargo.lock", "go.mod", "go.sum", "gemfile", "gemfile.lock"}


def words(text):
    """The lower-case words of the identifiers in text: snake_case, kebab-case, camelCase and PascalCase are split."""
    for pattern, replacement in CAMEL:
        text = pattern.sub(replacement, text)
    return re.findall(r"[a-z0-9]+", text.lower())


def auth_words(text, vocabulary):
    """True when a whole word of the text, or the phrase verify_signature, is in the vocabulary."""
    found = words(text)
    return any(vocabulary.fullmatch(word) for word in found) or "verify signature" in " ".join(found)


def parts(path):
    return [p.lower() for p in PurePosixPath(path).parts]


def name(path):
    return PurePosixPath(path).name.lower()


def is_self_policy(path, lines):
    p = path.lower()
    return (name(path) in {"codeowners", "review-routing.md", "route_risk.py", "test_route_risk.py"} or
            "fixtures/routing/" in p or "/receiving-code-review/" in "/" + p or "/security-review/" in "/" + p)


def is_auth_path(path, lines):
    return (bool(re.search(r"(^|[/_.-])(" + AUTH_WORDS + r")([/_.-]|$)", path, re.I)) or
            auth_words(path, PATH_WORD))


def is_auth_content(path, lines):
    return any(AUTH_CONTENT.search(line) or auth_words(line, CONTENT_WORD) for line in lines)


def is_policy_doc(path, lines):
    p = parts(path)
    return (name(path) in {"skill.md", "agents.md", "claude.md", "agreement.md"} or
            bool({"skills", ".claude", ".agents", "roles", "references"} & set(p)))


def is_oracle(path, lines):
    n = name(path)
    return (bool({"tests", "test", "spec", "specs", "__tests__", "fixtures"} & set(parts(path))) or
            n.startswith("test_") or re.search(r"(_test|\.test|\.spec)\.", n) is not None or
            re.search(r"verif|oracle|conformance|check_", n) is not None)


def is_ci(path, lines):
    p = path.lower()
    return (p.startswith(".github/workflows/") or p.startswith(".circleci/") or
            name(path) in {".gitlab-ci.yml", "jenkinsfile"})


def is_hook(path, lines):
    return bool({"hooks", ".husky"} & set(parts(path)))


def is_dependency(path, lines):
    return name(path) in LOCKFILES or re.fullmatch(r"requirements[\w.-]*\.txt", name(path)) is not None


def is_plain_doc(path, lines):
    p = parts(path)
    return bool(p) and (p[0] == "docs" or name(path).startswith("readme")) and name(path).endswith(".md")


def is_plain_source(path, lines):
    p = parts(path)
    return bool(p) and p[0] in {"src", "lib"} and PurePosixPath(path).suffix.lower() in CODE


# (rule id, route, test). The highest route among the matching rules wins; no match is `unresolved`.
RULES = [
    ("self-policy", "escalate", is_self_policy),
    ("auth-path", "escalate", is_auth_path),
    ("auth-content", "escalate", is_auth_content),
    ("policy-doc", "deep-review", is_policy_doc),
    ("test-oracle", "deep-review", is_oracle),
    ("ci", "deep-review", is_ci),
    ("hook", "deep-review", is_hook),
    ("dependency", "deep-review", is_dependency),
    ("plain-doc", "bounded-review", is_plain_doc),
    ("plain-source", "bounded-review", is_plain_source),
]
UNRESOLVED = ("unresolved", "deep-review")


def judge(change):
    paths = [change["path"]] + ([change["old_path"]] if change.get("old_path") else [])
    reasons = []
    for path in paths:
        lines = change.get("added", []) + change.get("removed", [])
        hit = [(rule, to) for rule, to, test in RULES if test(path, lines)]
        if not hit:
            hit = [UNRESOLVED]
        reasons += [{"path": path, "rule": rule, "route": to} for rule, to in hit]
    top = max(ROUTES.index(r["route"]) for r in reasons)
    return [r for r in reasons if ROUTES.index(r["route"]) == top]


def route(changes):
    if not changes:
        return {"route": "deep-review", "reasons": [{"path": "", "rule": "unresolved", "route": "deep-review"}],
                "action": "route-only"}
    reasons = [r for change in changes for r in judge(change)]
    top = max(ROUTES.index(r["route"]) for r in reasons)
    return {"route": ROUTES[top], "reasons": [r for r in reasons if ROUTES.index(r["route"]) == top],
            "action": "route-only"}


def valid(request):
    changes = request.get("changes") if isinstance(request, dict) else None
    return isinstance(changes, list) and all(
        isinstance(c, dict) and set(c) <= CHANGE_FIELDS and isinstance(c.get("path"), str) and c["path"] and
        (c.get("old_path") is None or isinstance(c["old_path"], str)) and
        all(isinstance(c.get(side, []), list) and all(isinstance(line, str) for line in c.get(side, []))
            for side in ("added", "removed"))
        for c in changes)


def main():
    try:
        request = json.loads(sys.stdin.read())
    except ValueError:
        request = None
    if not valid(request):
        print("route_risk: expected {\"changes\": [{\"path\": str, \"old_path\"?: str, \"added\"?: [str], \"removed\"?: [str]}]}; "
              "no other change field", file=sys.stderr)
        return 2
    print(json.dumps(route(request["changes"]), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

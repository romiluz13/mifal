# Review routing

Read when you assign review for a change, or when a change touches a skill, a test, a hook, CI, a permission or this
file. The router picks a review depth. It does not review, and it never approves.

<!-- scar: 2026-10-16 — calling instruction or test changes docs-only or tests-only excludes their effect on the gate -->

## Routes

| Route | What it means |
|---|---|
| `bounded-review` | One independent reviewer who is not the builder, with the diff and the requirement. |
| `deep-review` | The above, plus an independent expected outcome and a negative control for a consequential fix ([communication](communication.md#acceptance-evidence)), and the lead opens the decisive artifact. |
| `escalate` | The above, plus a second independent reviewer, and the human decides whatever policy, access or ownership is at stake (human-reserved stays human-reserved). |

Every change gets at least a bounded independent review. Risk sets the depth and the owner. **Routing is not
approval**: no route approves or merges, and no route lowers the independent-review requirement of an authorized round.
A bot identity and a log are not independent review.

## Rules

The highest route among the matching rules wins. A path that no rule places is `unresolved`, and an unclear case goes
up, never down. A rename is judged on both paths. A change list that is empty is `unresolved`.

| Rule | Matches | Route |
|---|---|---|
| `self-policy` | this routing reference, the router and its fixtures, `CODEOWNERS`, `receiving-code-review`, `security-review` | `escalate` |
| `auth-path` | a path with an auth, permission, ACL, RBAC, secret, credential, login, logout, session, JWT, CSRF, CORS, SSO, SAML, OIDC, sudo or privilege component; snake_case, camelCase and kebab-case names are split into words | `escalate` |
| `auth-content` | an added or a removed line that mentions any `auth-path` word, or role, admin, token, password, grant or owner, in any file; identifiers are split into words, so `require_permission`, `checkAuth` and `verify_signature` match | `escalate` |
| `policy-doc` | skill, `AGENTS.md`, `CLAUDE.md`, agreement and role or brief Markdown; anything under `skills/`, `.claude/`, `.agents/`, `roles/`, `references/` | `deep-review` |
| `test-oracle` | tests, specs, fixtures, verifiers and checkers: they decide what passes | `deep-review` |
| `ci` | CI workflows | `deep-review` |
| `hook` | hook scripts | `deep-review` |
| `dependency` | manifests and lockfiles | `deep-review` |
| `plain-doc` | `docs/**/*.md` and a README | `bounded-review` |
| `plain-source` | source files under `src/` or `lib/` with no stricter rule | `bounded-review` |
| `unresolved` | everything else | `deep-review` |

Skill and workflow Markdown, test oracles and one-line auth or ownership edits are consequential whatever their
extension or size, because agents and gates follow them. Calling such a change "docs-only" or "tests-only" is the
fail-open this table exists to close.

## Input

Each change is `{"path", "old_path"?, "added"?, "removed"?}`: the file, its old path for a rename, and the lines added and
removed. **Pass both sides of every hunk.** The content rules scan the added and the removed lines, because a deleted
guard has no added lines. Any other field is refused (exit 2), so a misspelled key cannot silently drop a signal.

**Incomplete change evidence must never select a lower route.** The router cannot tell an omitted `removed` list from a
change that removed nothing; the caller owns that. When you cannot give both sides of a hunk (a binary file, a
truncated diff, only a file list), do not take `bounded-review`: route the change at least `deep-review` and say why in
the task record.
<!-- scar: 2026-10-16 — the removed guard was the only auth signal and the router could not be given it -->

## Use

```sh
echo '{"changes": [{"path": "tests/test_billing.py", "added": ["assert total == 90.00"], "removed": ["assert total == 100.00"]}]}' \
  | python3 -I scripts/route_risk.py
```

The output is `{"route", "reasons", "action": "route-only"}`. Record the route and its reasons in the task record
before dispatching the review; do not reword the route to something milder. A repository may add rules or raise a
route in its agreement. It may not lower one. `CODEOWNERS` only requests review: enforcement needs the repository's
protected-branch or ruleset setting, so check the actual setting before you claim it.

Limits: paths and keywords only, so a change that hides its effect in an ordinary file can be underrated; an
unlisted language or layout is `unresolved` and goes up; an auth effect hidden behind names with none of the listed words is
not seen. The fixtures are `scripts/fixtures/routing/cases.json` and `cases-5.2.json`.

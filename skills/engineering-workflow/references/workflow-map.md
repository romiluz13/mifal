# Workflow map

Ask Matt body: sha256:bbc34195f40f44231e3595cf662362797bcceb8111ea6f77751087af26ad0e25

A hand-written table of the shipped skills: where each one runs, who invokes it, by what path, what it needs and what evidence shows it ran. It is not a router. Ask Matt (`skills/ask-matt/SKILL.md`) stays the only branch map, no row here decides a branch, and none of Matt's text is copied. `validate_contracts.py` reads this file at every Matt gate.

## Keeping it true

The `Ask Matt body:` line pins the Ask Matt body this map was reviewed against. When the installed body differs, every Matt gate holds with a message naming this map. To clear it, read the new Ask Matt body, fix the rows that no longer match, then replace the digest with the one that `validate_contracts.py read ~/.agents/skills/ask-matt/SKILL.md` prints in its footer.

The same check refuses a map that omits a shipped skill, lists one that is not shipped, or places a skill the wrong way:

- **Ask Matt rows** hold only skills that the installed Ask Matt body names as `/skill`. The Anchor says where Ask Matt places the skill.
- **Local attachments** attach to an Ask Matt row by name. They add a specialist at a phase, never a branch.
- **Factory section** holds what Ask Matt does not name: the factory core, and the starts Ask Matt does not cover.

It also refuses a map with a repeated authoritative section, or with more tables than its four. Both are read the way GitHub-flavored Markdown reads them: a heading is ATX (up to 3 spaces of indent, an optional closing `#` run) or setext (`===` or `---` underline), matched without regard to case or level; a table is any delimiter row outside a fence, with or without outer pipes, one or more hyphens per cell and up to 3 spaces of indent. Headings and tables written as raw HTML, or nested in a blockquote or a list item, are not recognised. The check covers structure, coverage, category and body freshness. It does not show that a row's prose matches Ask Matt or describes what the skill does; a reviewer reads the rows against the installed body.

Columns: Route and phase also decides which step's start Check a body's read is held against (the steps are in the phase record, 'Only the human cuts; reads come before the work'). Route and phase uses the route words of the engineering-workflow route table (research, plan, build, debug, review), plus `all` and `standalone`. Invoker is the lead (a solo agent counts as the lead) or a worker by brief. Evidence is what a gate or a reviewer can check; a `Loaded:` line records a read declaration and a hash, never that the skill was retrieved completely or applied. Anything not listed here is not shipped; the steward inventory discovers it from the user's own library.

## Ask Matt rows

| Skill | Route and phase | Invoker | Invocation path | Dependencies | Evidence | Anchor |
|---|---|---|---|---|---|---|
| ask-matt | all: scope (entry; picks the procedure for the active phase) | lead; a worker only when its brief lists it | engineering-workflow Required entry step 2; brief `Procedure:` line | the skills it routes to | `Procedure:` and `Loaded:` lines in the lead's record (the validator requires both); a worker brief under that record leaves them out | ask-matt: this body |
| grill-with-docs | plan: resolve (main flow step 1, in a working directory) | lead; the griller worker by brief when the lead's plan is grilled | Skill tool (lead); brief `Procedure:` line | grilling, domain-modeling | `Grilling:` line; `Procedure:` and `Loaded:` for grill-with-docs, grilling and domain-modeling; at accepted, the plan artifact pinned by digest with `## Accepted scope` and `## Design decisions` | ask-matt: main flow step 1 |
| grill-me | plan: resolve (main flow step 1, with no working directory) | lead | Skill tool (lead); brief `Procedure:` line | grilling | `Grilling:` line; `Procedure:` and `Loaded:` for grill-me and grilling | ask-matt: Standalone |
| grilling | plan: resolve (the interview primitive under every grill wrapper; triage, wayfinder and improve-codebase-architecture also run it; used directly only when you want the interview with no wrapper around it) | lead, through a wrapper or directly; the griller worker by brief | the wrapper's own Skill tool call; or a direct Skill tool call or brief `Procedure:` line | no dependencies | `Loaded:` line (the validator requires it with the wrapper, and in a griller task at `Grilling: accepted`) | ask-matt: Standalone |
| domain-modeling | plan: resolve (driven by grill-with-docs; or used directly when the words, not the process, are the problem) | lead, through grill-with-docs; the lead or a worker (by brief) directly | the wrapper's own Skill tool call; or a direct Skill tool call or brief `Procedure:` line | no dependencies | `Loaded:` line; edits to GLOSSARY.md and ADRs when the interview settles a term or a hard-to-reverse decision | ask-matt: Vocabulary underneath |
| prototype | plan: resolve (the detour in main flow step 2, when a question needs a runnable answer) | lead | Skill tool (lead), in a fresh session after a handoff | no dependencies | the throwaway program on its `prototype/NAME` branch, pointed at from the implementation ticket | ask-matt: main flow step 2 |
| handoff | all: any phase boundary (the bridge to and from a prototype; a new harness, directory or colleague) | lead | Skill tool (lead) | no dependencies | the handoff Markdown file, named in the next session's brief | ask-matt: main flow step 2 |
| to-spec | plan: plan (main flow step 3, when the build is multi-session) | lead | Skill tool (lead), in the grilling context | no dependencies | the spec on the configured tracker (local form: `.scratch/FEATURE/spec.md`); `Loaded:` line | ask-matt: main flow step 3 |
| to-tickets | plan: plan (main flow step 3, after to-spec) | lead | Skill tool (lead), in the grilling context | no dependencies | the tickets on the configured tracker (local form: one file per ticket under `.scratch/FEATURE/issues/`, each with `Blocked by:`); `Loaded:` line | ask-matt: main flow step 3 |
| implement | build: implement (main flow step 3: right here, in the same context window, on a single-session build; on a multi-session build, one ticket per worker with context cleared between tickets) | lead, on a single-session build; worker (by brief), one ticket each, on a multi-session build | Skill tool in the current context window (lead); brief `Procedure:` line (worker); the validator requires implement and tdd at a behavioral build implement phase unless `Implement: n/a:` is declared | tdd, code-review | `Loaded:` lines; the commit named in the receipt; `Check:` lines | ask-matt: main flow step 3 |
| implement-spec | build: implement (the whole spec in one run, parallel across the ticket frontier) | lead (scheduler) | Skill tool (lead) when parallel execution is authorized; brief `Procedure:` line for each implementer | tdd, code-review | `Scheduler:` and `Integration owner:` lines; the integration branch; one code-review over it | ask-matt: main flow step 3 |
| tdd | build: implement and remediate | lead, directly or through implement (on its own, without a full spec); worker (by brief) | Skill tool (lead); implement calls it; brief `Procedure:` line (worker) | codebase-design | `Loaded:` line; the red-then-green tests named in the receipt Claims | ask-matt: main flow step 3 |
| code-review | build and debug: review; review: review | lead, directly (on its own, against a fixed point) or through implement; worker (by brief) | Skill tool (lead); implement calls it; brief `Procedure:` line (worker); the validator requires it at the review and accept gates | no dependencies | `Loaded:` line; `Snapshot:` pinned by review-snapshot; findings, each with a location, a trigger and a consequence | ask-matt: main flow step 3 |
| pr | build: report (when the work goes up as a pull request) | lead or worker, whoever writes the PR body | model-invoked (Ask Matt: the agent reaches for it whenever it writes a PR) | no dependencies | the PR body with its visual, its before-and-after evidence and its one-way or two-way door call; opening or pushing the PR stays a reserved action | ask-matt: main flow step 3 |
| retro | build and debug: retro | lead (one parent retrospective closes a coordinated build) | engineering-workflow Build and Debug rows; brief `Procedure:` line | writing-for-agents | `Retro:` line pinned by digest to a report with `## Sources` and `## Findings`; the `Check:` line for retro; `Loaded:` lines for retro and writing-for-agents | ask-matt: main flow step 4 |
| triage | plan: scope (an on-ramp for incoming issues and external pull requests you did not create) | lead | Skill tool (lead) | grilling, domain-modeling | agent-ready issues on the tracker, each with its triage state; `Loaded:` line | ask-matt: On-ramps |
| diagnosing-bugs | debug: reproduce, hypothesis, diagnose and fix | worker (by brief) | brief `Procedure:` line; the validator requires it in those phases | no dependencies | `Loaded:` line; the failing one-command loop; the regression test; a retro after the fix | ask-matt: On-ramps |
| wayfinder | plan: scope and resolve (a foggy effort too big for one session) | lead | Skill tool (lead) | grilling, domain-modeling, research, prototype | the shared map of decision tickets on the tracker; it hands off at to-spec | ask-matt: On-ramps |
| improve-codebase-architecture | plan: inspect (the upkeep survey of deepening opportunities) | lead | Skill tool (lead) | codebase-design, grilling, domain-modeling | the visual HTML report; the chosen opportunity continues at grill-with-docs | ask-matt: Codebase health |
| codebase-design | all: reference vocabulary for design, loaded by tdd and improve-codebase-architecture, or used directly when the shape of a module is the problem | lead or worker (by brief), directly or through tdd or improve-codebase-architecture | a direct Skill tool call or brief `Procedure:` line; otherwise called by those skills | no dependencies | `Loaded:` line when a design question arises | ask-matt: Vocabulary underneath |
| research | research: investigate (also the research phase before a plan or a build) | lead delegates the reading to a worker by brief | Skill tool (lead); brief `Procedure:` line | no dependencies | the cited Markdown file in the repository, with dated primary sources | ask-matt: Standalone |
| to-questionnaire | plan: resolve (when the missing answer sits with someone else) | lead | Skill tool (lead) | no dependencies | the questionnaire file sent to its recipient; the answers feed grill-with-docs or to-spec | ask-matt: Standalone |
| wizard | build: implement (steps only a human can take: credentials, dashboards, cutovers) | lead hands the script to the human | model-invoked when the agent reaches a step only the human can pass | no dependencies | the generated wizard script and the human's own completion of each step | ask-matt: Standalone |
| wait-what | all: any phase in which a message did not land | lead | Skill tool (lead), when the human says the message did not land | no dependencies | the re-pitched message in plain words | ask-matt: Standalone |
| teach | standalone: a learning workspace over several sessions | lead, on the human's request | Skill tool (lead) | no dependencies | the workspace files in the current directory | ask-matt: Standalone |
| writing-for-agents | standalone (also build and debug: retro, where it is loaded with retro) | lead or worker (by brief) | Skill tool; brief `Procedure:` line with retro | no dependencies | `Loaded:` line (the validator requires it with retro) | ask-matt: Standalone |
| setup-matt-pocock-skills | plan: scope (the precondition before the first engineering flow in a repository) | lead | Skill tool (lead) | no dependencies | the repository's docs/agents files for tracker, triage labels and domain layout | ask-matt: Precondition |

## Local attachments

| Skill | Route and phase | Invoker | Invocation path | Dependencies | Evidence | Anchor |
|---|---|---|---|---|---|---|
| receiving-code-review | build and debug: remediate (when review findings come back) | worker (by brief) | brief `Procedure:` line | no dependencies | `Loaded:` line; each finding checked against the code before it is applied | attaches: code-review |
| ddd | all: only when DDD applies | lead selects; worker loads by brief | brief `Procedure:` line; the validator requires it with the current phase body when `DDD: applies:` is recorded | the DDD phase body for the current phase | `DDD: applies:` line; `Loaded:` lines for ddd and the phase body | attaches: research, grill-with-docs, code-review |
| ddd-scope | all: the research, context, source, investigate, inspect and reproduce phases, when DDD applies | worker (by brief) | brief `Procedure:` line | ddd | `Loaded:` line; the official-documentation findings cited in the plan | attaches: research |
| ddd-ground | all: the plan, resolve and hypothesis phases, when DDD applies | lead or worker (by brief) | brief `Procedure:` line | ddd | `Loaded:` line; decisions cited to their sources in the plan | attaches: grill-with-docs |
| ddd-verify | all: the review, verify, regression, substantiate, retro, report and deliver phases, when DDD applies | worker (by brief) | brief `Procedure:` line | ddd | `Loaded:` line; the finished code compared with its cited sources | attaches: code-review |
| frontend-design | build and debug: plan and review, when the change touches a user journey, visual direction or interaction | worker (by brief) | brief `Procedure:` line, with the ux-acceptance reference; the validator requires the reference when `UX: applies:` is recorded | no dependencies | `UX: applies:` line; `Loaded:` lines for frontend-design and `team-lead/references/ux-acceptance.md`; the journey walkthrough in the receipt | attaches: grill-with-docs, code-review |
| agent-browser | build and debug: verify (exercises the affected journey in a real browser) | worker (by brief) | brief `Procedure:` line; for a discovery stub, also load the installed CLI's workflow guide before running browser commands | the installed agent-browser CLI and its workflow guide | `Loaded:` line; the traced steps and observed results in the receipt | attaches: code-review |

## Factory section

Starts and parts that Ask Matt does not name. Nothing here claims an Ask Matt branch.

### Factory core

| Skill | Route and phase | Invoker | Invocation path | Dependencies | Evidence | Anchor |
|---|---|---|---|---|---|---|
| engineering-workflow | all: every phase (the ordered route table and the gates) | lead; every worker by brief | the per-harness entry pointer; brief `Procedure:` line | ask-matt, team-lead, code-review, ddd, ddd-scope, ddd-ground, ddd-verify | `Procedure:` and `Loaded:` lines in every Matt record; the Phase checklist; the `workflow` gate runs | factory: the common execution contract |
| team-lead | all: coordination (assign, dispatch, accept) | lead | Skill tool (lead); `Implement: n/a: coordination:` requires its `Loaded:` line | herdr-adapter, validate-contracts, and the herdr skill when Herdr is the channel | the `Implement:` line; `Loaded:` line; one brief and one receipt per task | factory: team coordination |
| herdr-adapter | all: dispatch, resume and acceptance of Matt tasks | lead | the `tools/herdr_adapter` command line; its task JSON carries the Workflow keys into the brief | validate-contracts | its journal and task state, the doorbell lines and a receipt per attempt | factory: team coordination |
| validate-contracts | all: the entry, review and accept gates, and the brief and receipt checks | lead and worker | `python3 ~/.agents/skills/team-lead/scripts/validate_contracts.py` with brief, receipt or workflow; the adapter loads it as a module | no dependencies | the exit code and stderr of each run, recorded as `Check:` lines | factory: the gates |
| setup-pre-commit | build: implement (a one-off repository setup, on explicit request) | lead | Skill tool (lead), on request | no dependencies | the hook files in the repository and a passing commit-time run | factory: a Matt skill that Ask Matt does not place |

### Starts Ask Matt does not cover

| Start | Route and phase | Invoker | Invocation path | Dependencies | Evidence | Anchor |
|---|---|---|---|---|---|---|
| operational or one-off task | build: scope through report (the Build row of the route table, unchanged) | lead | engineering-workflow Required entry records Route build; no Ask Matt branch is claimed | engineering-workflow, code-review, retro, and wizard for steps only a human can take | the Workflow record with Route build and the Build row's phase evidence; reserved actions wait for the human's quoted grant | factory: Ask Matt has no start for an agent-doable operational task |
| team coordination | all: coordination (assign, dispatch, accept) | lead | team-lead, with the herdr-adapter or plain briefs | team-lead, herdr-adapter, validate-contracts | the `Implement: n/a: coordination:` line; one brief and one receipt per task; the parent `workflow` gate runs | factory: Ask Matt covers building, not running workers |

## Required steps

The steps each route, and for build each recorded Ask Matt branch, requires, in order. A step is a checklist item whose label, or whose words before the first colon, are the step's name (case, punctuation and a leading "to" do not matter: `- [x] To-spec: done` counts; `- [x] To-spec skipped` does not). The gates read this section: a step before one that is already done, or before the review or accept gate, must show as done on the Phase checklist, or a `Cut:` line must quote the human who cut it. A step still ahead of the record is pending, never a skip. The branch is the record's `Route decision`; it is read from the parent `State:` when the record has none. This restates the route table of engineering-workflow and Ask Matt's main flow; it decides no branch, and Ask Matt stays the only branch map.

- research: scope, source, investigate, synthesize, review, verify
- plan: scope, inspect, resolve, plan, review, verify
- build, multi-session yes: scope, grilling, to-spec, to-tickets, implement, review, retro
- build, multi-session no: scope, grilling, implement, review, retro
- debug: scope, reproduce, hypothesis, diagnose, review, regression, retro
- review: scope, inspect, review, substantiate, verify

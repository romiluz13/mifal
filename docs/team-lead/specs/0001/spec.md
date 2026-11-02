---
spec: 0001
title: Team-lead orchestration over the herdr socket
status: ready-for-agent
decided: 2026-10-05
adrs: [0001-socket-transport, 0002-vocabulary-transport-seam]
prototype: ~/Dev/herdr-socket-proto (VERDICT.md)
---

# Spec 0001 — Team-lead orchestration over the herdr socket

## Problem Statement

I run mixed agent teams in herdr panes and I love watching them work and talk to each
other in the wall of panes. But I am the orchestration layer. By hand, I: type prompts
into panes one at a time, eyeball each pane's state to know who is working or blocked,
remember which agent has which skills and MCPs, chase AGENTS.md compliance myself, and
hold the whole fleet's context in my head. Coordinating by hand is slow, error-prone,
and caps the fleet at the size I can babysit. When I step away, the fleet stalls.

I want a team lead — an agent manager, not a scheduler — that runs the fleet the way my
team-lead skill already describes: briefs with done-means and stop rules, evidence over
reports, coaching, retros. I want it to control the fleet at machine speed without
touching what I see in the panes, to steward skills and configurations instead of me,
and to bring me only the decisions that are actually mine.

## Solution

A team-lead agent, living in a herdr pane of its own, runs a continuous loop over the
herdr socket: it watches member states through event subscriptions (guarded by a polling
floor), dispatches briefs as durable files with visible pane prompts, and receives
doorbell rings (DONE / HELP / HELD / STOPPED) that are both pane messages I can watch
and records any agent can read. Everything above the transport is agent-agnostic
Markdown — briefs, receipts, skill inventory, tool ledger, compliance reports — so any
model can join or leave the fleet and the channel can evolve (plugin, remote) without
rewriting contracts.

The lead is also the fleet's steward: it curates the skill inventory, keeps the tool
ledger current, checks AGENTS.md compliance in tiers (hard lines enforced, conventions
checked, preferences advised), notices capability gaps, and pitches new specialist
recruits to me with a recommendation — I approve, it never hires alone. The panes stay
exactly as they are: the socket is backstage, the wall of panes remains the theater.

## User Stories

### The human

1. As the human, I want to watch my agents work and talk in the panes exactly as I do
   today, so that orchestration never costs me the visibility I love.
2. As the human, I want to hand the lead a mission and walk away, so that the fleet keeps
   making progress without me babysitting panes.
3. As the human, I want the lead to ring *me* only for decisions that are mine
   (approvals, spending, publishing, model changes, hiring), each with a recommendation,
   so that my attention is spent on judgment, not triage.
4. As the human, I want a durable record of everything the lead did on my behalf and why,
   so that no decision dies silently with a session.
5. As the human, I want to interrupt or stop any member or the whole fleet at any time,
   so that I stay in command of my own machines.
6. As the human, I want the lead to notice when the fleet lacks a capability, search the
   skill pool, and pitch me a new specialist with a recommendation, so that growing the
   team is a one-approval action instead of a research project.
7. As the human, I want to pick the default models for roles myself, with the lead able
   to recommend and request exceptions, so that model authority stays with me.
8. As the human, I want tiered AGENTS.md compliance: safety hard lines enforced without
   exception, project conventions checked and reported, style preferences advised only,
   so that enforcement strength matches what each rule actually protects.
9. As the human, I want every inter-agent contract in plain Markdown files under version
   control, so that I can read, diff, and audit the fleet's entire shared brain.
10. As the human, I want the fleet to be model-agnostic and channel-agnostic, so that
    swapping any member — or the whole channel — never rewrites the way the team works.
11. As the human, I want the lead to never type into a pane where I have a half-typed
    draft, so that automation never merges with or submits my text.
12. As the human, I want the lead to never act on a pane it didn't explicitly identify,
    so that a mistyped parameter can never land work in my live workspace (as it did
    during the prototype).
13. As the human, I want unattended runs to carry a pass/fail finish condition and do
    only reversible, authorized work, so that "away" never means "unaccountable".

### The team lead

14. As the team lead, I want member state changes pushed to me as events with a polling
    floor as backup, so that my loop is fast without being fragile.
15. As the team lead, I want socket calls at sub-millisecond latency, so that observing
    and dispatching a large fleet costs effectively nothing.
16. As the team lead, I want to detect a silently dead event stream via watchdog and
    recover by reconnect + resubscribe + snapshot, so that starvation degrades my loop
    instead of freezing it.
17. As the team lead, I want to handle explicit `events_lost` backpressure errors with
    the documented recovery recipe, so that a slow cycle never corrupts my fleet picture.
18. As the team lead, I want briefs to be durable files with stable task ids, latitude,
    done-means, stop rules, and return paths, so that any member can execute them and any
    later reader can audit them.
19. As the team lead, I want delivery proven by receipts (the member's transcript quoting
    the brief, `Closes:` ids, sidecar artifacts) rather than socket return codes, so that
    a timeout never fools me into double-dispatching.
20. As the team lead, I want doorbell rings (DONE / HELP / HELD / STOPPED + task id +
    artifact path) from members, so that I wake exactly when a moment needs me, without
    bare polling.
21. As the team lead, I want corrections to get their own attempt id, so that a late
    `DONE 7` can never close attempt 7.2.
22. As the team lead, I want a curated skill inventory plus member self-reported
    capability briefs, so that I assign by demonstrated fit instead of model reputation.
23. As the team lead, I want a tool ledger of MCPs and connectors per member, so that I
    never brief a task that needs a tool its owner doesn't have.
24. As the team lead, I want role folders with shipped defaults and project overrides,
    so that a new member of a known role onboards in minutes without me re-explaining.
25. As the team lead, I want to check AGENTS.md compliance in tiers and record the
    result, so that enforcement is proportionate and traceable.
26. As the team lead, I want to detect capability gaps against the mission, search the
    skill pool, and pitch a recruit to the human, so that staffing the team is my job,
    hiring is hers.
27. As the team lead, I want to record every decision, recognition, correction, and
    lesson in the team record, so that compaction or restart never costs the fleet its
    memory.
28. As the team lead, I want to reconcile in-flight work against disk and live members
    before dispatching anything on resume, so that I never re-dispatch completed work.
29. As the team lead, I want read-only subscription connections with liveness pings on
    separate connections, so that my own health checks never kill my event streams.
30. As the team lead, I want schema validation of every socket param before sending, so
    that herdr's silent-unknown-param behavior can never mutate my intent.
31. As the team lead, I want member identity checks (ids + cwd + agent name + terminal
    id) before destructive actions, so that pane-id reuse after a server restart never
    aims a close or a prompt at the wrong pane.
32. As the team lead, I want to read member output on state transitions, not
    continuously, so that I never cause the visible flicker or viewport shifts that
    aggressive polling causes. One signature-stable reread per lead turn is authorized
    for a member holding unfinished work, because a transition read can miss a late
    doorbell line still inside the viewport; this is a bounded catch-up read, not
    continuous polling, and members without unfinished work are still read on
    transitions only.

### A member (any model, any kind)

33. As a member, I want my brief as a file I can read at my own pace, so that a long
    context never depends on a pane's scrollback.
34. As a member, I want to ring the doorbell with one line (e.g. `HELP 7 blocked-on
    auth`), so that asking for help costs me nothing and is seen immediately.
35. As a member, I want to self-report my capabilities into the inventory, so that the
    lead assigns me work I'm actually good at.
36. As a member, I want latitude stated in my brief (Look · Propose · Do & tell · Own),
    so that I know exactly what I may decide alone.
37. As a member, I want my role folder to carry my onboarding pointers, so that I start
    productive instead of spending turns discovering the project.
38. As a member, I want a stop rule and an honest-failure contract, so that stopping
    early with evidence is always better than reinterpreting the goal.

### The system itself

39. As a future remote member, I want the contracts to be files and vocabulary, not
    local panes, so that joining from another machine requires only a sync channel.
40. As a future plugin host, I want transport specifics isolated behind the adapter
    seam, so that hosting the lead outside herdr reuses everything above the seam.
41. As the fleet's record, I want one writer per artifact, so that parallel members never
    corrupt the shared brain.
42. As the fleet's record, I want to be version-controlled, so that every stewardship
    change to skills, configs, and inventories is reviewable history.

## Implementation Decisions

### Transport (ADR-0001)

- A **socket adapter** is the lead's only machine control path: NDJSON over the herdr
  socket, one request per connection, subscription connections read-only, liveness pings
  on separate connections. CLI stays for humans and one-off scripts.
- The adapter **schema-validates params** against `herdr api schema --json` before
  sending (herdr silently ignores unknown params and substitutes dangerous defaults).
- **Explicit pane ids always**; a missing injected pane id is a hard error, never a
  fallback to the focused pane.
- **Draft guard** before typing into any pane: agent idle ≥60 s and input box empty on
  two reads ≥10 s apart; unreadable counts as not empty; refuse when a draft exists.
- **Receipts over waits**: prompts are sent without `--wait`; delivery is proven by
  durable receipts. `agent.wait` may be used for settled-state observation only, never as
  proof of delivery.
- Bootstrap order on connect/reconnect: **subscribe → buffer → snapshot → apply buffer →
  stream**; events never replay onto a snapshot (no shared sequence boundary).
- Debounce with a cap (200 ms quiet / 1 s max) on high-frequency events; reads happen on
  state transitions, not continuously (plus the authorized signature-stable catch-up
  reread for members holding unfinished work); `pane run` with empty stdout and exit 0 is
  success; markers for output matching are runtime-computed and anchored.
- ~500 ms–2.5 s shell-ready delay after spawning a pane before sending text.

### Event loop (hybrid, per prototype verdict)

- **Events own the loop** (`pane.agent_status_changed` per-pane subscriptions; soak:
  1784 events / 0 deaths / 0 reconnects over 30 min).
- **A polling floor guards it**: periodic `session.snapshot` reconcile on the socket
  (timer), so a dead stream degrades to polling, never freezes.
- **Watchdog** on event silence (threshold relative to expected cadence) plus explicit
  `events_lost` frames → reconnect, resubscribe, snapshot-reconcile.

### Fleet shape

- **The lead lives inside herdr**, in a pane of its own — visible, inspectable, and
  replaceable like any member. It is an agent, not a daemon.
- **Mixed, agnostic fleet**: membership is capability-based; any agent kind can be a
  member. Role folders ship defaults (brief templates, onboarding pointers, doorbell
  instructions) that projects can override.
- **Model authority**: the human picks defaults; the lead recommends, requests
  exceptions per task, and never changes a member's model without approval.

### Vocabulary and records (ADR-0002)

- **Doorbell vocabulary**: `DONE <task> <artifact>`, `HELP <task> <reason>`,
  `HELD <task> <waits-on>`, `STOPPED <task> <why>` — pane message and durable record in
  one; state transitions observed over the socket annotate but never replace it.
- **Brief/receipt contract**: briefs are files with stable task ids and attempt ids
  (`7`, `7.2`); members close ids explicitly (`Closes: 7`); results land as sidecar
  artifacts. The lead reads the return file, not the transcript.
- **Team record** per project: state, agreement (versioned), people, lessons, decisions —
  one writer per artifact, all git-versioned in the `~/.agents` tree.

### Stewardship

- **Skill inventory**: lead-curated registry (what exists, maturity, owner) merged with
  member **self-reported capability briefs**; assignments draw on demonstrated fit.
- **Tool ledger**: per-member MCPs and connectors, kept current by the lead, checked
  before briefing tasks that need specific tools.
- **Tiered AGENTS.md compliance**: Tier 0 (safety hard lines — enforced, blocks
  dispatch), Tier 1 (project conventions — checked, reported per task), Tier 2 (style
  preferences — advised, never blocking).
- **Recruitment flow**: capability gap detected against mission + inventory → search
  skill pool → pitch to human (who, why, what it enables, cost) → human approves →
  lead onboards via role folder. Hiring is human-reserved.
- **Version control**: the whole `~/.agents` tree is a git repository (caches and
  lockfiles ignored); stewardship changes are commits, not silent edits.

### From the prototype, encoded as adapter invariants

The prototype's connection discipline, watchdog, and per-pane fan-out patterns
(`proto_probe.py`) carry over as the adapter's first implementation sketch — the
decisions above are its distilled contract; the probe code itself stays throwaway.

## Testing Decisions

- **Good tests observe external behavior only**: fleet state via socket snapshots and
  durable artifacts, never adapter internals or pane pixels.
- **Seam 1 (primary) — the fake-fleet loop**: end-to-end lead behavior against
  zero-LLM fake agents (prototype's `fake_agent.sh` pattern) in a scratch herdr
  workspace. Verifications read `session.snapshot` / `agent.list` and the team record.
  Covers: dispatch, doorbell handling, receipts, watchdog recovery, resume
  reconciliation, compliance reports, recruitment pitch (fake gap).
- **Seam 2 (secondary) — the adapter's JSON interface**: command + params in, JSON out,
  against a live herdr with the fake fleet. Failure injection here only: slow consumer
  (expects `events_lost`), killed subscription connection (expects watchdog + reconnect +
  resubscribe + snapshot reconcile), schema-invalid params (expects hard refusal),
  missing pane id (expects hard error, never a focused-pane fallback).
- **Prior art**: the prototype's smoke/bench/soak/teardown harness and wrap-tolerant
  render verification; the research report's side-by-side reference subscriber for
  starvation detection.
- **Never tested automatically**: pane rendering for humans (verified once by
  prototype; the panes are the human's own eyes).

## Out of Scope

- Remote machines (v1 is local; contracts are already remote-ready files).
- Windows named pipes (CLI-wrapper path is sanctioned there).
- Plugin packaging of the lead (destination, not v1 — the seam keeps it additive).
- Replacing the CLI for humans, or automating anything the human sees in panes.
- Federated multi-lead fleets.
- Automatic model switching without human approval.
- Any scheduler, cron, or permission system beyond herdr's own and the agreement's
  reserved list.

## Further Notes

- Prototype evidence and the community research (every pitfall URL-cited) live in
  `~/Dev/herdr-socket-proto/` (`VERDICT.md`, `research-socket-api.md`) — read both
  before implementing the adapter.
- Unknowns deferred to implementation: prompt-queue depth on working agents,
  `events.wait` one-shot semantics, socket-level rate limits.
- No external issue tracker is configured; specs and tickets live in this tree
  (git-versioned per ticket 0) with `status: ready-for-agent` frontmatter playing the
  triage-label role. The skill's normal tracker flow resumes if one is connected later.
- The two ADRs (`docs/adr/0001`, `0002`) are the binding records for the transport and
  vocabulary decisions; this spec depends on both.

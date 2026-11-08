# Herdr socket adapter

Python 3.9+, standard library only. Implements spec 0001, tickets 03–04 at the JSON
CLI seam. This is agency tooling, not a skill. No installation or network access.

Ticket 06 adds a separate [turn-based lead interface](LEAD.md), consuming this
adapter, the event loop, vocabulary contracts and compliance gate.
After a break or restart, ticket 09's [M1 resume command](LEAD.md#resume-before-another-lead-turn)
reconciles disk and current member identities before returning control to that loop.
Automatic QUIET events cover Claude Code workers with the team Stop hook only;
workers on other Harnesses stay on the manual quiet-worker check.

## Guarded CLI send

```sh
python3 ~/.agents/mifal/tools/herdr_adapter/guard_send.py worker "Task 7: read /tmp/tasks/7.md and start."
```

Run inside Herdr (`HERDR_ENV=1`) with its CLI on PATH. This separate command
uses `agent get` and `pane get` to pin identity/readiness, the socket adapter's
complete passive visible read (CLI text reads omit truncation metadata), then
rechecks identity and invokes `herdr agent prompt` once on the pinned pane.
It does not change the controller's generic-frame guards or timing.
Exit 0 and `delivery: unverified` mean submission acknowledged, not that work
started. No delivery wait, focus, draft clearing or automatic retry occurs.

`composer.py` owns the dialog signature table and captured profiles. A known
dialog footer refuses before profile selection, on any agent. The shipped
[frame evidence](tests/fixtures/composers/README.md) covers Codex 0.166.0 and 0.167.0,
Claude Code 2.1.317 and Pi 1.4.0 clear profiles, plus Codex hook review and
Droid 1.2.0 login dialogs. Droid's clear composer and OpenCode 1.19.4's profile
are unverified. The captured OpenCode frame is retained as evidence only:
startup installed dependencies in its disposable Home despite suppression
flags, so that capture does not satisfy the no-install boundary.
These profiles are layout forms, not promises about other versions or settings.

Preflight refusals make zero input calls. Known dialog, draft, blocked,
not-idle, unreadable, truncated, changed identity and CLI failure stay held.
Only `unsupported_profile` prints the manual path: a lead, agent or human
checks scoped identity, idle/done and a readable empty composer before using
raw `herdr agent prompt`, as [Herdr dispatch](../../skills/team-lead/references/herdr.md#dispatch)
describes. An unseen dialog on an uncaptured agent stays exposed on that path.
A CLI error or timeout during submission reports `send_uncertain`: input may
already have landed; reconcile the pane and durable Return before retrying.

This catches known patterns, not every dialog. Quoted dialog text above a
composer sends; an exact dialog footer at the bottom cannot be distinguished
from UI by plain text. A draft identical to a placeholder is also
indistinguishable. A human or UI can change between the check and send;
this command has no atomic lock or server-side compare-and-swap.

## Interface

One JSON object on stdin; one JSON object on stdout. Exit 0 means the command
returned successfully, **not** that a member received/completed work. Exit 1
returns `{"ok":false,"error":{"code":"…","message":"…"}}`.

```sh
ADAPTER="$HOME/.agents/mifal/tools/herdr_adapter/adapter.py"
printf '%s\n' '{"command":"observe","params":{}}' | python3 "$ADAPTER"
printf '%s\n' '{"command":"observe","params":{"workspace_id":"wEXAMPLE"}}' |
  python3 "$ADAPTER"
```

`observe` returns `members`, `panes`, `tabs`, `workspaces`, version/protocol and
the current focus ids from **one authoritative `session.snapshot`**. It does
not read screens, focus panes, or change the viewport.

Dispatch requires explicit **both** `pane_id` and `workspace_id`, a stable
`dispatch_id`, exactly one of `text`/`brief_file`, and a verified input-box frame:

```sh
python3 "$ADAPTER" <<'JSON'
{
  "command": "dispatch",
  "params": {
    "pane_id": "wEXAMPLE:p1",
    "workspace_id": "wEXAMPLE",
    "dispatch_id": "7.2",
    "brief_file": "/absolute/path/to/brief.md",
    "input_box": {
      "agent": "adapter-fake",
      "start": "[INPUT verified-token]",
      "end": "[/INPUT verified-token]"
    }
  }
}
JSON
```

The file's **content**, not a shell command or filename, is sent. Replace
`brief_file` with `"text":"Your brief"` for inline text. Missing ids never use
`HERDR_PANE_ID`, `pane.current`, or UI focus. The example ids are deliberately
not real targets.

`input_box` is trusted harness-layout configuration, **not a caller assertion
that input is empty**. The adapter itself reads the visible pane twice. The
`agent` must match herdr's live agent kind. `start`/`end` must be distinct literal
whole lines, each unique in the viewport, enclosing only blank lines; all lines
after `end` must also be blank. The viewport must be at the bottom. Missing,
ambiguous, truncated, mismatched, or unknown layouts are refused.
Whitespace-only lines count as empty; the idle window and two-read guard still apply.

**Supported surface in this ticket:** framed input boxes, demonstrated by the
included fake agent. No built-in native Claude/Codex/other TUI recognizers are
claimed. Supply a frame only after verifying it bounds the actual editable
input; never invent delimiters to bypass a refusal. Native harness-specific
recognizers require their own evidence/fixtures before enabling those layouts.
Visible reads cannot atomically lock out a human keystroke between the final
read and submission; the specified two-read guard is not a server-side CAS.

### Durability and timing

- Default idle observation: **60 seconds**, measured with a monotonic clock.
  Snapshots every ≤500 ms pin the agent's `state_change_seq` and identity
  (pane/workspace/tab, terminal, cwd, agent, name). A transient busy→idle cycle
  changes the sequence even if polls miss the busy state. A non-idle or changed
  identity refuses immediately; it does not queue/retry.
  Protocol-22 `done` also qualifies: it means idle-but-unseen, not busy.
  No focus call is needed to clear a completion badge; every other guard remains.
- Default gap between the two empty-box reads: **at least 10 seconds**. This
  stateless CLI conservatively observes a fresh idle window for each dispatch;
  normally the actual read gap is ≥60 seconds.
- `--shell-ready-ms` defaults to **500**, allowed range **500–2500**. Every
  dispatch waits this long before the guard, including panes created elsewhere.
  The core does not expose spawn/close operations.
- Only disposable tests should shorten `--idle-seconds` / `--read-gap-seconds`.
  Both must be finite and positive. No boolean “skip guard” exists.
- `--socket PATH` overrides `HERDR_SOCKET_PATH`, otherwise defaults to
  `~/.config/herdr/herdr.sock`. Supply an explicit socket for named sessions.
- `--state-dir DIR` defaults to `~/.local/state/herdr-adapter`. All dispatchers
  for a session must share the same state directory and socket path: per-pane
  locks serialize guard/send and prevent concurrent typing.

Before sending, the adapter reserves `dispatches/<dispatch_id>/` and persists
`brief.txt` plus an fsynced `record.json` with its SHA-256 and `status: prepared`.
The one atomic `pane.send_input` request contains text + Enter; **no
`agent.prompt --wait` or delivery wait is used**.

An acknowledged submission records `status: sent`, always `delivery: unverified`.
A fully received, id-matched herdr error records `status: refused` and returns
`dispatch_refused`; transport failures (including lost connections/ACKs and
mismatched or malformed responses) record `status: uncertain`.
Both retain `delivery: unverified`. Prepared, sent, refused, and uncertain
ids are all refused on reuse, including after a crash. Never delete a record or
mint another id just to retry: first reconcile the member's durable receipt.
The caller proves delivery from a transcript/sidecar artifact, not this command's
exit code, `sent` status, screen echo, or a timeout.

### Schema validation

```sh
printf '%s\n' '{"command":"validate","params":{"method":"pane.split","params":{"pane_id":"wEXAMPLE:p1","direction":"right"}}}' |
  python3 "$ADAPTER"
# exit 1: schema_invalid — pane.split uses target_pane_id, not pane_id.
```

`validate` is **offline only**, never an RPC escape hatch. It checks the bundled
schema, not authorization/readiness; valid optional targeting in herdr's raw
schema does not authorize sending it. The dispatcher separately requires targets
and guards. Unknown command/params fields are rejected before any socket request.

Every outgoing request validates its params again. The stdlib validator covers
the bundled request schema's references, unions, constants/enums, types, required
fields, arrays, maps, property names, patterns, property counts and numeric
ranges/formats. Unsupported schema keywords fail closed. Object properties are
closed by default, deliberately stricter than herdr's permissive schema.

Only snapshot, passive pane reads, guarded input, pings and subscriptions are routed.
No focus methods, raw RPC forwarding, or request connection reuse exist here;
`--no-focus` is unconditional rather than an optional flag. Each request gets a
new Unix socket, unique id, matching-id NDJSON response, and deterministic close.
No request is ever sent on an event subscription connection.

### Hybrid event loop

```sh
python3 "$ADAPTER" 2>/tmp/fleet-loop.ndjson <<'JSON'
{"command":"watch","params":{"workspace_id":"wEXAMPLE","duration_seconds":180}}
JSON
```

`watch` takes the same closed JSON command/params envelope. It emits one final
JSON result on stdout, plus structured NDJSON diagnostics on stderr throughout
the run. Drain stderr continuously or redirect it to a local file. The result
contains `picture` (the same shape as `observe`), `stats`, `snapshot_age_seconds`,
`snapshot_error` (null after the last successful reconcile), and the configured
`silence_seconds`. A successful run means a snapshot was obtained, not that all
intermediate states were retained or that any work was delivered/completed.

| Parameter | Default | Meaning |
| --- | --- | --- |
| `workspace_id` | omitted | Observe all workspaces; a supplied id must be nonempty |
| `duration_seconds` | 60 | Bounded run duration |
| `floor_seconds` | 3 | Independent full snapshot reconciliation timer |
| `ping_seconds` | 30 | Server ping on a fresh connection |
| `expected_event_seconds` | 2 | Expected relevant-event cadence |
| `silence_periods` | 60 | Watchdog threshold multiplier: **120s** by default |
| `retry_seconds` | 1 | Delay after death/failed subscribe or snapshot; minimum **0.05s** |
| `request_timeout_seconds` | 2 | Request and subscription-ACK timeout |
| `include_updates` | false | Also consume high-frequency `pane.updated` events |

Timing values must be positive finite numbers; unknown params and booleans in
numeric fields are refused. Quiescent fleets can legitimately hit the silence
watchdog: tune the expected cadence to the fleet rather than treating silence
as completion. At the duration boundary, the loop drains any outstanding snapshot
and flushes pending invalidations (including unexpired debounce) with one final
snapshot, logged with reason `exit`. That final request uses
`request_timeout_seconds`; failure preserves the last picture and records
`snapshot_error`. Shutdown can therefore take an outstanding request timeout plus
one final snapshot timeout beyond the duration. There is no background daemon or
scheduler after return. This describes the loop's bounded return, not forcible
termination of arbitrary executor threads. An injected non-cooperative snapshot
can make `Loop.run()` return before the Python CLI process exits: Python waits
for outstanding executor threads at shutdown. Normal socket requests have their
own total deadlines; the audit's sleeping-worker injection does not establish
an ordinary unbounded socket hang.

The sibling `event_loop.py` reuses the core's schema, client, subscription reader,
and `observe`. It does not implement another socket client:

- Discover pane ids from the observed picture, then subscribe once with an
  explicit `pane.agent_status_changed` entry per pane and lifecycle entries.
  Topology changes rebuild the entire fan-out. A rejected subscription refreshes
  the pane list and retries the whole request; never assumes partial success.
- Each bootstrap is ACK → buffer invalidations → snapshot on another connection
  → replace cache → apply buffered invalidations by scheduling a fresh snapshot.
  **Event payloads never mutate or replay onto the cache.** Snapshots and events
  have no shared sequence boundary.
- Event, bootstrap and floor refreshes are serialized by one snapshot worker.
  Separate connection/ACK and ping workers keep those waits from stopping the
  floor or watchdog. Bounded stream reads leave time for all timers.
- EOF, malformed stream frames, `events_lost`, and silent starvation all trigger
  reconnect + resubscribe + bootstrap. Polling continues during stream outages;
  failed snapshots preserve the last picture with explicit age/error metadata.
- Status/lifecycle events reconcile promptly. Optional updates use **200ms quiet
  / 1s maximum** debounce, supporting the mixed dotted/snake-case event names
  seen in protocol 22. Default subscriptions avoid continuous updates entirely.
- No pane output is polled or read by `watch`; transition logs are the seam for
  callers that need a passive output read or durable-artifact reconciliation.

Diagnostic kinds include `subscribe_start`, `subscribed`, `bootstrap_applied`,
`event`, `death`, `resubscribe`, `subscribe_error`, `snapshot_start`, `reconcile`,
`snapshot_error`, `ping`, `ping_error`, and `stopped`. Every row includes elapsed
monotonic seconds and subscription generation. Reconciles include the cause and
changed member identities/status/sequences; floor discoveries are distinguishable.
These are observations, not delivery/completion receipts. A transition shorter
than the observation gap cannot be reconstructed from non-durable events;
authoritative snapshots expose sequence changes, not replayable history.

## Verification

```sh
cd "$HOME/.agents"
python3 -m unittest discover -s tools/herdr_adapter/tests -v
python3 -m py_compile tools/herdr_adapter/*.py tools/herdr_adapter/tests/*.py

# OPT-IN: creates then closes its own four-pane ADAPTER-TEST-* workspace.
python3 tools/herdr_adapter/tests/live_acceptance.py --live --safe-defaults

# OPT-IN: own four-pane ADAPTER-LOOP-TEST-* fleet; fault injections + 3-minute soak.
python3 tools/herdr_adapter/tests/live_event_loop.py --live --soak-seconds 180
```

Offline tests exercise the public JSON CLI against a disposable Unix peer.
The live suite starts zero-LLM fake agents with self-reported idle/working/blocked
states. A recording proxy limits all mutations to its owned scratch pane ids.
It checks file dispatch against a durable, member-written receipt and
runtime-computed marker; fleet observation; zero requests on invalid schema or
missing pane; preserved drafts; unreadable-box refusal; and focus invariance.
`--safe-defaults` additionally measures a full real 60s/10s guard.

Evidence is left under the printed `/tmp/adapter-live-*` directory:
`commands.json` has exact argv, JSON inputs, results, exit codes, and request
counts; `wire.json` records adapter requests; `focus.json` records focus checks;
`workspace-{before,after}.json` and `identities-{before,after}.json` prove teardown
and preservation of pre-existing workspace/pane identities. Receipts and send
records remain there for inspection. Tests never type in, focus, or close any
pre-existing pane/workspace. Human rendering is not claimed as an automated test.

The event-loop suite uses a read-only proxy for a killed subscription, silent
event suppression, and a 15-second pause reading the actual herdr stream with
high-frequency updates enabled. If the server buffers that pause without
`events_lost`, the summary says `attempted-and-covered-by-unit-test`; it never
claims live backpressure recovery was demonstrated. Offline tests synthesize the
actual error frame and verify resubscription before snapshot recovery.

Loop evidence is printed under `/tmp/adapter-loop-live-*`: `commands.json` stores
exact argv/inputs/results; `{killed,silent,slow,soak}.ndjson` holds structured loop
logs, `*-wire.json` records requests, and `*-proxy.json` proves failure injections
and zero requests on subscription streams. Cycling fake agents write
`member-*/states.ndjson`, an independent snapshot-confirmed state/sequence oracle
(an unseen idle completion is `done`, not `idle`). `summary.json` counts expected,
missing, and floor-only transitions; only the first/last one-second boundary is
excluded. `workspace-{before,after}.json`, `identities-{before,after}.json`,
`focus.json`, and `teardown.json` prove preservation and terminated fake-agent pids.
No failures are injected into another client's connection or workspace.

## Protocol provenance

`api-schema.json` is an unchanged copy of the locally captured
`herdr api schema --json`, **herdr 0.9.3 / protocol 22 / schema version 1**.
SHA-256: `9e2af207e9aa8183d4aeca5fde9cc48e7909bb40cdbd7cf21608a6d3ea78075b`.
Other snapshot protocols are refused; no unverified compatibility fallback.

Binding sources read for this implementation:

- `docs/team-lead/specs/0001/tickets/03-socket-adapter-core.md` in the Mifal repository (not installed)
- `docs/team-lead/specs/0001/tickets/04-event-loop.md` in the Mifal repository (not installed)
- `docs/team-lead/specs/0001/spec.md` in the Mifal repository (not installed): Transport / Testing Decisions
- `~/.agents/skills/team-lead/docs/adr/0001-socket-transport.md`
- `~/Dev/herdr-socket-proto/{VERDICT.md,proto_probe.py,fake_agent.sh,api-schema.json,research-socket-api.md}`

The prototype and skills repositories remain read-only references.

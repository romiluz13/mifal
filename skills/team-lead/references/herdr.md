# Leading a team through Herdr

Read when the team's channel is Herdr: the agreement says so, or the roster
lives in Herdr panes. This file covers how to lead through Herdr. For command
syntax, load the `herdr` skill and trust the installed CLI's help over this
page. The user choosing Herdr for this team counts as the explicit mention
that skill requires.

First, check you're inside Herdr: `test "${HERDR_ENV:-}" = 1`. If you're not,
say so and lead through whatever other channel is authorized. Don't drive a
Herdr session from outside it.

## Choose the coordination path

For a small peer exchange, use short inline messages with an exchange id,
sender/receiver and a round limit. Finish on the intended receiver's explicit
reply for that id, not a matching line in another pane or an idle state. The
lead owns the overall wait bound; workers need no improvised timers or task
factory for a joke exchange.

For engineering assignments, use the task/receipt protocol below and visible
chat summaries. For a sustained fleet loop, read the agency tooling guide
`~/.agents/mifal/tools/herdr_adapter/LEAD.md` before choosing its one-turn socket
controller and resume reconciliation. This is tooling, not another skill or an
automatically running scheduler. Its verified input-box framing and trusted
expected-artifact digests are prerequisites; the zero-model live fixtures do
not establish native Claude, Codex, Droid or Pi framing. Use the guarded CLI send below
when that controller is unsuitable, after checking the receiving harness.
Do not invent frame delimiters or weaken the production draft guards.

## Know who's on the team

`herdr agent list` returns every agent on the server, including other
people's teams in other workspaces. Filter to `workspace_id` equal to
`$HERDR_WORKSPACE_ID`, or to the workspaces the agreement names. Anything
outside that set isn't yours to onboard or message.

For each teammate, record in `state.md`: the name, `pane_id`, `agent` kind,
and `agent_session.value` when present. The kind is Herdr's detection, which
is more reliable than a model name someone typed in a message, but it still
isn't a model version.

Names are what the team runs on: briefs, the doorbell, and the record all
address teammates by name. If panes the user set up for this team have no
name, give them short, stable ones with `herdr agent rename <pane> <name>`,
and note it in `agreement.md`. Name your own pane too, so workers can reach
you.

A new `agent_session` value in a known pane may be a replaced worker, with
none of the old context, or a child `claude` running in that pane, which
reports its own id. Look at the pane before you re-brief: re-brief a replaced
worker from the record, and don't assume it remembers anything.

## The attention loop

1. **Look:** the filtered `agent list`, `state.md` and the expected return files.
2. **Pick** the highest-value moment. Rough order: a `blocked` teammate, a
   report waiting for you, an idle teammate with valuable work, a teammate
   quiet past its expected time, then a reflection that's due.
3. **Act** on that moment.
4. **Record** in `state.md`; a task line goes in before its prompt is sent.
5. **Wait** with a limit. Either the doorbell wakes you, or you use
   `herdr agent wait <name> --timeout <ms>`. Pick the timeout from how long
   the task should take. Don't run a bare polling loop. If your harness can
   run commands in the background, run the wait there so finishing it wakes
   you.

## Dispatch

For CLI dispatches and worker rings, use
`python3 ~/.agents/mifal/tools/herdr_adapter/guard_send.py <target> "<text>"`.
It resolves the target, checks identity and idle/done state, passively reads the
complete visible frame with truncation metadata, refuses known dialog menus
before selecting a captured composer profile, and rechecks identity before
sending once to the pinned pane. It never clears input or focuses a pane.
The socket controller keeps its existing two-read draft guard; its generic
frame delimiters do not establish native composer support.

A refusal names its reason. Only `unsupported_profile` prints the manual path:
the lead, agent or human may check the scoped identity and idle/done state,
read the visible composer, and use `herdr agent prompt <target> "<text>"` only
if that composer is readable and empty. Known dialog, draft, blocked, not-idle,
unreadable, truncated, identity-change and CLI-failure refusals stay held;
none permits a raw-send bypass. Preserve drafts and leave a visible summary.
A dim Claude prompt suggestion is empty input; the guarded ANSI read distinguishes it from a typed draft.
An unseen dialog on an uncaptured agent remains exposed on the manual path.

Profiles cover the captured Codex, Claude and Pi frames only. Droid's clear
composer and OpenCode's profile are unverified. OpenCode startup installed
dependencies in its disposable Home despite suppression flags, so its captured
frame is retained as evidence but is not enabled as a profile. The signature table currently covers Codex hook
review and Droid login menus, including a menu with footer lines below it.
Claude matches the empty composer itself; footer modes, status lines and
notices below it do not decide whether it is clear. Codex keeps its captured
two-row footer boundary; missing or changed footer rows remain unsupported.
Arbitrary footer text is ambiguous with multiline draft text. Missing or
ambiguous composer boundaries refuse. This is known-pattern detection, not
general dialog recognition. Quoted dialog text above a real clear composer
does not refuse; plain text cannot distinguish a perfectly copied menu from UI,
or a draft that exactly reproduces an accepted placeholder.
The check-to-send race with human typing or a changing UI remains: no atomic
lock or compare-and-swap is claimed. Herdr's structured `agent_blocked` submit
error rejects before input and leaves a retryable hold; retry the full checks
after it is clear. Any other submission failure is `send_uncertain`: do not
retry until the pane and durable Return have been reconciled. A Codex pane
whose status line is off or holds one item refuses, and says so: its footer
can't be told from a draft without a captured form. Claude's box is the last
two column-0 rules in the frame: a footer drawing rules of its own could move
it, though no captured footer does.

- Launch a fresh worker plainly: Mifal's Guide makes Matt the owner in every
  harness. Preserve the requested account, provider, model and effort. Use
  documented `pane run <pane-id> <shell command>` in an available shell, then
  check `agent get <pane-id>` for detection/readiness; use
  `agent explain <pane-id>` if detection is unclear, then
  `agent rename <pane-id> <name>` for its live name before prompting.
- Start a worker with the same or narrower approval, filesystem and network
  permissions as yours, because a worker can do whatever its launch allows,
  including what you could not authorize. Compare effective capabilities, not
  mode names: actions requiring approval, writable paths and network access,
  including tools and child processes. Record your own effective capabilities;
  before each launch, establish the worker's from the installed version's
  documented flags and settings, or its documented defaults when no settings
  exist, and record the actual launch arguments, without credentials, with its
  roster entry in `state.md`. Pass a flag that skips approvals only when you
  run that way too and the agreement allows it. A dimension whose effective
  behavior stays unestablished counts as not equal: name it, and it holds the
  dispatch. An approval mode, project-trust choice or enabled bypass option is
  not proof of a sandbox or of an active bypass.
- Put the brief in `<record>/tasks/<id>.md`, where `<record>` is the
  record root's absolute path
  ([communication](communication.md#parallel-agents-in-one-repository)), and
  send a short prompt that points to it: `python3
  ~/.agents/mifal/tools/herdr_adapter/guard_send.py <name> "Task <id>: read <record>/tasks/<id>.md and start. Ring me when done."` Tiny
  tasks can go inline. A correction uses its attempt id (`Task 7.2`).
- Pin the brief before you send it: `validate_contracts.py brief-digest
  <record>/tasks/<id>.md` prints `sha256:<digest>`, and you stamp
  `brief=sha256:<digest>` in the dispatch Check line. Re-stamp after any
  amendment of your own. You accept the return with `validate_contracts.py
  receipt <record>/tasks/<id>.md --matt --brief-digest sha256:<digest>`, which
  refuses a brief that changed in any way but its ticks ([phase
  record](../../engineering-workflow/references/phase-record.md)).
- Before direct prompts, check the scoped pane identity and readiness, then
  use the guarded send above to read the composer; if it holds a draft or is
  unreadable, do not send. An idle state alone does not prove the input is empty.
  Preserve the draft, skip the send and leave the durable return plus a visible
  summary. Never clear a user's draft. The manual check/send sequence available
  only after `unsupported_profile` has the same race with human typing.
- Prompt only a teammate that is `idle` or `done`. Text sent to a `working`
  agent may interleave, queue, or behave differently depending on the
  receiving harness; verify per harness. If you need to stop work, use the
  stop procedure below. Don't send a message instead.
- When dispatching to several teammates, send all the prompts without
  `--wait`, then wait on each. `--wait` on the first one leaves the others
  unassigned.
- A successful prompt only proves the text was submitted, not that work
  started. If a prompt times out or stalls, run `agent get` and `agent read`
  before sending anything again. The first one may already have landed. A
  `send_uncertain` result requires reconciliation before another attempt.

## The doorbell

The return happens in three parts:

1. The worker writes its full report to the file named in the brief.
2. It shows a short summary in its own chat: task/attempt, result, decisive
   checks, blockers and the receipt path. The human can follow the team
   without opening every artifact. Derive this summary from the receipt.
3. The worker waits up to about a minute for your pane to be free
   (`herdr agent wait <lead> --until idle --until done --timeout 60000`),
   then verifies the lead's identity and empty readable composer before
   sending one line: `python3
   ~/.agents/mifal/tools/herdr_adapter/guard_send.py <lead> "DONE <id> <path>"`. Use
   `HELP <id> <specific question>` for guidance, `HELD <id> <approval needed>`
   for a human approval, or `STOPPED <id> <reason>` after a stop. These follow
   the [doorbell contract](contracts/doorbell.md). If the wait times out, or
   the guard refuses for any reason but `unsupported_profile` or
   `send_uncertain` (you are at a dialog, you scrolled up, your composer holds
   a draft or can't be read), the worker leaves your input alone and tries the
   whole step again every 2 minutes for up to 30 minutes. The worker runs the wait and every retry in the foreground,
   never as a background task: a background task that finishes may start no
   new turn, and the ring then comes late or not at all. It never sends to a
   busy lead, for any kind of lead. After 30 minutes it stops trying, and notes
   the last refusal in its Return; the file is enough.

Put these steps and your pane's name in every brief that expects a return.
Tell workers to deliver one ring: a refused or skipped attempt is retried,
and a ring that was sent is never sent again. The file is authoritative; the
ring is only a hint, so whenever you wake, and between your own steps, check
the expected return files whether or not a ring came. The durable detail
survives compaction, while the summary stays visible in chat. This is the
Team Lead task-return protocol; Herdr's chat-first guidance for ad hoc
command/output exchange still applies there.
A foreground `agent wait` on a worker shows you as `working`, so its ring
has to wait: run your wait in the background where the harness allows,
otherwise keep it short.

## Reading a pane

The return file is your first source of evidence. A pane transcript is the
last. When you need the pane (a teammate has gone quiet, a UI is blocked, or
a doorbell never came), read a small window:
`herdr agent read <name> --source recent-unwrapped --lines 40`. Widen it only
if that doesn't answer the question. Every line you read comes out of the
context you need for judgment.

While a pane is working, use the installed CLI's passive `--source visible`
read; history sources can require an idle pane. Verify the current help.

`idle` or `done` doesn't mean the work was accepted, or that the artifact
hasn't changed. Accept work only after checking its evidence.

## Blocked

`blocked` means Herdr sees an approval or question UI. Check it with
`agent get` and a short `agent read`.

- **Approval to run a command, edit, or access something:** this is
  reserved for the human unless `agreement.md` pre-authorizes that exact
  class of action. Send the human the command, the pane, whether it's in
  scope, whether it can be reversed, and your recommendation. Leave that pane
  held and keep the rest of the team working.
- **A question about the task:** answer it if the answer is within your
  authority. Otherwise treat it as a question for the human.

Never approve a dialog just to keep things moving.

## Quiet teammates

A Claude Code worker with the team Stop hook (a per-project copy of
`~/.agents/mifal/tools/herdr_adapter/hooks/team-stop.sh`), admitted through
`lead.py` or an assignment pin, leaves a QUIET event when a turn ends with no
report: one file in `<record>/quiet/`. Attend to it last, after any ring,
assignment or review that is due: look at the pane and ask for `DONE`, `HELP`
or `HELD`. Under `lead.py` it is a row in `state.md`'s Lead attention needed,
and the turn that attends to it writes the `attend-quiet` entry that consumes
it. Without `lead.py`, list `quiet/` when you wake; an event from an
assignment pin carries owner `-`, so match it to its task by pane and
attempt, and your progress log entry naming the event is what consumes it.
QUIET closes, fails, retries and unholds nothing. Which events are stale or
superseded, and which files to leave unread:
[doorbell contract](contracts/doorbell.md#quiet-is-attention-only).

Herdr's `agent_session` is used to word a row and to attribute a ring to a
session, but never to dismiss an event, because a child `claude` in a pane
reports its own id for that pane. A ring never supersedes it either: only a
later stop from another session can. Herdr's session is null on some panes,
and that is normal.

Only Claude Code workers with that hook get QUIET events. Workers on other
agents stay on the manual check below, as does anything a Stop event cannot
see: a cleared or replaced session, a worker that never stops, or one that
exited.

A teammate that's still `working` past the time you expected, or is in
`unknown`, isn't evidence of anything yet. Read a small window, then work out
which it is:

- **Progressing slowly:** extend the wait once, with a new limit.
- **Thrashing** (repeating attempts that fail): stop it and re-brief with
  what's missing.
- **Lost the thread** (re-asking settled questions, contradicting its own
  earlier findings, ignoring constraints in the brief): stop it and re-brief
  from the record. With authority, start a fresh session.
- **A service or tool failure:** that's a problem with the environment, not
  with the teammate's reasoning. Record it that way.

Take one bounded action and record it.

## Stopping and scope changes

To interrupt, use the kind's interrupt, usually
`herdr agent send-keys <name> esc` (see the herdr skill for other kinds).
Wait for `idle`, then use the guarded send for a plain message saying what stopped, what to keep,
and what happens next. A stop that hasn't been acknowledged is unconfirmed.
Record it that way. A thank-you or a reflection message is not an instruction
to resume old work. Say so if the teammate could read it that way.

## Paging the human

`herdr notification show "<title>" --body "<one line>" --sound request` is
only for things the human needs to act on: an approval, a product decision,
or bad news. It's a pager, not a feed. Routine progress goes in the progress
log in `state.md`.

## Keeping or restarting a teammate's session

Keep the same session for related follow-on work. Its context and the
feedback you've already given it are an asset. Start a fresh session, with
authority, for unrelated work or once a teammate has lost the thread. The
development record belongs to the member, not the session, so carry it into
the next brief.

A re-review after a fix is the exception: it goes to a new reviewer session,
as [review and disagreement](communication.md#review-and-disagreement) says.

## House rules inherited from the herdr skill

Use `--no-focus`, and leave the user's focus where it is. Don't close panes,
tabs, or workspaces you didn't create. Parse IDs from JSON rather than
predicting them. Never stop the Herdr server.

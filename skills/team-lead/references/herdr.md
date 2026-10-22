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
not establish native Claude, Codex, Droid or Pi framing. Keep the raw CLI path
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

A new `agent_session` value in a known pane means a new session with none of
the old context. Re-brief it from the record. Don't assume it remembers
anything.

## The attention loop

1. **Look:** the filtered `agent list` plus `state.md`.
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

- Before assigning engineering implementation to a fresh Claude worker,
  start it under the parent methodology. Mifal's Guide makes Matt the owner
  in every harness, so a plain launch is enough. Use documented
  `pane run <pane-id> <shell command>` in an available shell, then
  check `agent get <pane-id>` for detection/readiness; use
  `agent explain <pane-id>` if detection is unclear, then
  `agent rename <pane-id> <name>` for its live name before prompting.
  Preserve the requested account, provider, model and effort.
  Reuse an existing session only with checked effective ownership. A
  session another methodology owns can give a bounded advisory review without inheriting
  Matt's lifecycle; implementation under another owner needs a fresh launch.
  See the engineering-workflow owner contract; a successful preview is
  configuration evidence, not observed runtime ownership or compliance.
- Put the brief in `<record>/tasks/<id>.md`, where `<record>` is the
  record root's absolute path
  ([communication](communication.md#parallel-agents-in-one-repository)), and
  send a short prompt that points to it: `herdr agent prompt <name> "Task
  <id>: read <record>/tasks/<id>.md and start. Ring me when done."` Tiny
  tasks can go inline. A correction uses its attempt id (`Task 7.2`).
- Before direct prompts, check the scoped pane identity, readiness and an
  actually empty composer using the receiving harness's verified layout. An
  idle state alone does not prove the input is empty. If a draft exists or the
  composer is unreadable, preserve it, skip the send and leave the durable
  return plus a visible summary. Never clear a user's draft. This manual
  check/send sequence has a race with human typing; it is not atomic.
- Prompt only a teammate that is `idle` or `done`. Text sent to a `working`
  agent may interleave, queue, or behave differently depending on the
  receiving harness; verify per harness. If you need to stop work, use the
  stop procedure below. Don't send a message instead.
- When dispatching to several teammates, send all the prompts without
  `--wait`, then wait on each. `--wait` on the first one leaves the others
  unassigned.
- A successful prompt only proves the text was submitted, not that work
  started. If a prompt times out or stalls, run `agent get` and `agent read`
  before sending anything again. The first one may already have landed.

## The doorbell

The return happens in three parts:

1. The worker writes its full report to the file named in the brief.
2. It shows a short summary in its own chat: task/attempt, result, decisive
   checks, blockers and the receipt path. The human can follow the team
   without opening every artifact. Derive this summary from the receipt.
3. The worker waits up to about a minute for your pane to be free
   (`herdr agent wait <lead> --until idle --until done --timeout 60000`),
   then verifies the lead's identity and empty readable composer before
   sending one line: `herdr agent prompt <lead> "DONE <id> <path>"`. Use
   `HELP <id> <specific question>` for guidance, `HELD <id> <approval needed>`
   for a human approval, or `STOPPED <id> <reason>` after a stop. These follow
   the [doorbell contract](contracts/doorbell.md). If the wait times out, the
   prompt is refused with `agent_blocked` (you are at a question or approval
   dialog), or your composer holds a draft or can't be read, the worker leaves
   your input alone and tries the whole step again every 2 minutes for up to
   30 minutes. It never sends to a busy lead. After 30 minutes it stops trying;
   the file is enough.

Put these steps and your pane's name in every brief that expects a return.
Tell workers to deliver one ring: a refused or skipped attempt is retried,
and a ring that was sent is never sent again. The file is authoritative; the
ring is only a hint. The durable detail survives compaction, while the summary stays
visible in chat. This is the Team Lead task-return protocol; Herdr's
chat-first guidance for ad hoc command/output exchange still applies there.
A foreground `agent wait` on a worker shows you as `working`, so its ring
has to wait: run your wait in the background where the harness allows,
otherwise keep it short and check the expected return files on each wake.

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
Wait for `idle`, then send a plain message saying what stopped, what to keep,
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

## House rules inherited from the herdr skill

Use `--no-focus`, and leave the user's focus where it is. Don't close panes,
tabs, or workspaces you didn't create. Parse IDs from JSON rather than
predicting them. Never stop the Herdr server.

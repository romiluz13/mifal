# The receipt contract

A receipt is the member's return: the durable proof that a task came back and
what came back with it. It lives in the task file below the brief (under
`## Return`), and its results land as sidecar artifacts. Delivery is proven
by receipts, never by transport return codes — a timeout proves nothing, so
the lead reads the return file, not the transcript and not a send's exit
status. The same fields may live in an existing native task record or Pi
journal declared in the brief. For a read-only request they may remain in
the conversation, with persistence explicitly unverified. The Markdown
validator checks file representations; it does not prove native delivery.

## Shape

```
## Return — attempt 7.1

Closes: 7

### Result
### Claims
### Evidence
### Sidecars        # when artifacts were produced
### Limits
### Decision needed # when the lead must decide something
### What I wish the brief had said
### Lesson proposed # optional
```

### The `Closes:` line

Required, exactly as written: `Closes: 7` (or an attempt id, `Closes: 7.2`).
Closing ids explicitly is what lets the lead reconcile: an open attempt stays
open until its own id closes, and a late `DONE 7` can never close `7.2`.

### Required sections

- `### Result` — the finding or change, with artifact identity (commit, path,
  digest). An honest stop reports "no fix" here; that is a good receipt.
- `### Claims` — every done-means claim from the brief, one line each:
  `- <claim>: passed|failed|untested` plus the revision checked. A claim the
  receipt doesn't address is untested, never assumed.
- `### Evidence` — what was actually inspected or produced, as pointers.

### Sidecars

Results land as files next to the task file (`tasks/7/repro.txt`), listed one
path per line under `### Sidecars`. The receipt points; it doesn't paste
logs.

### Optional sections

`### Limits` (failed approaches, what's unknown, cleanup owed),
`### Decision needed` (with a recommendation),
`### What I wish the brief had said` (one line, or "nothing"),
`### Lesson proposed` ("When <trigger>, do <rule>" — the lead checks it
before it enters `lessons.md`).

## Rules

- **Receipts over return codes.** Sending, acknowledgment, completion, and
  acceptance are four different events; only the complete receipt at the
  declared surface proves delivery. A native completion signal without its
  claims and evidence remains insufficient.
- **One writer.** The owning member appends the return; the lead writes
  everything else in the record.
- **Statuses anchor to revisions.** Each claim names the revision or digest
  it was checked against, so a later change can't make old evidence look
  current.

Fixture: a well-formed receipt is
`scripts/fixtures/receipt/good/receipt-7.md`; check any return with
`validate_contracts.py receipt <path>`.

## Command run records

Run a command through the validator to capture its input identity and output:

```sh
validate_contracts.py run --out /evidence/tests.json --repo /checkout -- pytest -q
validate_contracts.py run --out /evidence/tests.json --path ignored-input -- command argument
```

The command receives literal argv, without a shell. Shell metacharacters stay
arguments; invoke a shell explicitly if the check itself requires one. The
child runs in the caller's cwd. The measured repository is the Git root of
that cwd, or the root selected by `--repo`; the record keeps repo and cwd
separately. An unresolved index is refused before launch.

The default scope includes tracked, staged, unstaged and nonignored untracked
files. Identity uses `review-snapshot.py`'s raw bytes, symlink target text,
executable bits and filter-disabled Git reads. `--path` adds inputs to that
scope; it never narrows the default scope. Paths are relative to the repository
root, or absolute for external inputs. A named directory includes its files,
including ignored files, without following directory symlinks. An unreadable
named directory is refused rather than silently omitted. Ignored and
external inputs are otherwise outside scope. Submodule worktrees are not
inspected, and collection is not atomic. Claims must state any additional
limit in what the command checked; the default input limits are in the record.

Every symlink, tracked or explicitly named, is measured by its link text.
Its target's contents are not opened. This also applies to links inside a
named directory. Name the target directly with `--path` to measure its contents.

`--out`, `<out>.stdout` and `<out>.stderr` must lie outside the measured scope.
An ignored output location inside the repository is allowed when it is not
tracked or explicitly included. Every output is reserved by exclusive create
before launch; an existing file or symlink is refused and preserved. During
execution the reserved record is empty and cannot support a claim. After both
identities and the full streams are collected, a complete JSON record replaces
the reservation atomically. A wrapper failure can leave empty reservations
and captured streams for diagnosis; they are not a complete run record.

The JSON schema is version 1:

- `argv`, `repo`, `cwd`, and `scope` (`paths` plus textual `limits`).
- `before` and `after`: review-snapshot identity objects with default `paths`
  of `["."]`, no omitted untracked files, and `explicitPaths` / `explicitFiles`
  for additional inputs. `snapshotSha256` hashes canonical, sorted JSON of
  those identity fields, excluding `snapshotSha256`, `reviewCommands`, and
  `limits` as in review-snapshot's identity rules.
- `candidate`: the before-run `head` and `identity: "sha256:<digest>"`.
- `startedAt` and `endedAt`: UTC timestamps.
- `exitStatus` and `signal`: one integer and one null. `outcome` is `passed`
  for exit 0, `failed` for a nonzero exit, or `crashed` for a signal.
- `execution: "producer"`, always. This release has no immutable evidence
  identifying a local producer, so `producer` is always `"unknown"`.
  Environment variables and flags cannot upgrade it to a lead or reviewer.
- `stdout` and `stderr`: absolute sidecar `path`, full-stream `sha256`, `bytes`,
  and a UTF-8 `tail` decoded from at most the last 4096 bytes with replacement
  for invalid bytes. The sidecars preserve full, exact bytes.

The wrapper returns the child's exit status, or `128 + signal` for a killed
child. Launch, identity and publication errors print `error: run wrapper:`
and return 125. A child can also exit 125; its complete record distinguishes
that child failure from a wrapper failure. No timeout or not-executed outcome
is recorded.

## Citing a run

The existing `- <claim>: passed|failed|untested` grammar remains valid. A
run-backed claim uses this suffix, in order (paths contain no whitespace):

```text
- tests: passed | run:/evidence/tests.json head:<commit> identity:sha256:<digest>
- focused-check: passed | run:/evidence/focused.json head:<commit> identity:sha256:<digest> limit:only the named behavior was checked
```

A relative record path resolves from the task file's directory. `head` is the
full Git commit id; the digest is the record's before-run `snapshotSha256`.
`receipt --matt` refuses a missing, malformed, truncated or incomplete record,
inconsistent fields, an outcome that differs from the claim, a signal, drift
between before and after identities, or a HEAD or identity token mismatch.
A launch failure supplies no complete record. A matching failed record can
support a `failed` claim; whether that failure was an expected negative control
is decided by the enclosing check. A claim without `run:` still passes the
existing checks, with a `note:` naming each passed claim lacking a record.
Each agreeing `run:` claim also gets a `note:` labelling it historical. These
notes say only that the claim and record agree; they imply nothing about the
current checkout and start no command.

## Checking the current candidate

Before reusing a run for acceptance, check it against the checkout being
accepted:

```sh
validate_contracts.py run --check /evidence/tests.json
validate_contracts.py run --check /evidence/tests.json --repo /checkout
```

The checked repository is the Git root of the caller's cwd, or the root
selected by `--repo`. Both roots are resolved and must equal the record's
repository root. A sibling worktree is a different root even when its HEAD
and files match; check a worktree's record in that worktree. Merging changes
the candidate, so the integration checkout needs its own run.

The checker reads the saved explicit paths and before/after identities,
including recorded untracked paths. It uses the same raw-byte collector as
`run`, checks the current nonignored untracked set too, and compares both
recorded identities with current HEAD, file bytes, executable bits, symlink
target text and index identity. Changing current ignore settings cannot hide
a previously recorded untracked input. `--path` and command argv are refused
with `--check`; its scope comes from the record. The recorded argv is never
executed, and neither the record nor the checkout is written.

If the candidate matches, stdout contains:

```text
ok: candidate matches run record /evidence/tests.json
```

Exit status is 0. A mismatch prints `stale:` lines naming the repository,
HEAD, each changed file identity, index or remaining scope identity, and
exits 1. Missing, malformed, truncated, inconsistent or unreadable records
and inputs are refused with `stale:` and exit 1, without a traceback. A run
that drifted must match both snapshots and cannot pass by matching only its
after snapshot.

Named external inputs and ignored inputs (including children of a named
directory) are remeasured. A `note:` names each such input and states that
file bytes or symlink link text are checked, without vouching for dependencies.
Each named symlink gets its own `note:`, including links inside a named
directory. The note names the link, says its target contents are not checked,
and explains that naming the target directly with `--path` covers its contents.
Unreadable inputs are refused. An unnamed ignored input remains outside the
record's scope and does not change this result.

`ok` covers only the record's scope. It does not prove the command passed or
tests the claim, authenticate execution, inspect submodule worktrees, or
detect an edit reverted between collections. Collection remains non-atomic.
The command's outcome and the enclosing claim still need their own checks.

On a case-insensitive volume, a case-only tracked rename can leave the
measured identity unchanged and return `ok`, even when case-sensitive imports
or build rules behave differently. Exact directory-entry spelling is not
proved. A probe on a normalization-insensitive volume with Git
`core.precomposeunicode=true` and `core.ignorecase=true` also returned `ok`
after an NFC-to-NFD-only tracked rename: the entry spelling changed while the
original spelling still opened the same file. Unicode-normalization spelling
is likewise outside this proof; other filesystem or Git settings can differ.

A record is editable JSON, not an authenticated attestation. Internal agreement
does not prove who ran the command, that its input scope contains every relevant
dependency, or that the command tests the claim. Receipt validation reads the
record; it starts no command, does not rehash stream sidecars and does not check
the current checkout. An old record and matching tokens can still agree after
source changes; the separate `run --check` command measures the current candidate.

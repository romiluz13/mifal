# Mifal

**A shared engineering workflow for the coding agents Mifal can wire on your Mac, plus a validator that checks their records when run; you still review the work.**

[![tests](https://github.com/romiluz13/mifal/actions/workflows/test.yml/badge.svg)](https://github.com/romiluz13/mifal/actions/workflows/test.yml) ![status: alpha](https://img.shields.io/badge/status-alpha-C2362B) ![platform: macOS](https://img.shields.io/badge/platform-macOS-1C1B19) [![license: MIT](https://img.shields.io/badge/license-MIT-2E7A4C)](LICENSE)

**[The Mifal website](https://romiluz13.github.io/mifal/)**: the build replay you can scrub through, the gate, and the install run.

![Install, doctor and uninstall in a disposable home folder: every write previewed, 17 doctor checks passed, and the home folder matching its pre-install snapshot after uninstall](docs/assets/install-doctor-uninstall.gif)

<sub>A recorded run of Mifal 0.2.4 in a disposable home folder on macOS. The last command compares that folder with a snapshot taken before the install; the snapshot leaves out the working folder holding the clone and the <code>.cache</code> and <code>.npm</code> caches, and Herdr was already installed.</sub>

An agent's "done" message is not independent proof that the work passed its checks. Mifal detects five agent families (Claude Code, Codex, Droid, Pi and OpenCode) and installs one Guide into the selected homes it can wire; a precedence conflict or a symbolic rules file can make it skip an agent or refuse the install. It also installs the same 39 skills (Matt Pocock's engineering skills run as ordered phases, plus DDD, review and team leading) and a contract validator that refuses a brief, receipt or phase record that lacks its required fields and checks selected identities and hashes; it does not verify that tests ran or that skills were invoked. `--dry-run` previews the planned changes; a plain install prints a short summary and writes. Uninstall removes what Mifal wrote that is unchanged and keeps any file you edited.

## What you get

- 🧭 **One workflow, five agents.** For each selected home that can be wired, the installer adds the same Guide. The Guide instructs the agent to load `engineering-workflow` before an engineering request; Mifal does not force that invocation. A multi-session build runs scope → grill → spec → tickets → implement → review → retro in order; research, planning, debugging and review take shorter routes. `mifal doctor` checks the recorded install, the Guide blocks and the configured skill paths; it does not start agents or prove they loaded the Guide or the skills.
- 🛡️ **Gates that refuse.** The Guide has the agent run `validate_contracts.py` before every dispatch, review and acceptance. A record that lacks its required fields is refused with a diagnostic, and a passing record still needs its cited work and evidence reviewed:

  ```text
  $ python3 ~/.agents/skills/team-lead/scripts/validate_contracts.py brief .team/tasks/7.md --matt
  error: .team/tasks/7.md: missing section '## Done means'; the brief contract requires: Why, Outcome, Done means, Stop rule
  error: .team/tasks/7.md: missing '## Workflow' for the Matt check; add one before '## Return', e.g.:
    ## Workflow
    Methodology: matt
    ...
  ```
- ↩️ **Previewed, and undone where unchanged.** `--dry-run` lists the planned changes before anything changes. Your own rules files keep everything you wrote; Mifal adds one Marked block. `mifal uninstall` removes unchanged managed files, links and blocks, preserves your edits and additions, and restores a moved-aside backup only when its target is free (otherwise it keeps and reports the backup); Herdr stays installed.
- 👥 **A team, not a single chat.** The team lead skill has the lead brief agents in [Herdr](https://herdr.dev) panes, check their receipts with the validator, and send their work to a reviewer before accepting it, as in the replay above.

## Quickstart

You need macOS, git and Python 3.9 or later; verify them with `git --version` and `python3 --version` (`xcode-select --install` provides them on the tested Mac). The dry run lists every write and changes nothing. If Herdr is missing, the installer runs `brew install herdr`, which the dry run shows first; without Homebrew, in a terminal it downloads Herdr's install script, shows its checksum and asks before running it, and without a terminal it stops unless you pass `--herdr-script`.

```sh
git clone https://github.com/romiluz13/mifal.git
cd mifal
./install.sh --dry-run
./install.sh
```

The install puts the `mifal` command in `~/.local/bin`; if that folder is not on your PATH, the installer prints the line to add to `~/.zprofile`. Then check the install:

```sh
mifal doctor
```

Start a session in any agent Mifal wired, in a project folder, and ask for engineering work as you normally would. The Guide tells the agent to scope the request, ask whether you want the full workflow or a cut, and work phase by phase. For a team, start the session inside Herdr (`herdr`) and ask for one.

## Built by its own team

<img src="docs/assets/mission-replay.gif" width="480" alt="Mission replay: the lead, a reviewer, a researcher and an outside critic built Mifal over 19 hours; the reviewer said HOLD five times, with 21 blocking findings across those rounds, all closed before the public release">

Mifal 0.1 was built by a Mifal team: a Claude lead, a Codex reviewer, a Claude researcher, and an outside critic for the final plan. Every mark is an event from the build record and `git log`. The reviewer said HOLD five times, with 21 blocking findings across those rounds (a few were what remained of an earlier finding), and all were closed before the public release.

## How it works

```mermaid
flowchart LR
  ask[Your request] --> guide["Mifal Guide<br/>(a block in each wired agent's rules file)"]
  guide --> ew[engineering-workflow]
  ew --> am[Ask Matt selects the phase skill]
  am --> phase["build route: scope → grill → spec<br/>→ tickets → implement → review → retro"]
  phase -->|the agent runs it before each<br/>dispatch, review, acceptance| gate{validate_contracts.py}
  gate -->|refused, with the fix| phase
  gate -->|ok| phase
  ew -.->|team request| lead[team-lead]
  lead --> panes["Herdr panes:<br/>workers and a reviewer"]
  panes -->|receipts| gate
```

By default, Mifal's files live in your home folder: the engine in `~/.agents/mifal/`, the skills in `~/.agents/skills/`, and one Marked block in each successfully wired agent's rules file; an outside-home root needs `--allow-root-outside-home`, and Herdr's installation has its own effects described in INSTALL.md. [docs/INSTALL.md](docs/INSTALL.md) lists every write, and covers update and uninstall.

## Status

**Alpha.** The installer, update, uninstall, doctor and validator are covered by tests, run in CI on macOS under the system Python and the current python3. What a program checks, and what still relies on the agent following the Guide, is spelled out in [docs/TRUST.md](docs/TRUST.md).

## Support

This matrix is provisional. A cell is filled only from a recorded live check: a first session that quotes the Guide and lists Mifal's skills, and a lead that dispatches a task to that agent through Herdr and receives its reply.

| Platform | Claude Code | Codex | Droid | Pi | OpenCode |
|---|---|---|---|---|---|
| macOS | observed on one Mac | product wiring open | observed on one Mac | observed on one Mac | unverified |

Linux and Windows are not supported in this release. On one tested Mac, Claude Code (personal), Droid and Pi completed a recorded team workflow; Codex's product wiring is still open (a separate personal hook is not product support), and OpenCode is unverified.

Keep the clone you installed from: `mifal update` and `mifal doctor`'s completeness check read it. Deleting it leaves the installed skills and rules in place, but you would then clone Mifal again to update.

## Docs

- [docs/INSTALL.md](docs/INSTALL.md): what gets written, update and uninstall.
- [docs/TRUST.md](docs/TRUST.md): what is checked by a program, and what relies on the agent.
- [MAINTAINING.md](MAINTAINING.md): how upstream skill, Herdr and agent changes get into Mifal, and how Mifal's changes go back upstream.

## Credits

Mifal ships the work of others under their licences, recorded per component and skill in [`third_party/provenance.json`](third_party/provenance.json), each licence text beside its component (most in [`third_party/licenses/`](third_party/licenses), Impeccable's and LottieFiles' in `skills/frontend-design/references/interface/licenses/`) and summarised in [`NOTICE`](NOTICE): Matt Pocock's skills, DDD, Superpowers, agent-browser, Anthropic's frontend-design, Herdr's skill, Impeccable and LottieFiles motion-design. Mifal itself is MIT ([`LICENSE`](LICENSE)).

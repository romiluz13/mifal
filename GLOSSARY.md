# Glossary

**Guide**: the one generic set of always-on rules every Mifal session follows. It is installed once and delivered to each Harness.

**Harness**: a coding-agent tool Mifal wires into: Claude Code, Codex, Droid, Pi or OpenCode.

**Home**: one root folder of one Harness that Mifal serves. The Manifest keeps a list of Homes per Harness; `--home NAME=PATH` names one, and for a Harness with named Homes only those are served.

**Marked block**: the bounded text Mifal owns inside a file it shares with the user, such as a Harness's global rules file. Mifal adds, updates and removes only its own block.

**developer_instructions key**: the Guide as one Mifal-marked top-level key in a linked Codex Home's own `config.toml`. Mifal owns only the marked block's bytes and checks their integrity, never that a session loaded it.

**pending**: a recorded Codex Home whose own `SessionStart` hook may already deliver the Guide. Mifal writes no key, records the reason, warns in doctor and re-checks the Home on every run; it never edits the hook.

**unknown**: a recorded Codex Home whose hook file or `[hooks]` table Mifal cannot read. No key is written and doctor fails the Home with its fix.

**Manifest**: the record of every write an install made, and what each write displaced. Preview, doctor, update and uninstall all read it.

**Pool**: the shared folder of Agent Skills that every Harness reads, directly or through links.

**Personal layer**: a developer's own rules, kept outside Mifal's Marked block in each Harness's regular rules file. Mifal never writes through a linked rules file to reach it; a Codex Home that links to it is served through a marked key in its own `config.toml` (ADR 0005).

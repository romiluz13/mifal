# Glossary

**Guide**: the one generic set of always-on rules every Mifal session follows. It is installed once and delivered to each Harness.

**Harness**: a coding-agent tool Mifal wires into: Claude Code, Codex, Droid, Pi or OpenCode.

**Marked block**: the bounded text Mifal owns inside a file it shares with the user, such as a Harness's global rules file. Mifal adds, updates and removes only its own block.

**Manifest**: the record of every write an install made, and what each write displaced. Preview, doctor, update and uninstall all read it.

**Pool**: the shared folder of Agent Skills that every Harness reads, directly or through links.

**Personal layer**: a developer's own rules, kept outside Mifal's Marked block in each Harness's regular rules file. Mifal never writes through a linked rules file to reach it.

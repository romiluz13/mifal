# Contributing

Issues and pull requests are welcome. Mifal is alpha and macOS only.

- **A problem:** open an issue with the output of `mifal doctor`, your macOS and Python versions, and what you expected.
- **A change:** keep it to one purpose, and add or change a test that fails without it. `/bin/bash tests/run.sh -q` runs Mifal's own tests under macOS's Python 3.9 and your current `python3`; a change under `skills/` or `tools/` also needs the full `/bin/bash tests/run.sh`, which adds the shipped validator and adapter suites in a disposable home folder. Any argument, `-q` or a test name included, skips the shipped suites, and the script says so when it ends. Both Pythons must pass.
- **A vendored skill:** skills under `skills/` come from upstream projects, recorded in `third_party/provenance.json`. A fix that belongs upstream goes there first; [MAINTAINING.md](MAINTAINING.md) says how changes move in both directions.
- **The website:** `site/` is [the Mifal website](https://romiluz13.github.io/mifal/). The installer never copies it.

Security problems go through [SECURITY.md](SECURITY.md), not a public issue.

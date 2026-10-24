# One installer owns Mifal-managed writes; no plugin manifests in v1

Mifal ships as one installer and one `mifal` CLI that write the Pool, the engine and each Harness's Guide wiring, and record them in the Manifest. The Manifest also records the Herdr installation route, version and binary path; Herdr keeps its own installation lifecycle, and its own file changes are not a complete Manifest inventory. We considered native plugins (Claude, Codex) plus a smaller installer. For v1 we chose a single installer and rules-file delivery rather than separate native-plugin implementations; no native-plugin route ships here.

Consequence: no native `/plugin` front door in v1. Reopen if Claude-only users cannot get from the README to a green doctor without help; a launcher that delegates to the installer can add the front door.

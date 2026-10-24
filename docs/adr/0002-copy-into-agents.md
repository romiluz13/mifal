# Install by copying into ~/.agents, not by linking to the clone

The Pool goes to `~/.agents/skills` and the engine to `~/.agents/mifal`, as copies. `~/.agents/skills` is the folder most harnesses already read natively, and the validator, doctor and skills resolve their paths from it, so no relocation is needed. Copied rules and skills remain after the clone is removed, but `mifal update` and the recorded-revision completeness check in `mifal doctor` need the recorded clone (or a new clone and a reinstall); an edit in the clone takes effect only through `mifal update` or a reinstall.

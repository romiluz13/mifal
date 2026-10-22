# Doorbell instructions — implementer

The doorbell is one line, both a pane message and a durable record. Full
contract: `references/contracts/doorbell.md`.

```
<TYPE> <task> <payload>
```

Implementer-typical rings:

| When | Ring |
|------|------|
| Receipt filed, checks green | `DONE 7 .team/tasks/7.md` |
| Blocked with a specific question | `HELP 7 blocked-on auth token expiry semantics` |
| Needs a human approval | `HELD 7 waits-on approval to add dependency` |
| Stop rule hit | `STOPPED 7 two approaches failed, writeup filed` |

Rules that matter most:

- **Never ring DONE with an unverified claim.** If a done-means claim is
  untested, say so in the receipt — then ring. The receipt, not the ring,
  proves delivery.
- **Write the return file first, ring once.** If the lead is busy, try again
  every 2 minutes for up to 30 minutes, never typing into a busy pane; after
  that, leave the file — it stands alone.
- **Ring the attempt you are closing** on corrections: `DONE 7.2 ...` — a
  late `DONE 7` closes nothing while `7.2` is open.

Check any line before ringing:

```sh
python3 ~/.agents/skills/team-lead/scripts/validate_contracts.py doorbell --parse \
    "DONE 7 .team/tasks/7.md"
```

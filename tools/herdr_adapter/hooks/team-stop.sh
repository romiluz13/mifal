#!/bin/bash
# team-stop.sh <record-root>: Claude Stop feedback for one admitted team worker. TEMPLATE: install it per project.
#
# FEEDBACK ONLY. Every hook failure lets the agent through, so this can never be the gate: the lead accepts only
# through its own check (lead.review_receipt with the plan's verifiers), and nothing in lead.py or resume.py reads
# this hook's output or its log.
#
# Scope: HERDR_PANE_ID plus the record root fixed in the hook command. A session with no pane id, no record, or a pane
# that is neither a lead.py member with a task in flight nor pinned in <record-root>/assignments/ is left alone.
#
# Claude Code fires Stop at every turn end, not only at completion, so the hook gives feedback only when the worker
# claims completion. A claim is either a line of the last assistant message that starts "DONE <attempt>" (sentence
# punctuation . , : ; ! may follow the attempt), or a return file that already holds a Return section closing the attempt.
# Everything else is a mid-task stop: exit 0.
#   last message starts with HELP or HELD              -> exit 0 always (a question for the lead is not a completion)
#   any DONE line names the pane's attempt              -> a claim, whatever other attempts the message also names
#   DONE lines name only other attempts                 -> exit 0, one "attempt mismatch" line in the log
#
# A mid-task stop of an admitted worker that reports nothing (last message not starting HELP, HELD or STOPPED, no
# DONE line, no Return closing the attempt) also writes one QUIET event, schema 1, at
# <record-root>/quiet/<sha256 of the JSON array [session_id, prompt_id]>.json: type, owner, pane, attempt,
# session_id, prompt_id, reason "no report", waiting, and the UTC write time. Positive evidence of work wins: a
# running task or a non-empty session_crons list means no event at all, whatever shape the other key has. Otherwise
# waiting is none when background_tasks and session_crons are present lists holding nothing active ("running" is
# the only active status Claude Code 2.1.316 was captured sending), and unknown when either is absent or not a
# list, or a task holds a status this hook does not recognise. The event never blocks the stop: it is written
# atomically (a temp file in quiet/, then a hard link, so an existing event is never overwritten) and a failed
# write is only logged. One stop delivered twice, or retried with stop_hook_active, has
# the same (session_id, prompt_id) key, so it stays one event; a stop missing either id has no reliable identity:
# no event, one "unknown stop identity" log line. The event file is immutable and owned by this hook; nothing here
# reads it back or prompts anyone, and an unadmitted pane stays as silent as before.
#
# Mapping for a claimed completion, preflight verdict -> hook exit. The validator's own exit status is never
# forwarded: it exits 1 for an invalid receipt, and a hook exit of 1 is a non-blocking error, so forwarding it would
# pass every invalid receipt.
#   preflight-ok      -> exit 0   (exit 2 once only when the Stop payload lists background_tasks still running)
#   missing           -> exit 2   the precise errors on stderr; the worker sees them and may fix its return
#   cannot-evaluate   -> exit 0   one line in <record-root>/stop-hook.log; the worker is not told
#   anything else     -> exit 0   (crash, no JSON, missing interpreter or script, unknown verdict) logged the same way
# Early exit 0: stop_hook_active is true (the retry escape: the stop is allowed and the task stays unaccepted).
# This script never runs a plan verifier; preflight.py is read-only and runs none.
#
# Environment: TEAM_STOP_PYTHON (an absolute interpreter; never a version-manager shim), TEAM_STOP_PREFLIGHT.

RECORD="$1"
PYTHON="${TEAM_STOP_PYTHON:-/usr/bin/python3}"
PREFLIGHT="${TEAM_STOP_PREFLIGHT:-$HOME/.agents/mifal/tools/herdr_adapter/preflight.py}"
PANE="$HERDR_PANE_ID"

log() {
  [ -d "$RECORD" ] && printf '%s pane=%s %s\n' "$(date -u +%FT%TZ)" "$PANE" "$*" >> "$RECORD/stop-hook.log" 2>/dev/null
  return 0
}

[ -n "$PANE" ] && [ -n "$RECORD" ] && [ -d "$RECORD" ] || exit 0
[ -f "$RECORD/lead-state.json" ] || [ -d "$RECORD/assignments" ] || exit 0

payload="$(cat)"
[ -x "$PYTHON" ] || { log "cannot-evaluate: interpreter $PYTHON is not executable"; exit 0; }

flags="$(printf '%s' "$payload" | "$PYTHON" -I -c 'import json, re, sys
d = json.load(sys.stdin)
msg = d.get("last_assistant_message")
msg = msg if isinstance(msg, str) else ""
word = re.match(r"[A-Za-z]+", re.sub(r"^[\s`*_>#-]+", "", msg))
done = re.findall(r"(?m)^[\s`*_>#-]*DONE[ \t]+([0-9]+(?:\.[0-9]+)*)[.,:;!]*(?![\w.])", msg)
tasks = d.get("background_tasks")
print("active" if d.get("stop_hook_active") is True else "inactive",
      len(tasks) if isinstance(tasks, (list, str, dict)) else 0,
      word.group(0) if word else "-", ",".join(dict.fromkeys(done)) or "-")' 2>/dev/null)" ||
  { log "cannot-evaluate: unreadable Stop payload"; exit 0; }
set -- $flags
[ "$1" = active ] && exit 0
background="${2:-0}"
case "$3" in HELP|HELD) exit 0 ;; esac
said_done="${4:--}"   # every attempt a DONE line names, comma separated

request="$("$PYTHON" -I -c 'import json, sys
print(json.dumps({"command": "preflight", "params": {"record_root": sys.argv[1], "pane_id": sys.argv[2]}}))' "$RECORD" "$PANE" 2>/dev/null)" ||
  { log "cannot-evaluate: could not build the preflight request"; exit 0; }

# The preflight's exit status is deliberately ignored: only its typed verdict counts.
reply="$(printf '%s' "$request" | "$PYTHON" -B "$PREFLIGHT" 2>/dev/null)"

# First line: kind, the attempt the preflight judged, and whether the return already closes it (tab separated).
mapped="$(printf '%s' "$reply" | "$PYTHON" -I -c 'import json, sys
def head(kind, result=None):
    result = result if isinstance(result, dict) else {}
    print(kind, str(result.get("attempt") or "-"), "1" if result.get("closes") is True else "0", sep="\t")
try:
    result = json.load(sys.stdin)["result"]
    kind = result["verdict"]
    if kind == "preflight-ok":
        head("ok", result)
        print("")
    elif kind == "missing":
        head("missing", result)
        print("\n".join("- " + str(error) for error in result["errors"][:20])[:3000])
    elif kind == "cannot-evaluate":
        head("cannot")
        print(str(result.get("reason")) + ": " + str(result.get("detail", ""))[:300])
    else:
        head("other")
        print("unexpected verdict " + str(kind)[:80])
except Exception as error:
    head("other")
    print("unreadable preflight reply (" + error.__class__.__name__ + ")")' 2>/dev/null)"
IFS=$'\t' read -r kind judged closes <<< "${mapped%%$'\n'*}"
detail="${mapped#*$'\n'}"

# A mid-task stop is not a completion claim: leave it alone, silently.
if [ "$said_done" != - ]; then
  if [ "$judged" != - ]; then
    case ",$said_done," in
      *",$judged,"*) ;;
      *) log "attempt mismatch: the last message says DONE ${said_done//,/, DONE }, this pane is on attempt $judged"
         exit 0 ;;
    esac
  fi
elif [ "$closes" != 1 ]; then
  # The stop of an admitted worker that reported nothing: one QUIET event, then through (rules above).
  if [ "$judged" != - ] && [ "$3" != STOPPED ]; then
    outcome="$(printf '%s' "$payload" | "$PYTHON" -I -c '
import datetime, hashlib, json, os, sys, tempfile

record, pane, attempt = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    d = json.load(sys.stdin)
    session_id, prompt_id = d.get("session_id"), d.get("prompt_id")
    if not (isinstance(session_id, str) and session_id and isinstance(prompt_id, str) and prompt_id):
        print("unknown stop identity")
    else:
        tasks, crons = d.get("background_tasks"), d.get("session_crons")
        tasks_ok, crons_ok = isinstance(tasks, list), isinstance(crons, list)
        statuses = [task.get("status") if isinstance(task, dict) else None for task in tasks] if tasks_ok else []
        if "running" in statuses or (crons_ok and crons):
            waiting = "in flight"
        elif not (tasks_ok and crons_ok) or tasks:
            waiting = "unknown"
        else:
            waiting = "none"
        if waiting == "in flight":
            print("waiting")
        else:
            owner = "-"
            try:
                with open(os.path.join(record, "lead-state.json")) as state:
                    members = json.load(state).get("members") or {}
                owner = next((name for name, member in members.items()
                              if isinstance(member, dict) and member.get("pane_id") == pane), "-")
            except Exception:
                pass
            event = {"schema": 1, "type": "QUIET", "owner": owner, "pane": pane, "attempt": attempt,
                     "session_id": session_id, "prompt_id": prompt_id, "reason": "no report",
                     "waiting": waiting, "written_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
            event_id = hashlib.sha256(json.dumps([session_id, prompt_id]).encode("ascii")).hexdigest()
            quiet = os.path.join(record, "quiet")
            os.makedirs(quiet, exist_ok=True)
            final = os.path.join(quiet, event_id + ".json")
            if os.path.exists(final):
                print("skipped")
            else:
                fd, temp = tempfile.mkstemp(dir=quiet, prefix=".quiet-")
                try:
                    with os.fdopen(fd, "w") as handle:
                        json.dump(event, handle)
                        handle.flush()
                        os.fsync(handle.fileno())
                    try:
                        os.link(temp, final)
                        print("written")
                    except FileExistsError:
                        print("skipped")
                finally:
                    os.unlink(temp)
except Exception as error:
    print("write failed: " + error.__class__.__name__)
' "$RECORD" "$PANE" "$judged" 2>/dev/null)"
    case "$outcome" in
      written|skipped|waiting) ;;
      *) log "${outcome:-no outcome from the quiet-event write}" ;;
    esac
  fi
  exit 0
fi

case "$kind" in
  ok)
    if [ "$background" -gt 0 ] 2>/dev/null; then
      printf 'team-stop: %s background task(s) are still running; wait for them, then stop again.\n' "$background" >&2
      exit 2
    fi
    exit 0 ;;
  missing)
    printf 'team-stop: your return is not ready for the lead. Fix this, then stop again:\n%s\n' "$detail" >&2
    exit 2 ;;
  cannot)
    log "cannot-evaluate $detail"
    exit 0 ;;
  *)
    log "${detail:-no preflight reply}"
    exit 0 ;;
esac

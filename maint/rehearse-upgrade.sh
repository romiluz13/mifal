#!/bin/bash
# Release rehearsal in a disposable HOME with a stub binary for each of the five agents. It installs an older release
# the way a user did, with a rules file of the user's own for four of the agents and a skill of the user's own, updates
# with that old release's own code, checks what that update left (a known gap is reported, never passed over), updates
# with the new code, then publishes a synthetic next release that reserves one more skill name, plants a user skill
# under it and updates again. It then uninstalls, installs the candidate fresh, and rolls back to the older release by
# the documented path (uninstall, then install from a clone of the older tag). The tail is a multi-Home slice: the
# 0.2.x single-Home records are migrated by an update, a negative control proves the multi-Home check fails when one
# Home is not wired, then one fresh install serves two Claude and two Codex Homes, one of them linked and served
# through the marked config.toml key, an update moves every Home, and an exact clean uninstall leaves every Home
# byte for byte as before. Every check prints PASS or FAIL with the
# exit code of the command it checked; any FAIL makes the script exit 1. Run before a release.
# usage: maint/rehearse-upgrade.sh REPO FROM_TAG   (REPO is a path or URL; FROM_TAG is the older release to start from)
set -euo pipefail
[ $# -eq 2 ] || { echo "usage: $0 REPO FROM_TAG" >&2; exit 2; }
repo="$1" from="$2"
# A 0.2.x release predates OpenCode's rules file and the update guards: its install records OpenCode as skipped, and
# its own update moves a skill of mine under a newly reserved name instead of stopping. From 0.3.0 on, neither holds.
case "$from" in v0.[0-2].*) legacy=1 ;; *) legacy=0 ;; esac
case "$from" in v0.1.*) branch_following=1 ;; *) branch_following=0 ;; esac
home="$(mktemp -d "${TMPDIR:-/tmp}/mifal-rehearsal.XXXXXX")"
trap 'rm -rf "${home:?}"' EXIT
home="$(cd -P "$home" && pwd)"
python="$(python3 -B -I -c 'import sys; print(sys.executable)')"
mkdir -p "$home/stub" "$home/tmp"
ln -s "$python" "$home/stub/python3"
stub() { printf '#!/bin/sh\n[ "$1" = "--version" ] && echo "%s"\n' "$2" >"$home/stub/$1"; chmod +x "$home/stub/$1"; }
stub herdr "herdr 0.9.5"
for agent in claude codex droid pi opencode; do stub "$agent" "$agent 1.0.0"; done
run() { env -i HOME="$home" TMPDIR="$home/tmp" PATH="$home/stub:/usr/bin:/bin" \
  GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null LANG=en_US.UTF-8 TERM=dumb "$@"; }
git() { run /usr/bin/git "$@"; }
python3() { run "$home/stub/python3" -B "$@"; }
python3 -I -c '
import os, sys, tempfile
from pathlib import Path
home = Path(sys.argv[1]).resolve()
assert Path.home().resolve() == home
temporary = home / "tmp"
assert Path(tempfile.gettempdir()).resolve() == temporary
assert not any(k in os.environ for k in ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "PI_CODING_AGENT_DIR",
                                       "FACTORY_HOME_OVERRIDE", "OPENCODE_CONFIG_DIR", "XDG_CONFIG_HOME"))
print(f"PASS isolation: disposable HOME {home}; temporary writes under {temporary}; no inherited Homes")
' "$home"
all="--harness claude --harness codex --harness droid --harness pi --harness opencode"
rules="claude:.claude/CLAUDE.md codex:.codex/AGENTS.md droid:.factory/AGENTS.md pi:.pi/agent/AGENTS.md"
results="$home/results.txt" problems="" failures=0

summary() {
  [ ! -s "$results" ] || { echo "-- results"; sort -s -k2,2 "$results"; }
}
fail() { summary; echo "REHEARSAL FAILED: $*" >&2; exit 1; }
problem() { problems="$problems; $*"; }
# verdict LETTER TEXT EXIT: PASS when no problem was recorded since the last verdict, FAIL with the problems otherwise.
verdict() {
  if [ -z "$problems" ]; then echo "PASS ($1) $2 (exit $3)" >>"$results"
  else echo "FAIL ($1) $2 (exit $3)$problems" >>"$results"; failures=$((failures + 1)); fi
  problems=""
}
blocks() { local n; n="$(grep -c '^<!-- mifal:begin ' "$1" 2>/dev/null || true)"; echo "${n:-0}"; }
snap() {
  python3 -I -c '
import hashlib, os, sys
home = sys.argv[1]
for top in (".agents", ".claude", ".codex", ".factory", ".pi", ".config", ".local"):
    for root, dirs, files in os.walk(os.path.join(home, top)):
        dirs.sort()
        for name in sorted(files + [d for d in dirs if os.path.islink(os.path.join(root, d))]):
            path = os.path.join(root, name)
            rel = os.path.relpath(path, home)
            if os.path.islink(path):
                print(rel, "->", os.readlink(path))
            else:
                print(rel, hashlib.sha256(open(path, "rb").read()).hexdigest())
' "$home"
}
# Shell here-documents use scratch files outside this HOME on macOS; text checks use files inside it.
# opencode_named TEXT: a line that names OpenCode and the CLAUDE.md it stops reading.
opencode_named() {
  printf '%s\n' "$1" >"$home/opencode-note.txt"
  grep -i opencode "$home/opencode-note.txt" >"$home/opencode-lines.txt" || true
  grep -q 'CLAUDE.md' "$home/opencode-lines.txt"
}

if [ -d "$repo" ] && [ -n "$(git -C "$repo" status --porcelain)" ]; then
  echo "NOTE candidate uses committed HEAD; dirty worktree edits are excluded"
fi
git clone -q --bare --no-hardlinks "$repo" "$home/origin.git"
if ! start="$(git -C "$home/origin.git" rev-parse -q --verify "refs/tags/$from^{commit}")"; then
  case "$from" in
    v0.1.0) version_commit=f71698a19a33a1dd53a0e7e6eb9c134f06accbce ;;
    v0.1.1) version_commit=74cd732ffcda213b1ccc1a7358a3291a5d526460 ;;
    *) fail "GAP $from: no local release tag; the promised path was not rehearsed" ;;
  esac
  start="$(git -C "$home/origin.git" rev-parse -q --verify "$version_commit^{commit}")" || \
    fail "GAP $from: no local release tag or version commit $version_commit"
  [ "$(git -C "$home/origin.git" show "$start:VERSION")" = "${from#v}" ] || \
    fail "GAP $from: version commit $start does not hold VERSION ${from#v}"
  echo "NOTE $from: using version commit $start because its release tag is absent"
fi
for required in install.sh bin/mifal lib/mifal_cli.py; do
  git -C "$home/origin.git" cat-file -e "$start:$required" || \
    fail "GAP $from: required installer layout lacks $required; no replacement step was run"
done
# The candidate is REPO's checked-out revision, published as the private origin's main and release tag;
# a stale local main in REPO is never used.
git -C "$home/origin.git" update-ref refs/heads/main HEAD
git -C "$home/origin.git" symbolic-ref HEAD refs/heads/main
next="$(git -C "$home/origin.git" show main:VERSION)"
candidate="$(git -C "$home/origin.git" rev-parse main)"
# Only the disposable origin publishes this tree as a release, including when VERSION has not yet been bumped.
if [ "$branch_following" = 0 ]; then
  git -C "$home/origin.git" update-ref "refs/tags/v$next" "$candidate"
fi
git clone -q "$home/origin.git" "$home/clone"
git -C "$home/clone" checkout -q -B main "$start"
git -C "$home/clone" branch -q --set-upstream-to=origin/main main
for entry in $rules; do
  mkdir -p "$(dirname "$home/${entry#*:}")"
  echo "my own ${entry%%:*} rule" >"$home/${entry#*:}"
done
run /bin/bash "$home/clone/install.sh" $all >"$home/install.log" 2>&1 || { cat "$home/install.log"; fail "install of $from"; }
cat "$home/install.log"

mkdir -p "$home/.agents/skills/my-own-skill"
echo "my own skill" >"$home/.agents/skills/my-own-skill/SKILL.md"
ln -s "$home/.agents/skills/my-own-skill" "$home/.claude/skills/my-own-skill"
mifal="$home/.local/bin/mifal"

# audit REV [--complete]: every file REV's tree installs is installed byte-equal and owned in the Manifest with its
# hash. Prints the counts; with --complete a gap fails the rehearsal.
audit() {
  python3 -c '
import hashlib, io, json, subprocess, sys
from pathlib import Path
home, origin, rev, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
ENGINE = ("bin", "lib", "tools", "LICENSE", "NOTICE", "VERSION", "third_party")
IGNORED = {"__pycache__", ".DS_Store"}
git = lambda *a: subprocess.run(["git", "-C", origin, *a], capture_output=True, check=True).stdout
owned = {e["path"]: e for e in json.loads((home / ".agents/mifal/install-manifest.json").read_text())["entries"]}
want = {}
objects = {}
for item in git("ls-tree", "-r", "-z", rev).split(b"\0"):
    if not item:
        continue
    metadata, name = item.split(b"\t", 1)
    _file_mode, kind, oid = metadata.split()
    rel = name.decode()
    parts = rel.split("/")
    if kind != b"blob" or IGNORED & set(parts):
        continue
    if parts[0] in ENGINE:
        want[rel] = home / ".agents/mifal" / rel
    elif rel == "guide/AGENTS.md":
        want[rel] = home / ".agents/mifal/AGENTS.md"
    elif parts[0] == "skills" and len(parts) > 2:
        want[rel] = home / ".agents/skills" / "/".join(parts[1:])
    if rel in want:
        objects[rel] = oid
batch = subprocess.run(["git", "-C", origin, "cat-file", "--batch"],
                       input=b"\n".join(objects.values()) + b"\n", capture_output=True, check=True).stdout
stream, blobs = io.BytesIO(batch), {}
for rel, oid in objects.items():
    sha, kind, size = stream.readline().split()
    assert sha == oid and kind == b"blob", "unexpected Git batch response"
    blobs[rel] = stream.read(int(size))
    assert stream.read(1) == b"\n", "truncated Git batch response"
gaps = []
for rel, target in sorted(want.items()):
    blob = blobs[rel]
    entry = owned.get(str(target))
    if not target.is_file() or target.read_bytes() != blob:
        gaps.append(f"{rel}: not installed or not byte-equal")
    elif not entry or entry.get("sha256") != hashlib.sha256(blob).hexdigest():
        gaps.append(f"{rel}: not owned in the Manifest with its hash")
print(f"audit {rev}: {len(want) - len(gaps)} of {len(want)} files installed, byte-equal and owned; {len(gaps)} gap(s)")
for line in gaps[:12]:
    print("  " + line)
sys.exit(1 if gaps and mode == "--complete" else 0)
' "$home" "$home/origin.git" "$1" "${2:-}"
}

echo "-- first update, run by $from's own code"
run /bin/bash "$mifal" update --yes || fail "first update (old code)"
[ "$(cat "$home/.agents/mifal/VERSION")" = "$(git -C "$home/origin.git" show main:VERSION)" ] || fail "the first update did not land on main's VERSION"
[ "$(git -C "$home/clone" rev-parse HEAD)" = "$candidate" ] || fail "the old update did not land on the candidate commit"
if [ "$branch_following" = 1 ]; then
  echo "PASS branch-following selection: $from follows origin/main from a main branch initialized at $start"
  git -C "$home/origin.git" update-ref "refs/tags/v$next" "$candidate"
fi

echo "-- what the old code left, checked against the candidate's own tree"
audit main | tee "$home/gap.txt"
run /bin/bash "$mifal" doctor >"$home/doctor-gap.txt" 2>&1 || true
cat "$home/doctor-gap.txt"
if ! grep -q " 0 gap(s)" "$home/gap.txt"; then
  echo "(expected: $from's update does not install every file the candidate installs)"
  grep -q "^WARN engine: " "$home/doctor-gap.txt" || fail "doctor did not warn about the files the old update left out"
fi

echo "-- an update by the candidate's code: repairs the files $from's update left out and keeps the gone skipped OpenCode Home skipped"
snap >"$home/before.txt"
rc=0; out="$(run /bin/bash "$mifal" update --yes 2>&1)" || rc=$?
echo "$out"
update_codes=$rc update_out="$out"
if [ "$rc" -ne 0 ]; then
  opencode_named "$out" || fail "the update by the candidate's code stopped, and not on OpenCode's CLAUDE.md fallback"
  snap >"$home/after.txt"
  cmp -s "$home/before.txt" "$home/after.txt" || problem "the update that stopped changed files"
  echo "-- the same update with --overwrite-edits"
  rc=0; out="$(run /bin/bash "$mifal" update --yes --overwrite-edits 2>&1)" || rc=$?
  echo "$out"
  [ "$rc" -eq 0 ] || fail "the update with --overwrite-edits"
  update_out="$update_out
$out"
  update_codes="$update_codes, then $rc with --overwrite-edits"
fi
audit main --complete || fail "after the update the install is not the candidate, file for file"
run /bin/bash "$mifal" update --yes | grep -q "up to date" || fail "an update after the repair was not a no-op"
opencode="$home/.config/opencode/AGENTS.md"
if [ "$legacy" = 1 ]; then
  # 0.3.0: a recorded skipped Home whose folder is gone stays skipped on update, nothing created; naming it serves it.
  [ ! -e "$opencode" ] || problem "$opencode was created, but a skipped Home whose folder is gone stays skipped on update"
  printf '%s\n' "$update_out" >"$home/update-out.txt"
  grep -q "skip opencode: ~/.config/opencode no longer exists, so Mifal keeps it recorded as skipped and writes " \
    "$home/update-out.txt" || problem "the update does not keep the gone skipped OpenCode Home skipped, with its note"
  verdict b "the update repairs the files $from's update left out and keeps the gone skipped OpenCode Home skipped until it is named" "$update_codes"
else
  [ "$(blocks "$opencode")" = 1 ] || problem "$opencode does not hold exactly one Mifal block after the update"
  verdict b "the update repairs the files $from's update left out and keeps OpenCode served" "$update_codes"
fi

echo "-- a synthetic next release that reserves one more skill name, and an unreleased commit, then an update by the new code"
git clone -q "$home/origin.git" "$home/work"
work_git() { git -C "$home/work" -c user.name=rehearsal -c user.email=rehearsal@example.com "$@"; }
for existing in "$home"/work/skills/*/; do cp -R "$existing" "$home/work/skills/rehearsal-new-skill"; break; done
echo "99.0.0" >"$home/work/VERSION"
work_git add skills
work_git commit -q -am "release 99.0.0"
work_git tag v99.0.0
echo "unreleased" >"$home/work/UNRELEASED"
work_git add UNRELEASED
work_git commit -q -m "after the release"
work_git push -q origin main v99.0.0
git -C "$home/origin.git" ls-tree --name-only "v$next" skills/ >"$home/skills-before.txt"
git -C "$home/origin.git" ls-tree --name-only v99.0.0 skills/ >"$home/skills-next.txt"
reserved="$({ diff "$home/skills-before.txt" "$home/skills-next.txt" || true; } | sed -n 's#^> skills/##p')"
[ -n "$reserved" ] && [ "$(echo "$reserved" | wc -l)" -eq 1 ] || fail "could not pick the one skill name v99.0.0 newly reserves"
echo "a skill of mine under a name the next release reserves" >"$home/user-skill.md"
mkdir -p "$home/.agents/skills/$reserved"
cp "$home/user-skill.md" "$home/.agents/skills/$reserved/SKILL.md"
ln -s "$home/.agents/skills/$reserved" "$home/.claude/skills/$reserved"
snap >"$home/before.txt"
rc=0; out="$(run /bin/bash "$mifal" update --yes 2>&1)" || rc=$?
echo "$out"
update_codes=$rc
[ "$rc" -ne 0 ] || problem "the update exited 0, so it took over $reserved instead of stopping"
printf '%s\n' "$out" >"$home/update-out.txt"
grep -q "$reserved" "$home/update-out.txt" || problem "the output does not name $reserved"
if [ "$rc" -ne 0 ]; then
  snap >"$home/after.txt"
  cmp -s "$home/before.txt" "$home/after.txt" || problem "the update that stopped changed files"
  echo "-- the same update with --overwrite-edits"
  rc=0; out="$(run /bin/bash "$mifal" update --yes --overwrite-edits 2>&1)" || rc=$?
  echo "$out"
  [ "$rc" -eq 0 ] || problem "update --overwrite-edits exited $rc"
  update_codes="$update_codes, then $rc with --overwrite-edits"
  saved="$(grep -rlx -F -f "$home/user-skill.md" "$home/.agents/mifal/backup" 2>/dev/null || true)"
  [ -n "$saved" ] || problem "your copy of $reserved is not under ~/.agents/mifal/backup"
  git -C "$home/origin.git" show "v99.0.0:skills/$reserved/SKILL.md" | cmp -s - "$home/.agents/skills/$reserved/SKILL.md" ||
    problem "the release's $reserved is not installed"
  [ "$(cd -P "$home/.claude/skills/$reserved" && pwd)" = "$home/.agents/skills/$reserved" ] ||
    problem "~/.claude/skills/$reserved does not lead to the Pool"
fi
applied_rc=$rc
rc=0; run /bin/bash "$mifal" doctor >"$home/doctor-final.txt" 2>&1 || rc=$?
cat "$home/doctor-final.txt"
doctor_rc=$rc
grep -Eq '^note .*(backup|saved)' "$home/doctor-final.txt" || problem "doctor shows no note about the saved copy"
! grep -Eq '^WARN .*(backup|saved)' "$home/doctor-final.txt" || problem "doctor warns about the saved copy"
verdict d "update stops on $reserved, a name the next release reserves and a skill of mine has; --overwrite-edits saves my copy" "$update_codes"
[ "$(cat "$home/.agents/mifal/VERSION")" = "99.0.0" ] || fail "the new code did not install the newest release"
[ "$(git -C "$home/clone" rev-parse HEAD)" = "$(git -C "$home/origin.git" rev-parse v99.0.0^{commit})" ] || fail "the clone is not at the release"
[ ! -e "$home/clone/UNRELEASED" ] || fail "an unreleased commit was offered"
audit v99.0.0 --complete || fail "after the synthetic release the install is not that release, file for file"
run /bin/bash "$mifal" update --yes | grep -q "up to date" || fail "a second update was not a no-op"
[ "$(cat "$home/.agents/skills/my-own-skill/SKILL.md")" = "my own skill" ] || fail "the user's own skill changed"

for entry in $rules; do
  file="$home/${entry#*:}"
  [ "$(blocks "$file")" = 1 ] || problem "$file does not hold exactly one Mifal block"
  grep -qx "my own ${entry%%:*} rule" "$file" || problem "my line is gone from $file"
done
[ ! -f "$opencode" ] || [ "$(blocks "$opencode")" = 1 ] || problem "$opencode does not hold exactly one Mifal block"
verdict a "each served agent's rules file holds exactly one Mifal block and my own line" "$applied_rc"

! grep -h '^PASS .*natively' "$home/doctor-gap.txt" "$home/doctor-final.txt" || problem "doctor passes a native-reading claim it did not check"
[ "$doctor_rc" -eq 0 ] || problem "doctor exited $doctor_rc after the update"
if [ "$legacy" = 1 ]; then
  grep -i opencode "$home/doctor-gap.txt" | grep -qi 'not served' || problem "doctor does not list OpenCode as detected but not served while it is"
  verdict c "doctor claims no unchecked native reading, lists the agent it does not serve, and is clean after the update" "$doctor_rc"
else
  verdict c "doctor claims no unchecked native reading and is clean after the update" "$doctor_rc"
fi

echo "KNOWN LIMIT: a user's Claude link recorded as Mifal's by 0.3.0 or 0.3.1 is removed; its Pool skill is restored."
link_saved="$(python3 -B -c 'import json, sys
entries = json.load(open(sys.argv[1]))["entries"]
link = sys.argv[2]
if any(e["kind"] == "backup" and e["path"] == link for e in entries):
    print("saved")
elif any(e["kind"] == "symlink" and e["path"] == link for e in entries):
    print("recorded")
else:
    print("unknown")' "$home/.agents/mifal/install-manifest.json" "$home/.claude/skills/$reserved")"
echo "-- uninstall"
rc=0; run /bin/bash "$mifal" uninstall >"$home/uninstall.log" 2>&1 || rc=$?
cat "$home/uninstall.log"
[ "$rc" -eq 0 ] || problem "uninstall exited $rc"
for entry in $rules; do
  file="$home/${entry#*:}"
  grep -qx "my own ${entry%%:*} rule" "$file" || problem "my line is gone from $file"
  ! grep -q 'mifal:begin' "$file" || problem "a Mifal block is left in $file"
done
[ ! -f "$opencode" ] || ! grep -q 'mifal:begin' "$opencode" || problem "a Mifal block is left in $opencode"
[ "$(cat "$home/.agents/skills/my-own-skill/SKILL.md")" = "my own skill" ] || problem "uninstall removed the user's own skill"
cmp -s "$home/user-skill.md" "$home/.agents/skills/$reserved/SKILL.md" || problem "my $reserved skill was not restored"
if [ "$link_saved" = saved ]; then
  [ -L "$home/.claude/skills/$reserved" ] && \
    [ "$(cd -P "$home/.claude/skills/$reserved" 2>/dev/null && pwd)" = "$home/.agents/skills/$reserved" ] || \
    problem "restored Claude link for $reserved does not lead to the Pool"
elif [ "$link_saved" = recorded ]; then
  [ ! -e "$home/.claude/skills/$reserved" ] && [ ! -L "$home/.claude/skills/$reserved" ] || \
    problem "the recorded Mifal link for $reserved was not removed"
  echo "KNOWN LIMIT (e): $reserved link has no saved copy in the Manifest; recorded link removed, Pool skill restored."
else
  problem "Claude link ownership for $reserved is not recorded"
fi
verdict e "uninstall leaves my rules lines and my skills" "$rc"

echo "-- a fresh install of the candidate"
git -C "$home/clone" checkout -q -B main "$candidate"
rc=0; out="$(run /bin/bash "$home/clone/install.sh" $all 2>&1)" || rc=$?
echo "$out"
[ "$rc" -eq 0 ] || problem "the fresh install exited $rc"
[ -f "$opencode" ] || problem "$opencode was not written"
[ ! -f "$opencode" ] || [ "$(blocks "$opencode")" = 1 ] || problem "$opencode does not hold exactly one Mifal block"
opencode_named "$out" || problem "the install output has no line naming OpenCode and the CLAUDE.md it stops reading"
verdict b "a fresh install writes ~/.config/opencode/AGENTS.md and names the CLAUDE.md OpenCode stops reading" "$rc"

echo "-- rollback to $from: uninstall, then install from a clone of $from"
# The agents $from's own installer wired are the ones to bring back: it may skip an agent that the candidate serves.
served=""
for pair in claude:"Claude Code" codex:Codex droid:Droid pi:Pi opencode:OpenCode; do
  case ", $(sed -n 's/^Wired: //p' "$home/install.log")," in *", ${pair#*:},"*) served="$served --harness ${pair%%:*}";; esac
done
rc=0; run /bin/bash "$mifal" uninstall >"$home/uninstall-rollback.log" 2>&1 || rc=$?
[ "$rc" -eq 0 ] || problem "the uninstall before the rollback exited $rc"
git -C "$home/clone" checkout -q -B main "$start"
rc=0; run /bin/bash "$home/clone/install.sh" $served >"$home/rollback.log" 2>&1 || rc=$?
cat "$home/rollback.log"
[ "$rc" -eq 0 ] || problem "the install of $from exited $rc"
[ "$(run /bin/bash "$mifal" version)" = "mifal ${from#v}" ] || problem "the installed version is not $from"
for entry in $rules; do
  file="$home/${entry#*:}"
  [ "$(blocks "$file")" = 1 ] && grep -q "^<!-- mifal:begin version=${from#v} " "$file" || problem "$file does not hold one Mifal block of $from"
  grep -qx "my own ${entry%%:*} rule" "$file" || problem "my line is gone from $file"
done
[ "$(cat "$home/.agents/skills/my-own-skill/SKILL.md")" = "my own skill" ] || problem "my own skill changed"
[ -L "$home/.claude/skills/$reserved" ] && \
  [ "$(cd -P "$home/.claude/skills/$reserved" 2>/dev/null && pwd)" = "$home/.agents/skills/$reserved" ] || \
  problem "restored Claude link for $reserved does not lead to the Pool"
rc=0; run /bin/bash "$mifal" doctor >"$home/doctor-rollback.txt" 2>&1 || rc=$?
cat "$home/doctor-rollback.txt"
if [ "$rc" -ne 0 ]; then
  echo "FAIL rollback to $from: doctor exited $rc after this rehearsal's uninstall and historical reinstall:"
  grep '^FAIL ' "$home/doctor-rollback.txt" || true
fi
[ "$rc" -eq 0 ] || problem "doctor exited $rc after the rollback"
verdict f "rollback to $from by uninstall and install from its clone leaves doctor clean and my files in place" "$rc"

echo "-- an update from $from's single-Home records: every default Home keeps its Guide"
rc=0; out="$(run /bin/bash "$mifal" update --yes 2>&1)" || rc=$?
echo "$out"
update_codes="$rc"
if [ "$rc" -ne 0 ] && [ "$legacy" = 0 ]; then
  printf '%s\n' "$out" >"$home/update-out.txt"
  grep -q "^~/.agents/skills/$reserved: exists and was not installed by Mifal" "$home/update-out.txt" \
    || problem "the update run by $from's own code stopped, and not on $reserved, the name v99.0.0 reserves"
  rc=0; out="$(run /bin/bash "$mifal" update --yes --overwrite-edits 2>&1)" || rc=$?
  echo "$out"
  update_codes="$update_codes on $reserved, then $rc with --overwrite-edits"
fi
[ "$rc" -eq 0 ] || problem "the update run by $from's own code exited $rc"
[ "$(cat "$home/.agents/mifal/VERSION")" = "99.0.0" ] || problem "the update run by $from's own code did not land on v99.0.0"
rc2=0; out2="$(run /bin/bash "$mifal" update --yes 2>&1)" || rc2=$?
echo "$out2"
update_codes="$update_codes, then $rc2"
if [ "$rc2" -ne 0 ]; then
  opencode_named "$out2" || problem "the second update stopped, and not on OpenCode's CLAUDE.md fallback"
  rc2=0; out3="$(run /bin/bash "$mifal" update --yes --overwrite-edits 2>&1)" || rc2=$?
  echo "$out3"
  update_codes="$update_codes, then $rc2 with --overwrite-edits"
fi
[ "$rc2" -eq 0 ] || problem "the update that migrates $from's records exited $rc2"
for entry in $rules; do
  file="$home/${entry#*:}"
  [ "$(blocks "$file")" = 1 ] || problem "$file does not hold exactly one Mifal block after the migrated update"
  grep -q "^<!-- mifal:begin version=99.0.0 " "$file" || problem "$file does not hold the new release's block"
  grep -qx "my own ${entry%%:*} rule" "$file" || problem "my line is gone from $file"
done
verdict g "an update from $from's single-Home records keeps every default Home served" "$update_codes"

echo "-- uninstall before the multi-Home slice"
rc=0; run /bin/bash "$mifal" uninstall >"$home/uninstall-mh0.log" 2>&1 || rc=$?
cat "$home/uninstall-mh0.log"
[ "$rc" -eq 0 ] || problem "the uninstall before the multi-Home slice exited $rc"
for entry in $rules; do
  file="$home/${entry#*:}"
  grep -qx "my own ${entry%%:*} rule" "$file" || problem "my line is gone from $file"
  ! grep -q 'mifal:begin' "$file" || problem "a Mifal block is left in $file"
done
rm -rf "$home/.agents/skills/$reserved" "$home/.claude/skills/$reserved"

echo "-- a multi-Home layout: two Claude and two Codex Homes, one linked, and a stray reader of the shared file"
mh_rules="claude-work:.claude-work/CLAUDE.md claude-second:.claude-second/CLAUDE.md codex-work:.codex-work/AGENTS.md"
for entry in $mh_rules; do
  mkdir -p "$(dirname "$home/${entry#*:}")"
  echo "my own ${entry%%:*} rule" >"$home/${entry#*:}"
done
mkdir -p "$home/.ai" "$home/.codex-second" "$home/.codex-stray"
echo "my shared rules" >"$home/.ai/AGENTS.md"
ln -s "$home/.ai/AGENTS.md" "$home/.codex-second/AGENTS.md"
ln -s "$home/.ai/AGENTS.md" "$home/.codex-stray/AGENTS.md"
printf 'model = "gpt-6.1"\nmodel_provider = "openai"\n' >"$home/.codex-second/config.toml"
cp "$home/.codex-second/config.toml" "$home/config-original.toml"
keyblocks() { local n; n="$(grep -c '^# mifal:begin ' "$1" 2>/dev/null || true)"; echo "${n:-0}"; }
# strip_key FILE: the file's bytes with Mifal's marked key block taken out.
strip_key() { awk '/^# mifal:begin /{owned=1} owned{if (/^# mifal:end$/) {owned=0}; next} {print}' "$1"; }
mh_snap() {
  python3 -I -c '
import hashlib, os, sys
home = sys.argv[1]
for top in sys.argv[2:]:
    for root, dirs, files in os.walk(os.path.join(home, top)):
        dirs.sort()
        for name in sorted(files + [d for d in dirs if os.path.islink(os.path.join(root, d))]):
            path = os.path.join(root, name)
            rel = os.path.relpath(path, home)
            if os.path.islink(path):
                print(rel, "->", os.readlink(path))
            else:
                print(rel, hashlib.sha256(open(path, "rb").read()).hexdigest())
' "$home" "$@"
}
# mh_assert [VERSION]: every named Home is served, read from the files on disk, not from the installer's records.
mh_assert() {
  local version="${1:-}" file claude cfg="$home/.codex-second/config.toml"
  for entry in $mh_rules; do
    file="$home/${entry#*:}"
    [ "$(blocks "$file")" = 1 ] || problem "$file does not hold exactly one Mifal block"
    grep -qx "my own ${entry%%:*} rule" "$file" || problem "my line is gone from $file"
    [ -z "$version" ] || grep -q "^<!-- mifal:begin version=$version " "$file" ||
      problem "$file does not hold the $version block"
  done
  for claude in .claude-work .claude-second; do
    [ -L "$home/$claude/skills/engineering-workflow" ] || problem "~/$claude holds no engineering-workflow link"
    [ "$(cd -P "$home/$claude/skills/engineering-workflow" 2>/dev/null && pwd)" = "$home/.agents/skills/engineering-workflow" ] ||
      problem "~/$claude/skills/engineering-workflow does not lead to the Pool"
  done
  [ "$(readlink "$home/.codex-second/AGENTS.md")" = "$home/.ai/AGENTS.md" ] ||
    problem "the linked rules file ~/.codex-second/AGENTS.md was replaced"
  [ "$(cat "$home/.ai/AGENTS.md")" = "my shared rules" ] || problem "the shared file ~/.ai/AGENTS.md changed"
  [ "$(readlink "$home/.codex-stray/AGENTS.md")" = "$home/.ai/AGENTS.md" ] || problem "the stray reader's link changed"
  [ "$(keyblocks "$cfg")" = 1 ] || problem "$cfg does not hold exactly one marked key"
  head -n 1 "$cfg" | grep -q '^# mifal:begin ' || problem "the marked key is not at the top of $cfg"
  strip_key "$cfg" >"$home/config-stripped.toml"
  cmp -s "$home/config-stripped.toml" "$home/config-original.toml" ||
    problem "$cfg keeps bytes outside the marked key differently than before"
  [ -z "$version" ] || grep -q "^# mifal:begin version=$version " "$cfg" || problem "$cfg does not hold the $version key"
}

# mh_expected PROBLEMS: true for exactly the three diagnostics a missing ~/.claude-second Home must produce,
# and nothing else: its rules file without a Mifal block, its missing skills link, and that link's Pool
# resolution. Not any failure that names the Home.
mh_expected() {
  local item count=0 block=0 link=0 pool=0
  printf '%s\n' "${1};" >"$home/mh-problems.txt"
  while IFS= read -rd ';' item; do
    item="${item# }"
    [ -n "$item" ] || continue
    case "$item" in
      *".claude-second/CLAUDE.md does not hold exactly one Mifal block") block=1 ;;
      *".claude-second holds no engineering-workflow link") link=1 ;;
      *".claude-second/skills/engineering-workflow does not lead to the Pool") pool=1 ;;
      *) return 1 ;;
    esac
    count=$((count + 1))
  done <"$home/mh-problems.txt"
  [ "$count" -eq 3 ] && [ "$block" -eq 1 ] && [ "$link" -eq 1 ] && [ "$pool" -eq 1 ]
}

echo "-- negative control: the multi-Home check must fail when one Home is not wired"
git -C "$home/clone" checkout -q -B main "$candidate"
rc=0; run /bin/bash "$home/clone/install.sh" --harness claude --harness codex \
  --home "claude=$home/.claude-work" --home "codex=$home/.codex-work" --home "codex=$home/.codex-second" \
  >"$home/install-control.log" 2>&1 || rc=$?
cat "$home/install-control.log"
[ "$rc" -eq 0 ] || problem "the control install exited $rc"
# The control's problems are read beside anything earlier: nothing is reset here, so an earlier failure
# (the pre-slice uninstall, a nonzero control install) still fails the verdict instead of being wiped.
before="$problems"
mh_assert
control="$problems"
added="${control#"$before"}"
if [ -z "$added" ]; then
  problem "the multi-Home check passed although ~/.claude-second was not named, so the control is vacuous"
elif ! mh_expected "$added"; then
  problem "the multi-Home check failed without ~/.claude-second wired, but on:$added"
else
  # Only the three expected diagnostics are dropped: they are the control's point, not a failure of the
  # candidate. Everything earlier stays, and the verdict sees it.
  problems="$before"
  echo "(expected: without ~/.claude-second named, the multi-Home check reports exactly:$added)"
fi
rc=0; run /bin/bash "$mifal" uninstall >"$home/uninstall-control.log" 2>&1 || rc=$?
cat "$home/uninstall-control.log"
[ "$rc" -eq 0 ] || problem "the uninstall of the control install exited $rc"
cmp -s "$home/.codex-second/config.toml" "$home/config-original.toml" ||
  problem "the control uninstall left ~/.codex-second/config.toml changed"
verdict h "the multi-Home check fails when one Home is not wired" "$rc"

echo "-- a fresh multi-Home install of the candidate"
mh_snap .claude-work .claude-second .codex-work .codex-second .ai .codex-stray >"$home/mh-before.txt"
rc=0; out="$(run /bin/bash "$home/clone/install.sh" --harness claude --harness codex \
  --home "claude=$home/.claude-work" --home "claude=$home/.claude-second" \
  --home "codex=$home/.codex-work" --home "codex=$home/.codex-second" 2>&1)" || rc=$?
echo "$out"
[ "$rc" -eq 0 ] || problem "the multi-Home install exited $rc"
printf '%s\n' "$out" >"$home/install-out.txt"
grep -qx "Wired: Claude Code, Codex" "$home/install-out.txt" || problem "the install does not report exactly Claude Code and Codex wired"
grep -q "key ~/.codex-second/config.toml: developer_instructions" "$home/install-out.txt" ||
  problem "the install output does not name the marked key"
mh_assert
rc=0; run /bin/bash "$mifal" doctor >"$home/doctor-mh.txt" 2>&1 || rc=$?
cat "$home/doctor-mh.txt"
[ "$rc" -eq 0 ] || problem "doctor exited $rc on the multi-Home install"
for line in "PASS guide claude: block in ~/.claude-work/CLAUDE.md" \
            "PASS guide claude: block in ~/.claude-second/CLAUDE.md" \
            "PASS guide codex: block in ~/.codex-work/AGENTS.md" \
            "PASS guide codex: Mifal's developer_instructions key in ~/.codex-second/config.toml, as installed" \
            "note ~/.codex-stray reads ~/.ai/AGENTS.md, not served by this install"; do
  grep -qx "$line" "$home/doctor-mh.txt" || problem "doctor does not print: $line"
done
verdict i "one install serves two Claude and two Codex Homes, the linked one through the marked key, and doctor names each Home and the stray reader" "$rc"

echo "-- an update moves every Home to the synthetic release"
rc=0; out="$(run /bin/bash "$mifal" update --yes 2>&1)" || rc=$?
echo "$out"
[ "$rc" -eq 0 ] || problem "the update over every Home exited $rc"
[ "$(cat "$home/.agents/mifal/VERSION")" = "99.0.0" ] || problem "the multi-Home update did not land on v99.0.0"
mh_assert 99.0.0
verdict j "mifal update moves every recorded Home to the new release and keeps the config's other bytes" "$rc"

echo "-- an exact clean uninstall of every Home"
rc=0; run /bin/bash "$mifal" uninstall >"$home/uninstall-mh.log" 2>&1 || rc=$?
cat "$home/uninstall-mh.log"
[ "$rc" -eq 0 ] || problem "the multi-Home uninstall exited $rc"
mh_snap .claude-work .claude-second .codex-work .codex-second .ai .codex-stray >"$home/mh-after.txt"
cmp -s "$home/mh-before.txt" "$home/mh-after.txt" ||
  problem "the multi-Home uninstall left a Home different from before the install"
verdict k "mifal uninstall leaves every Home byte for byte as before the install" "$rc"

echo "-- finish installed at the candidate tree"
git -C "$home/clone" checkout -q -B main "$candidate"
run /bin/bash "$home/clone/install.sh" $all || fail "final candidate install"
audit "$candidate" --complete || fail "final candidate payload"
python3 -I -c '
import json, sys
from pathlib import Path
data = json.loads((Path(sys.argv[1]) / ".agents/mifal/install-manifest.json").read_text())
assert data["source"]["revision"] == sys.argv[2], "final Manifest does not identify the candidate"
print(f"PASS candidate: {sys.argv[2]}")
' "$home" "$candidate"
run /bin/bash "$mifal" doctor >"$home/doctor-candidate.txt" 2>&1 || { cat "$home/doctor-candidate.txt"; fail "final candidate doctor"; }
cat "$home/doctor-candidate.txt"
! grep -Eq '^(FAIL |WARN engine:)' "$home/doctor-candidate.txt" || fail "final candidate doctor is not healthy"
echo "PASS candidate doctor: exit 0, no FAIL or missing-payload warning (stub Harnesses and Herdr)"

summary
if [ "$failures" -ne 0 ]; then
  echo "REHEARSAL FAILED: $failures check(s) failed" >&2
  exit 1
fi
echo "REHEARSAL OK: $from -> main -> v99.0.0 (synthetic), then fresh $next and back to $from, then a multi-Home slice: single-Home records migrated, two Claude and two Codex Homes served by one install (negative control red), every Home updated, exact uninstall; ends at candidate $candidate with doctor exit 0. Named GAP paths above are not passed."

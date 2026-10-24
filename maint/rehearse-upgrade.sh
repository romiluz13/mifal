#!/bin/bash
# Upgrade rehearsal in a disposable HOME: install an older release the way a user did, add a skill of the user's own,
# update with that old release's own code, check what that update left (a known gap is reported, never passed over),
# repair it with the new code, then publish a synthetic next release and an unreleased commit in a private copy of the
# remote and update again with the new code. Run before a release.
# usage: maint/rehearse-upgrade.sh REPO FROM_TAG   (REPO is a path or URL; FROM_TAG is the older release to start from)
set -euo pipefail
[ $# -eq 2 ] || { echo "usage: $0 REPO FROM_TAG" >&2; exit 2; }
repo="$1" from="$2"
home="$(mktemp -d)"
trap 'rm -rf "${home:?}"' EXIT
home="$(cd -P "$home" && pwd)"
python="$(dirname "$(command -v python3)")"
mkdir -p "$home/stub"
printf '#!/bin/sh\n[ "$1" = "--version" ] && echo "herdr 0.9.5"\n' >"$home/stub/herdr"
chmod +x "$home/stub/herdr"
run() { env -i HOME="$home" PATH="$home/stub:$python:/usr/bin:/bin" LANG=en_US.UTF-8 TERM=dumb "$@"; }
fail() { echo "REHEARSAL FAILED: $*" >&2; exit 1; }

git clone -q --bare "$repo" "$home/origin.git"
# The candidate is REPO's checked-out revision, published as the private origin's main and, when it is a new
# version, as its release tag, the way a release is published; a stale local main in REPO is never used.
git -C "$home/origin.git" update-ref refs/heads/main HEAD
git -C "$home/origin.git" symbolic-ref HEAD refs/heads/main
next="$(git -C "$home/origin.git" show main:VERSION)"
git -C "$home/origin.git" rev-parse -q --verify "refs/tags/v$next" >/dev/null || git -C "$home/origin.git" tag "v$next" main
git clone -q "$home/origin.git" "$home/clone"
git -C "$home/clone" checkout -q -B main "$from"
git -C "$home/clone" branch -q --set-upstream-to=origin/main main
run /bin/bash "$home/clone/install.sh" --harness claude >"$home/install.log" 2>&1 || { cat "$home/install.log"; fail "install of $from"; }

mkdir -p "$home/.agents/skills/my-own-skill"
echo "my own skill" >"$home/.agents/skills/my-own-skill/SKILL.md"
ln -s "$home/.agents/skills/my-own-skill" "$home/.claude/skills/my-own-skill"
mifal="$home/.local/bin/mifal"

# audit REV [--complete]: every file REV's tree installs is installed byte-equal and owned in the Manifest with its
# hash. Prints the counts; with --complete a gap fails the rehearsal.
audit() {
  python3 - "$home" "$home/origin.git" "$1" "${2:-}" <<'PY'
import hashlib, json, subprocess, sys
from pathlib import Path
home, origin, rev, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
ENGINE = ("bin", "lib", "tools", "LICENSE", "NOTICE", "VERSION", "third_party")
IGNORED = {"__pycache__", ".DS_Store"}
git = lambda *a: subprocess.run(["git", "-C", origin, *a], capture_output=True, check=True).stdout
owned = {e["path"]: e for e in json.loads((home / ".agents/mifal/install-manifest.json").read_text())["entries"]}
want = {}
for rel in git("ls-tree", "-r", "-z", "--name-only", rev).decode().split("\0"):
    parts = rel.split("/")
    if not rel or IGNORED & set(parts):
        continue
    if parts[0] in ENGINE:
        want[rel] = home / ".agents/mifal" / rel
    elif rel == "guide/AGENTS.md":
        want[rel] = home / ".agents/mifal/AGENTS.md"
    elif parts[0] == "skills" and len(parts) > 2:
        want[rel] = home / ".agents/skills" / "/".join(parts[1:])
gaps = []
for rel, target in sorted(want.items()):
    blob = git("show", f"{rev}:{rel}")
    entry = owned.get(str(target))
    if not target.is_file() or target.read_bytes() != blob:
        gaps.append(f"{rel}: not installed or not byte-equal")
    elif not entry or entry.get("sha256") != hashlib.sha256(blob).hexdigest():
        gaps.append(f"{rel}: not owned in the Manifest with its hash")
print(f"audit {rev}: {len(want) - len(gaps)} of {len(want)} files installed, byte-equal and owned; {len(gaps)} gap(s)")
for line in gaps[:12]:
    print("  " + line)
sys.exit(1 if gaps and mode == "--complete" else 0)
PY
}

echo "-- first update, run by $from's own code"
run /bin/bash "$mifal" update --yes || fail "first update (old code)"
[ "$(cat "$home/.agents/mifal/VERSION")" = "$(git -C "$home/origin.git" show main:VERSION)" ] || fail "the first update did not land on main's VERSION"

echo "-- what the old code left, checked against the candidate's own tree"
audit main | tee "$home/gap.txt"
if ! grep -q " 0 gap(s)" "$home/gap.txt"; then
  echo "(expected: $from's update does not install every file the candidate installs)"
  run /bin/bash "$mifal" doctor >"$home/doctor-gap.txt" 2>&1 || fail "doctor failed on the intermediate state"
  cat "$home/doctor-gap.txt"
  grep -q "^WARN engine: " "$home/doctor-gap.txt" || fail "doctor did not warn about the files the old update left out"
  echo "-- a second update by the candidate's code repairs it"
  run /bin/bash "$mifal" update --yes || fail "the repair update"
fi
audit main --complete || fail "after the update the install is not the candidate, file for file"
run /bin/bash "$mifal" update --yes | grep -q "up to date" || fail "an update after the repair was not a no-op"

echo "-- a synthetic next release and an unreleased commit, then an update by the new code"
git clone -q "$home/origin.git" "$home/work"
git="git -C $home/work -c user.name=rehearsal -c user.email=rehearsal@example.com"
echo "99.0.0" >"$home/work/VERSION"
$git commit -q -am "release 99.0.0"
$git tag v99.0.0
echo "unreleased" >"$home/work/UNRELEASED"
$git add UNRELEASED
$git commit -q -m "after the release"
$git push -q origin main v99.0.0
run /bin/bash "$mifal" update --yes || fail "update to the synthetic release (new code)"
[ "$(cat "$home/.agents/mifal/VERSION")" = "99.0.0" ] || fail "the new code did not install the newest release"
[ "$(git -C "$home/clone" rev-parse HEAD)" = "$(git -C "$home/origin.git" rev-parse v99.0.0^{commit})" ] || fail "the clone is not at the release"
[ ! -e "$home/clone/UNRELEASED" ] || fail "an unreleased commit was offered"
audit v99.0.0 --complete || fail "after the synthetic release the install is not that release, file for file"
run /bin/bash "$mifal" update --yes | grep -q "up to date" || fail "a second update was not a no-op"

[ "$(cat "$home/.agents/skills/my-own-skill/SKILL.md")" = "my own skill" ] || fail "the user's own skill changed"
run /bin/bash "$mifal" doctor || fail "doctor after update"
run /bin/bash "$mifal" uninstall >/dev/null || fail "uninstall"
[ "$(cat "$home/.agents/skills/my-own-skill/SKILL.md")" = "my own skill" ] || fail "uninstall removed the user's own skill"
echo "REHEARSAL OK: $from -> main -> v99.0.0 (synthetic)"

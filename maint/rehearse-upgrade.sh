#!/bin/bash
# Upgrade rehearsal in a disposable HOME: install an older release the way a user did, add a skill of the user's own,
# update with that old release's own code, then publish a synthetic next release and an unreleased commit in a private
# copy of the remote and update again with the new code. Run before a release.
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
git clone -q "$home/origin.git" "$home/clone"
git -C "$home/clone" checkout -q -B main "$from"
git -C "$home/clone" branch -q --set-upstream-to=origin/main main
run /bin/bash "$home/clone/install.sh" --harness claude >"$home/install.log" 2>&1 || { cat "$home/install.log"; fail "install of $from"; }

mkdir -p "$home/.agents/skills/my-own-skill"
echo "my own skill" >"$home/.agents/skills/my-own-skill/SKILL.md"
ln -s "$home/.agents/skills/my-own-skill" "$home/.claude/skills/my-own-skill"
mifal="$home/.local/bin/mifal"

echo "-- first update, run by $from's own code"
run /bin/bash "$mifal" update --yes || fail "first update (old code)"
[ "$(cat "$home/.agents/mifal/VERSION")" = "$(git -C "$home/origin.git" show main:VERSION)" ] || fail "the first update did not land on main's VERSION"

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
run /bin/bash "$mifal" update --yes | grep -q "up to date" || fail "a second update was not a no-op"

[ "$(cat "$home/.agents/skills/my-own-skill/SKILL.md")" = "my own skill" ] || fail "the user's own skill changed"
run /bin/bash "$mifal" doctor || fail "doctor after update"
run /bin/bash "$mifal" uninstall >/dev/null || fail "uninstall"
[ "$(cat "$home/.agents/skills/my-own-skill/SKILL.md")" = "my own skill" ] || fail "uninstall removed the user's own skill"
echo "REHEARSAL OK: $from -> main -> v99.0.0 (synthetic)"

#!/bin/bash
# Run the suite under macOS's system Python 3.9 and under the current python3. Both must pass.
# Any argument goes to unittest for tests/ only and skips the shipped suites; the run says so when it ends.
# The shipped suites read ~/.agents, so they run in a disposable HOME whose Pool and tools are this tree's.
set -eu
here="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(dirname "$here")"
home="$(mktemp -d)"
trap 'rm -rf "${home:?}"' EXIT
home="$(cd -P "$home" && pwd)"
mkdir -p "$home/.agents/mifal"
ln -s "$repo/skills" "$home/.agents/skills"
ln -s "$repo/tools" "$home/.agents/mifal/tools"

shipped() {
    local py="$1" dir="$2"
    echo "-- $dir"
    (cd "$repo" && env -i HOME="$home" PATH=/usr/bin:/bin TERM=dumb LANG=en_US.UTF-8 \
        "$py" -B -m unittest discover -s "$dir" -p 'test_*.py')
}

status=0
for py in /usr/bin/python3 "$(command -v python3)"; do
    echo "== $("$py" --version 2>&1) ($py), $(/bin/bash --version | head -1)"
    (cd "$here" && MIFAL_TEST_PYTHON="$py" "$py" -B -m unittest discover -s . -p 'test_*.py' "$@") || status=1
    if [ $# -eq 0 ]; then
        for dir in skills/team-lead/scripts skills/team-lead/stewardship tools tools/herdr_adapter/tests; do
            shipped "$py" "$dir" || status=1
        done
    fi
done
if [ $# -gt 0 ]; then
    echo "tests/run.sh: arguments given, so only tests/ ran and the shipped suites did not run" \
        "(validator, stewardship, tools, adapter); run tests/run.sh with no arguments for the full suite." >&2
fi
exit $status

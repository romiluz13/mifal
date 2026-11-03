#!/bin/bash
# Run the suite under macOS's system Python 3.9 and under the current python3. Both must pass.
# Any argument goes to unittest for tests/ only and skips the shipped suites; the run says so when it ends.
# --changed BASE instead runs the tests that tests/changed_tests.py picks for the changes since BASE.
# The shipped suites read ~/.agents, so they run in a disposable HOME whose Pool and tools are this tree's.
set -eu
here="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(dirname "$here")"

# Everything about --changed is checked here, before any interpreter starts.
changed=
for arg in "$@"; do
    case "$arg" in --changed*) changed=1 ;; esac
done
if [ -n "$changed" ]; then
    if [ $# -ne 2 ] || [ "$1" != --changed ]; then
        echo "usage: tests/run.sh --changed BASE    (BASE is a commit; nothing else goes with --changed)" >&2
        exit 2
    fi
    base="$(git -C "$repo" rev-parse --verify --quiet --end-of-options "$2^{commit}")" || {
        printf 'tests/run.sh --changed: %s is not a commit in %s\n' "'$2'" "$repo" >&2
        exit 2
    }
    git -C "$repo" merge-base "$base" HEAD >/dev/null || {
        printf 'tests/run.sh --changed: %s shares no history with HEAD\n' "'$2'" >&2
        exit 2
    }
fi
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
if [ -n "$changed" ]; then
    plan="$(/usr/bin/python3 -B "$here/changed_tests.py" "$repo" "$base")" || exit 2
    modules="$(printf '%s\n' "$plan" | sed -n 's/^tests //p')"
    roots="$(printf '%s\n' "$plan" | sed -n 's/^shipped //p')"
    [ -n "$modules" ] || { echo "tests/run.sh --changed: no plan from tests/changed_tests.py" >&2; exit 2; }
    log="$(mktemp)"
    trap 'rm -rf "${home:?}" "${log:?}"' EXIT
    in_tests() { (cd "$here" && MIFAL_TEST_PYTHON="$1" "$1" -B -m unittest "${@:2}"); }
    # Python before 3.12 calls a run of no tests OK, so the count decides, under every interpreter.
    counted() {
        local what="$1" rc
        shift
        { "$@" 2>&1 1>&3 | tee "$log" >&2; rc=${PIPESTATUS[0]}; } 3>&1
        if grep -E '^Ran [0-9]+ tests? in ' "$log" | tail -n 1 | grep -q '^Ran 0 '; then
            echo "tests/run.sh --changed: $what ran no tests, which is never a pass" >&2
            return 1
        fi
        return "$rc"
    }
    for py in /usr/bin/python3 "$(command -v python3)"; do
        echo "== $("$py" --version 2>&1) ($py), $(/bin/bash --version | head -1)"
        if [ "$modules" = all ]; then
            counted tests/ in_tests "$py" discover -s . -p 'test_*.py' || status=1
        else
            counted tests/ in_tests "$py" $modules || status=1
        fi
        for dir in $roots; do
            counted "$dir" shipped "$py" "$dir" || status=1
        done
    done
    echo "tests/run.sh --changed: a selection for one change, not release evidence;" \
        "a release needs the full MIFAL_RELEASE_REHEARSAL=1 tests/run.sh." >&2
    exit $status
fi
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

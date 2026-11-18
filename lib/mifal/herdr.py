"""Herdr is required: find it, check its version, and install it only through a route the user can see.

Herdr is an external dependency. Mifal records how it was found or installed, and never removes it.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

MINIMUM = (0, 9, 5)
SCRIPT_URL = "https://herdr.dev/install.sh"
TAMPER = "tamper-herdr-script"


@dataclass
class Requirement:
    status: str  # "ok", "old", "broken" or "missing"
    version: tuple | None = None
    path: str | None = None

    def describe(self, show=str) -> str:
        if self.status == "ok":
            where = "" if shutil.which("herdr") else " (not on your PATH)"
            return f"herdr {_dotted(self.version)} found at {show(self.path)}{where}"
        if self.status == "old":
            return (f"herdr {_dotted(self.version)} at {show(self.path)} is older than {_dotted(MINIMUM)}; "
                    f"upgrade it with: {upgrade_command(self.path)}")
        if self.status == "broken":
            return (f"{show(self.path)} does not report a Herdr version; Herdr's script would overwrite it. "
                    "Move it aside or fix it, then run the installer again.")
        return "herdr not found"


def _dotted(version) -> str:
    return ".".join(str(n) for n in version)


def script_target() -> Path:
    """Where Herdr's official script installs the binary."""
    return Path(os.environ.get("HERDR_INSTALL_DIR") or Path.home() / ".local" / "bin") / "herdr"


def check() -> Requirement:
    path = shutil.which("herdr")
    if not path:
        if not os.path.lexists(script_target()):
            return Requirement("missing")
        path = str(script_target())
    found = version(path)
    if found is None:
        return Requirement("broken", path=path)
    return Requirement("ok" if found >= MINIMUM else "old", found, path)


def version(path: str):
    try:
        result = subprocess.run([path, "--version"], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                                timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", result.stdout)
    return tuple(int(n) for n in m.groups()) if m else None


VERSION_FOLDER = r"/[^/]+/(\d+\.\d+\.\d+)[^/]*/"
# Herdr 0.9.5 does not recognise mise's registry layout, installs/herdr/<version>/herdr, and replaces it on
# `herdr update` (checked live on 2026-11-18); Homebrew's Cellar layout it does recognise.
SAFE_OWNERS = ("install it with Homebrew (`brew install herdr`), whose copies Herdr leaves to Homebrew, or with "
               "Herdr's own installer, which `herdr update` owns")
LEAVE_MISE = "`mise unuse -g` its entry, then `mise prune`"


def _mise_installs():
    roots = [os.environ.get("MISE_INSTALLS_DIR")]
    if os.environ.get("MISE_DATA_DIR"):
        roots.append(os.path.join(os.environ["MISE_DATA_DIR"], "installs"))
    return [os.path.realpath(r) for r in roots if r]


def _managed(real: str):
    """(manager, the version its folder records) for a copy inside a package manager's folder, else (None, None)."""
    patterns = [("mise", re.escape(root) + VERSION_FOLDER) for root in _mise_installs()]
    patterns += [("mise", "/mise/installs" + VERSION_FOLDER), ("Homebrew", "/Cellar" + VERSION_FOLDER),
                 ("Nix", r"/nix/store/[^/]+-(\d+\.\d+\.\d+)")]
    for label, pattern in patterns:
        m = re.search(pattern, real)
        if m:
            return label, tuple(int(n) for n in m.group(1).split("."))
    return None, None


@dataclass
class Copy:
    path: str
    runs: str
    version: tuple | None
    manager: str | None
    recorded: tuple | None


def runs(path: str, name: str):
    """The file that runs for `path`: itself, or for a mise shim the install `mise which` names (None if none)."""
    real = os.path.realpath(path)
    if os.path.basename(real) != "mise" and "/mise/shims/" not in path:
        return path
    mise = real if os.path.basename(real) == "mise" else shutil.which("mise")
    try:
        result = subprocess.run([mise, "which", name], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                                timeout=30) if mise else None
    except (OSError, subprocess.TimeoutExpired):
        return None
    target = result.stdout.strip() if result and result.returncode == 0 else ""
    return target if os.path.isfile(target) and os.path.basename(os.path.realpath(target)) != "mise" else None


def copies(name: str) -> list:
    """Every distinct `name` on PATH, in PATH order; a mise shim counts as the install it runs."""
    found, seen = [], set()
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        path = os.path.join(folder, name)
        if not folder or not (os.path.isfile(path) and os.access(path, os.X_OK)):
            continue
        target = runs(path, name)
        real = os.path.realpath(target) if target else None
        if not real or real in seen:
            continue
        seen.add(real)
        found.append(Copy(path, target, version(target), *_managed(real)))
    return found


def owner(name: str, found: list, show=str):
    """(status, detail, fix) for who updates `name`, given its copies on PATH; None when there are none."""
    if not found:
        return None
    for c in found:
        if c.manager and c.version and c.version != c.recorded:
            return ("FAIL", f"{show(c.path)} reports {_dotted(c.version)} but sits in {c.manager}'s folder for "
                    f"{_dotted(c.recorded)}: it updated itself, so {c.manager} no longer knows which version you run",
                    _one_owner(name, c))
    for c in found:
        if name == "herdr" and c.manager and not herdr_sees_manager(c.runs):
            return ("FAIL", f"{show(c.path)} sits in {c.manager}'s folder, but not where Herdr looks for "
                    f"{c.manager}'s copies, so `herdr update` would replace it behind {c.manager}'s back",
                    _one_owner(name, c))
    if len(found) > 1:
        listed = ", ".join(f"{show(c.path)} ({_dotted(c.version) if c.version else 'no version'}, "
                           f"{c.manager or 'own updater'})" for c in found)
        status = "WARN" if len({c.version for c in found}) == 1 else "FAIL"
        return (status, f"{len(found)} copies on PATH, the first one runs: {listed}",
                f"keep one {name} and remove the others, so a single updater owns it")
    c = found[0]
    return ("PASS", f"one copy, {show(c.path)}, updated by {c.manager or 'its own updater'}", None)


def _one_owner(name: str, c: Copy) -> str:
    leave = LEAVE_MISE if c.manager == "mise" else f"uninstall it with {c.manager}"
    if name == "herdr" and c.manager == "Homebrew":
        return "give herdr one owner: `brew reinstall herdr`, then `brew upgrade herdr`, so Homebrew records the copy you run"
    if name == "herdr":
        return f"give herdr one owner: {SAFE_OWNERS}; then remove this copy ({leave})"
    return f"give {name} one owner: remove this copy ({leave}) and install {name} with its own installer"


def herdr_sees_manager(path: str) -> bool:
    """Herdr's own test for a package-managed install (src/update.rs in Herdr 0.9.5), on the path it runs from and
    on its resolved path; `herdr update` replaces any other copy in place."""
    def sees(candidate):
        if candidate.startswith("/nix/store/"):
            return True
        parts = Path(candidate).parts
        if len(parts) < 5 or parts[-1] != "herdr" or parts[-2] != "bin" or parts[-4] != "herdr":
            return False
        installs = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(candidate))))
        return parts[-5] in ("installs", "Cellar") or os.path.realpath(installs) in _mise_installs()
    return sees(os.path.abspath(path)) or sees(os.path.realpath(path))


def upgrade_command(path: str) -> str:
    found = copies("herdr")
    path = runs(path, "herdr") or (found[0].runs if found else path)
    real = os.path.realpath(path)
    manager, _ = _managed(real)
    if manager == "mise":
        return "mise upgrade herdr" if herdr_sees_manager(path) else f"{SAFE_OWNERS}, then remove herdr from mise ({LEAVE_MISE})"
    if manager == "Homebrew" or real.startswith(("/opt/homebrew/", "/usr/local/Homebrew/")):
        return "brew upgrade herdr"
    return "herdr update"


def install_route(allow_script: bool) -> str:
    """How a missing Herdr gets installed: 'brew', 'script', 'ask' or 'refuse'."""
    if shutil.which("brew"):
        return "brew"
    if allow_script:
        return "script"
    if sys.stdin.isatty():
        return "ask"
    return "refuse"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure(allow_script: bool, dry_run: bool, out, err, previous=None, show=str):
    """The Manifest's record of Herdr, installing it on a real run when missing; None means the install must stop."""
    req = check()
    if req.status == "ok":
        out(req.describe(show))
        return _found(req, previous)
    if req.status != "missing":
        err(f"mifal: {req.describe(show)}")
        return None
    route = install_route(allow_script)
    script_words = (f"download Herdr's official install script from {SCRIPT_URL}, show its sha256, "
                    f"and run that same file (it installs Herdr's latest release into {show(script_target())})")
    if dry_run:
        out({"brew": "herdr not found: would run: brew install herdr",
             "script": f"herdr not found: would {script_words}",
             "ask": f"herdr not found: would ask, then {script_words}",
             "refuse": "herdr not found: a real install stops here; Homebrew is absent, so pass --herdr-script to "
                       + script_words}[route])
        return {}
    if route == "refuse":
        err("mifal: Herdr is required and Homebrew is not installed. To install Herdr with its official script, "
            f"rerun with --herdr-script, which will {script_words}.")
        return None
    if route == "brew":
        out("installing herdr: brew install herdr")
        status = subprocess.run(["brew", "install", "herdr"]).returncode
        if status != 0:
            err(f"mifal: brew install herdr failed (exit {status}); nothing of Mifal's was written.")
            return None
        record = {"route": "brew"}
    else:
        record = _run_script(route == "ask", out, err, show)
        if record is None:
            return None
    after = check()
    if after.status != "ok":
        err(f"mifal: after installing Herdr, {after.describe(show)}")
        return None
    out(after.describe(show))
    return dict(record, installed_by_mifal=True, version=_dotted(after.version), path=after.path)


def _run_script(ask: bool, out, err, show):
    target = script_target()
    with tempfile.TemporaryDirectory(prefix="mifal-herdr-") as tmp:
        script = Path(tmp) / "install.sh"
        if subprocess.run(["curl", "-fsSL", "-o", str(script), SCRIPT_URL]).returncode != 0 or not script.is_file():
            err(f"mifal: could not download {SCRIPT_URL}; nothing was changed.")
            return None
        digest = _sha256(script)
        out(f"Herdr is required and Homebrew is not installed. Herdr's official install script was downloaded from "
            f"{SCRIPT_URL}\n  sha256 {digest}\nIt installs Herdr's latest release into {show(target)}.")
        if ask:
            out("Run it now? [y/N] ")
            if sys.stdin.readline().strip().lower() not in ("y", "yes"):
                err("mifal: Herdr was not installed; nothing was changed. Install Herdr, then run ./install.sh again.")
                return None
        if os.environ.get("MIFAL_TEST_FAIL_AT") == TAMPER:
            with script.open("a") as f:
                f.write("\n# changed after it was shown\n")
        if _sha256(script) != digest:
            err("mifal: Herdr's install script changed after it was shown, so it was not run; nothing was changed.")
            return None
        out(f"running Herdr's install script (sha256 {digest})")
        status = subprocess.run(["/bin/sh", str(script)]).returncode
    if status != 0:
        left = f" It left {show(target)}, which Mifal did not remove." if os.path.lexists(target) else ""
        err(f"mifal: Herdr's install script failed (exit {status}); nothing of Mifal's was written.{left}")
        return None
    return {"route": "script", "script_sha256": digest}


def _found(req: Requirement, previous):
    if previous and previous.get("installed_by_mifal"):
        return dict(previous, version=_dotted(req.version), path=req.path)
    return {"route": "found", "installed_by_mifal": False, "version": _dotted(req.version), "path": req.path}


def removal_hint(record, show=str):
    """What uninstall says about Herdr, which it never removes."""
    if not (record and record.get("installed_by_mifal")):
        return None
    if record["route"] == "brew":
        return "Herdr stays installed. Mifal installed it with Homebrew; to remove it: brew uninstall herdr"
    return f"Herdr stays installed. Mifal installed it with its official script; to remove it: rm {show(record['path'])}"

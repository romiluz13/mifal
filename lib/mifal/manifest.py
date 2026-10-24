"""The Manifest: every path an install owns, by realpath, and the journal of an install in progress."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

FORMAT = 1
ENGINE = Path(".agents/mifal")
POOL = Path(".agents/skills")
BIN = Path(".local/bin")
SAVED = Path(".agents/mifal-saved")
MISSING = ("missing",)


class Home:
    """HOME, and the realpaths of the folders Mifal writes into."""

    def __init__(self, home):
        self.home = Path(home)
        self.real = Path(os.path.realpath(self.home))
        self.engine = self.resolve(ENGINE)
        self.pool = self.resolve(POOL)
        self.bin = self.resolve(BIN)
        self.saved = self.resolve(SAVED)
        self.manifest = self.engine / "install-manifest.json"
        self.link = self.bin / "mifal"

    def resolve(self, rel: Path) -> Path:
        return Path(os.path.realpath(self.home / rel))

    def linked(self):
        """(folder, realpath) for each folder Mifal writes into that a symlink leads somewhere else."""
        for rel in (ENGINE, POOL, BIN):
            real = self.resolve(rel)
            if real != self.real / rel:
                yield self.home / rel, real

    def show(self, path) -> str:
        path = Path(path)
        for base in (self.real, self.home):
            try:
                return "~/" + str(path.relative_to(base))
            except ValueError:
                pass
        return str(path)

    def under(self, base: Path, path: Path) -> Path:
        """Where path goes when moved into base, keeping its place relative to HOME."""
        try:
            return base / path.relative_to(self.real)
        except ValueError:
            return base / path.relative_to(path.anchor)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def state(path: Path) -> tuple:
    """What is at path, without following a symlink there."""
    path = Path(path)
    if path.is_symlink():
        return ("link", os.readlink(path))
    if path.is_dir():
        return ("dir",)
    if path.is_file():
        return ("file", sha256_file(path))
    return ("other",) if os.path.lexists(path) else MISSING


def diverted(path: Path, through=()):
    """The nearest folder above path that is now a symlink, or None. Manifest paths are realpaths, so a link above
    one means the user replaced that folder since install, and what it leads to is not Mifal's. A folder named in
    through is a link of the user's that Mifal wrote into, so it is not a replacement."""
    for parent in Path(path).parents:
        if parent.is_symlink() and parent not in through:
            return parent
    return None


def linked_skill_folders(data: dict) -> set:
    """The wired agents' skills folders that are links and were never Mifal's own folders: the person's link, which
    Mifal wrote its skill links through. A recorded dir entry is a folder Mifal made, so it never counts."""
    made = {Path(e["path"]) for e in data.get("entries", []) if e["kind"] == "dir"}
    found = {Path(r["root"]) / "skills" for r in data.get("harnesses", {}).values() if r.get("status") == "wired"}
    return {f for f in found if f.is_symlink() and f not in made}


def replace_file(path: Path, data: bytes, mode: int, tmp: Path | None = None) -> None:
    """Put data at path through a temporary file this call creates, never one that already exists and never through
    a link, then rename it over path. tmp is a name in a folder the caller owns; without one, or when path is on
    another filesystem, the temporary file is a fresh random name beside path."""
    if tmp is not None and os.stat(tmp.parent).st_dev != os.stat(path.parent).st_dev:
        tmp = None
    if tmp is None:
        fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".mifal-tmp")
        tmp = Path(name)
    else:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), mode)
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.lexists(tmp):
            os.unlink(tmp)
        raise


def mode_of(path: Path, default: int = 0o644) -> int:
    return os.stat(path).st_mode & 0o7777 if path.is_file() and not path.is_symlink() else default


def read_rules(path: Path) -> str:
    """A rules file's text exactly as stored, line endings included."""
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def expected(entry: dict) -> tuple:
    if entry["kind"] == "file":
        return ("file", entry["sha256"])
    if entry["kind"] == "symlink":
        return ("link", entry["target"])
    return ("dir",)


def load(h: Home):
    """(data, raw text) of the Manifest, or None when there is none."""
    if not h.manifest.exists():
        return None
    raw = h.manifest.read_text(encoding="utf-8")
    data = json.loads(raw)
    if data.get("format") != FORMAT:
        raise SystemExit(f"mifal: {h.show(h.manifest)} has format {data.get('format')!r}; this mifal reads format {FORMAT}")
    recorded = data.get("home")
    if not isinstance(recorded, str):
        raise SystemExit(f'mifal: the Manifest at {h.show(h.manifest)} has no usable "home" field. Nothing was changed.')
    if not same_home(recorded, h):
        raise SystemExit(
            f"mifal: {h.show(h.manifest)} belongs to the Mifal install for {recorded}, not this home ({h.real}). "
            f"Nothing was changed.\n{_link_advice(h)}"
        )
    return data, raw


def same_home(recorded: str, h: Home) -> bool:
    real = os.path.realpath(recorded)
    if real == str(h.real):
        return True
    try:
        return os.path.samefile(real, h.real)
    except OSError:
        return False


def _link_advice(h: Home) -> str:
    """Name the symlink that leads this home's engine folder elsewhere, deepest first."""
    path = h.home / ENGINE
    while True:
        if os.path.islink(path):
            shown = "~" if path == h.home else f"~/{path.relative_to(h.home)}"
            return f"Remove the link {shown} if it should not lead there."
        if path == h.home or h.home not in path.parents:
            break
        path = path.parent
    return (
        "If this home folder was renamed or moved, that install's recorded paths no longer match, "
        "and Mifal will not act on them."
    )


def save(h: Home, data: dict) -> None:
    write_text(h.manifest, json.dumps(data, indent=2, sort_keys=True) + "\n")


def write_text(path: Path, text: str) -> None:
    replace_file(path, text.encode("utf-8"), mode_of(path))

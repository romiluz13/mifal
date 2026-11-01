"""Audit doctor reads and exact existing subprocesses; refuse writes and sockets.
Usage: audited_doctor.py LOG ENGINE_LIB [DECLARED_CODEX_CONFIG ...]"""
import json
import os
import shutil
import sys
from pathlib import Path

log = open(sys.argv[1], "w")
engine = Path(sys.argv[2]).parent
settings = {os.path.abspath(path) for path in sys.argv[3:]}
resolved_settings = {os.path.realpath(path) for path in settings}
private = (".claude/settings.json", ".claude/.credentials.json", ".codex/auth.json",
           ".factory/settings.json", ".pi/agent/auth.json", ".config/opencode/opencode.json",
           ".local/share/opencode/auth.json", ".config/herdr/token", ".aws/credentials",
           ".claude.json", ".netrc", ".config/gh/hosts.yml", ".ssh/id_ed25519")
private_paths = {str(Path(os.environ["HOME"]) / path) for path in private}
herdr = shutil.which("herdr")
allowed_processes = {
    (sys.executable, "-B", "-I", str(engine.parent / "skills/team-lead/scripts/validate_contracts.py"), "selfcheck"),
    (herdr, "--version"), (herdr, "status", "--json"), (herdr, "api", "schema", "--json"),
}


def hook(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = os.fsdecode(args[0])
        log.write(f"open {path}\n")
        log.flush()
        flags = args[2]
        if path != os.devnull and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise RuntimeError("forbidden write")
        absolute, real = os.path.abspath(path), os.path.realpath(path)
        if (absolute in private_paths or real in private_paths
                or (Path(absolute).name in ("config.toml", "settings.json", "opencode.json")
                    or Path(real).name in ("config.toml", "settings.json", "opencode.json"))
                and absolute not in settings | resolved_settings):
            raise RuntimeError("forbidden settings or credential read")
    elif event == "subprocess.Popen":
        log.write(f"exec {args[1]}\n")
        log.flush()
        if tuple(args[1]) not in allowed_processes:
            raise RuntimeError("forbidden process")
    elif event.startswith("socket."):
        log.write(f"connect {event}\n")
        log.flush()
        raise RuntimeError("forbidden socket")
    elif event in ("os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link", "os.symlink", "os.chmod",
                   "os.chown", "os.truncate", "os.utime", "os.system", "os.posix_spawn", "os.fork", "os.exec"):
        log.write(f"forbidden {event}\n")
        log.flush()
        raise RuntimeError("forbidden mutation or process")
    log.flush()


sys.addaudithook(hook)
data = json.loads((engine / "install-manifest.json").read_text())
declared = {str(Path(rec["root"]) / "config.toml") for rec in data.get("harnesses", {}).get("codex", [])
            if rec["status"] == "wired"}
if not settings <= declared:
    raise RuntimeError("forbidden undeclared settings allowance")
source = data.get("source") or {}
if source.get("path") and source.get("revision"):
    allowed_processes.add(("git", "-C", source["path"], "ls-tree", "-r", "-z", "--name-only",
                           source["revision"]))
sys.path.insert(0, sys.argv[2])
from mifal.cli import main  # noqa: E402

sys.exit(main(["doctor"]))

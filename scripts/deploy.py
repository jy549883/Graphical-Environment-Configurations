#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

parser = argparse.ArgumentParser(description="Deploy selected manifest tools.")
parser.add_argument("tools", nargs="+")
parser.add_argument("--apply", action="store_true")
args = parser.parse_args()

def stop(message):
    raise SystemExit(message)

def exists(path):
    return path.exists() or path.is_symlink()

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def inside(base, relative):
    relative = Path(relative)
    if relative == Path(".") or relative.is_absolute() or ".." in relative.parts:
        stop(f"Unsafe relative path: {relative}")
    path = base / relative
    if not path.resolve().is_relative_to(base.resolve()):
        stop(f"Path escapes root: {path}")
    return path

def backup(path):
    candidate = path.with_name(path.name + ".bak")
    if exists(candidate):
        suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = path.with_name(
            f"{path.name}.bak.{suffix}-{uuid4().hex[:8]}"
        )
    try:
        with candidate.open("xb") as output, path.open("rb") as source:
            shutil.copyfileobj(source, output)
        shutil.copystat(path, candidate)
        if digest(path) != digest(candidate):
            stop(f"Backup verification failed: {candidate}")
    except BaseException:
        print(f"Backup operation failed; inspect: {candidate}", flush=True)
        raise
    print(f"BACKUP {path}\n    TO {candidate}", flush=True)

def replace_file(source, target):
    fd, name = tempfile.mkstemp(prefix=".deploy-", dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        shutil.copy2(source, temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)

def replace_link(target, live):
    fd, name = tempfile.mkstemp(prefix=".link-", dir=live.parent)
    os.close(fd)
    temporary = Path(name)
    temporary.unlink()
    try:
        temporary.symlink_to(target)
        temporary.replace(live)
    finally:
        temporary.unlink(missing_ok=True)

repo = Path(__file__).resolve().parents[1]
manifest = json.loads((repo / "manifest.json").read_text())
if manifest.get("schema_version") != 1:
    stop("Unsupported manifest schema.")

root = Path(manifest["deployment_root"]).expanduser()
home = Path.home().resolve()
if not root.is_absolute() or not root.resolve().is_relative_to(home):
    stop("Deployment root must be inside your home directory.")

state = Path.home() / ".local/state/graphical-environment-configurations"
record = state / "deployed-hashes.json"
hashes = json.loads(record.read_text()) if record.exists() else {}

selected = set(args.tools)
entries = [
    entry for entry in manifest["entries"]
    if entry.get("deploy") and entry["tool"] in selected
]
missing = selected - {entry["tool"] for entry in entries}
if missing:
    stop(f"No deployable entries for: {', '.join(sorted(missing))}")

plans = []
destinations = set()

for entry in entries:
    source = inside(repo, entry["repository_path"])
    target = inside(root, entry["deployment_path"])
    live = Path(entry["system_path"]).expanduser()

    if not entry.get("link"):
        stop("This version supports file-symlink entries only.")
    if not live.is_absolute() or ".." in live.parts:
        stop(f"Invalid application path: {live}")
    if not live.parent.resolve().is_relative_to(home):
        stop(f"Application path is outside your home: {live}")
    if live.is_relative_to(root) or live.parent.resolve().is_relative_to(root.resolve()):
        stop(f"Application path overlaps deployment root: {live}")
    if target in destinations or live in destinations or target == live:
        stop("Duplicate or overlapping destinations.")
    destinations.update((target, live))

    if not source.is_file():
        if entry.get("required", True):
            stop(f"Required source missing: {source}")
        print(f"SKIP optional missing source: {source}")
        continue
    if target.is_symlink() or (target.exists() and not target.is_file()):
        stop(f"Deployed destination is not an ordinary file: {target}")
    if live.is_symlink():
        if live.resolve() != target.resolve():
            stop(f"Unexpected existing symlink: {live}")
    elif live.exists() and not live.is_file():
        stop(f"Application path is not an ordinary file: {live}")

    source_hash = digest(source)
    copy_needed = not target.exists() or digest(target) != source_hash
    link_needed = not live.is_symlink()

    if target.exists() and copy_needed:
        if hashes.get(str(target)) != digest(target):
            stop(f"Unrecorded deployed edits; capture them first: {target}")

    if entry["tool"] == "niri":
        environment = os.environ.copy()
        environment["NIRI_CONFIG"] = str(source)
        subprocess.run(["niri", "validate"], env=environment, check=True)

    print(f"\nTool: {entry['tool']}", flush=True)
    print(f"Repository: {source}", flush=True)
    print(f"Deployed:   {target}", flush=True)
    print(f"Live link:  {live}", flush=True)
    print(f"Copy needed: {copy_needed}; link needed: {link_needed}", flush=True)
    if copy_needed and target.exists():
        print(f"Adjacent backup required for: {target}", flush=True)
    if link_needed and live.exists():
        print(f"Adjacent backup required for: {live}", flush=True)

    plans.append((source, target, live, source_hash, copy_needed, link_needed))

if not args.apply:
    print("\nPreview only. No configuration or backups were changed.")
    raise SystemExit(0)

if not plans:
    stop("Nothing to deploy.")

for source, target, live, expected, copy_needed, link_needed in plans:
    if digest(source) != expected:
        stop(f"Source changed during deployment planning: {source}")
    if copy_needed and target.exists():
        backup(target)
    if link_needed and live.exists():
        backup(live)

    if copy_needed:
        target.parent.mkdir(parents=True, exist_ok=True)
        replace_file(source, target)
    if link_needed:
        live.parent.mkdir(parents=True, exist_ok=True)
        replace_link(target, live)

    if digest(target) != expected or not live.is_symlink():
        stop(f"Verification failed: {live}")
    if live.resolve() != target.resolve():
        stop(f"Symlink verification failed: {live}")

    hashes[str(target)] = expected
    print(f"VERIFIED {live} -> {target}", flush=True)

state.mkdir(parents=True, exist_ok=True)
fd, name = tempfile.mkstemp(prefix=".hashes-", dir=state)
try:
    with os.fdopen(fd, "w") as handle:
        json.dump(hashes, handle, indent=2)
        handle.write("\n")
    Path(name).replace(record)
finally:
    Path(name).unlink(missing_ok=True)

print("\nDeployment complete. No services were enabled or restarted.")

"""python -m press publish [--now] [--push]

Stamp the notes into the ledger, build the blyg into the `live` worktree,
and with --push commit and push it when anything changed.
"""
import argparse
import subprocess
import sys
import time
import tomllib
from pathlib import Path

from . import build, ledger, notes

ROOT = Path(__file__).resolve().parent.parent

p = argparse.ArgumentParser(prog="press")
p.add_argument("command", choices=["publish"])
p.add_argument("--now", action="store_true", help="cut versions without waiting for the quiet period")
p.add_argument("--push", action="store_true", help="commit and push the built blyg if it changed")
args = p.parse_args()

config = tomllib.loads((ROOT / "blyg.toml").read_text())
source = Path(config["source"]).expanduser()
out = ROOT / config.get("out", "_site")
ledger_path = source / "ledger.json"

try:
    state = ledger.load(ledger_path)
    changed = ledger.stamp(state, notes.read_notes(source), time.time(), quiet=config.get("quiet_minutes", 30) * 60, now=args.now)
except (notes.Refused, ValueError) as e:
    sys.exit(f"not published: {e}")
ledger.save(state, ledger_path)
build.build(state, config, out)

git = ["git", "-C", str(out)]
if args.push and subprocess.run(git + ["status", "--porcelain"], capture_output=True, text=True).stdout:
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", f"publish: {len(changed)} item(s) changed"], check=True)
    subprocess.run(git + ["push", "-q", "origin", "live"], check=True)
print(f"{len(changed)} item(s) changed; built {out}" + (" and pushed" if args.push else ""))

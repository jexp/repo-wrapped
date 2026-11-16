#!/usr/bin/env python3
"""Repos worked on according to the Claude Code session files: cwd of each matching session -> git origin -> GitHub slug + clone.
Writes raw/discovered-repos.json. With "repos_from_sessions": true in the config, update.py adds the ones not configured yet."""
import glob, json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CFG, RAW

def git(cwd, *a): return subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True).stdout.strip()
rx = re.compile(CFG.get("sessions_match", "$^"), re.I)
cwds = {}
for d in glob.glob(os.path.expanduser("~/.claude/projects/*")):
    if not rx.search(os.path.basename(d)): continue
    for f in glob.glob(d + "/*.jsonl"):
        for i, ln in enumerate(open(f)):
            if i > 60: break
            try: c = json.loads(ln).get("cwd")
            except Exception: continue
            if c: cwds[c] = cwds.get(c, 0) + 1; break
found, gone = {}, 0
for cwd, n in cwds.items():
    if not os.path.isdir(cwd): gone += n; continue
    m = re.search(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?$", git(cwd, "remote", "get-url", "origin"))
    if not m: continue
    slug = m.group(1); common = git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    clone = os.path.dirname(common) if common.endswith("/.git") else cwd
    head = git(clone, "symbolic-ref", "--short", "refs/remotes/origin/HEAD") or "origin/main"
    r = found.setdefault(slug, {"name": slug.split("/")[1], "github": slug, "clone": clone, "refs": [head], "sessions": 0}); r["sessions"] += n
json.dump(sorted(found.values(), key=lambda r: -r["sessions"]), open(RAW + "discovered-repos.json", "w"), indent=1)
print(f"discovered {len(found)} repos from {sum(cwds.values())} sessions ({gone} in removed worktrees):", ", ".join(f'{r["github"]} ({r["sessions"]})' for r in found.values()), file=sys.stderr)

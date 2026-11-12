#!/usr/bin/env python3
"""One row per non-merge commit of both repos (git log --numstat): author, time (with tz), area LOC split, agent co-author flag."""
import json, subprocess, sys, re
sys.path.insert(0, ".")
from common import RAW, REPOS, CFG
from areas import area_of, kind
SEP = "\x1e"
out = open(RAW + "commits.jsonl", "w")
seen = set()
for repo, rc in REPOS.items():
    path = rc["clone"]; refs = rc.get("refs") or ["origin/main"]
    fmt = SEP + "%H%x1f%aN%x1f%aE%x1f%aI%x1f%cI%x1f%s%x1f%b"
    r = subprocess.run(["git", "-C", path, "log", *refs, "--no-merges", "--numstat", *(["--since=" + CFG["since"]] if CFG.get("since") else []), "--format=" + fmt], capture_output=True, text=True)
    for rec in r.stdout.split(SEP)[1:]:
        head, _, stats = rec.partition("\n")
        sha, an, ae, ad, cd, subj, body = (head.split("\x1f") + [""] * 7)[:7]
        # body may contain newlines: git puts numstat after body; split on first line that looks like numstat
        lines = rec.split("\n")
        body_lines, stat_lines = [], []
        for ln in lines[1:]:
            (stat_lines if re.match(r"^(\d+|-)\t(\d+|-)\t", ln) else body_lines).append(ln)
        if sha in seen: continue
        seen.add(sha)
        body_text = "\n".join([body] + body_lines)
        agent = bool(re.search(r"co-authored-by:.*(claude|cursor|copilot|codex|gemini|opencode|glm)", body_text, re.I) or re.search(r"generated with .*claude", body_text, re.I))
        loc = {}
        files = 0
        for ln in stat_lines:
            a, d, p = ln.split("\t", 2)
            if a == "-": continue
            if "=>" in p: p = re.sub(r"\{.*? => (.*?)\}", r"\1", p).replace("//", "/")
            files += 1
            k = kind(p); ar = area_of(p)
            e = loc.setdefault(ar, {"prod_add":0,"prod_del":0,"test_add":0,"test_del":0,"doc_add":0,"doc_del":0,"other_add":0,"other_del":0})
            key = {"prod_rs":"prod","test_rs":"test","docs":"doc","other":"other"}[k]
            e[key+"_add"] += int(a); e[key+"_del"] += int(d)
        out.write(json.dumps({"repo":repo,"sha":sha,"author":an,"email":ae,"author_date":ad,"commit_date":cd,"subject":subj,"agent":agent,"files":files,"loc":loc}) + "\n")
print(len(seen), "commits", file=sys.stderr)

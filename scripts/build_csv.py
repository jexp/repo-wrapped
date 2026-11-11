#!/usr/bin/env python3
"""raw/*.jsonl -> data/<person>.csv (one long-format CSV per person, record_type = pr | ticket | commit | ci_run | session)
and data/bundle.js (the same CSVs as a script tag so index.html works from file://). Re-run after fetching new raw data;
rows are keyed by (record_type, id), so appending/merging more CSV rows later is safe."""
import csv, io, json, math, re, sys, datetime as dt, collections, os
sys.path.insert(0, os.path.dirname(__file__))
from common import RAW as R, DATA as D, PERSONS as persons, REPOS, LINEAR, gh_url, CFG
from areas import area_of, kind, crate_of, CORE, layout
COLS = ["record_type","id","person","repo","title","state","created_at","start_at","end_at","duration_hours","tz","area_primary","areas","crates","files",
        "prod_add","prod_del","test_add","test_del","doc_add","doc_del","other_add","other_del","commits","comments","comment_chars","reviews",
        "agent_comments","agent_commits","agent_prompts","agent_tool_calls","active_minutes","ci_runs","ci_minutes","ci_fail","complexity","labels","url","extra"]
BOT = re.compile(r"(\[bot\]$|^app/|^copilot|^cursor|^stellar|^github-actions|^release-bot|bot$)", re.I)

def jl(p):
    return [json.loads(l) for l in open(R + p)] if os.path.exists(R + p) else []
def P(s): return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
def hours(a, b): return round((P(b) - P(a)).total_seconds() / 3600, 3) if a and b else ""

def complexity(prod, test, nareas, ncrates, core, discuss, adr):
    churn = prod[0] + prod[1] * 0.5 + test[0] * 0.5 + test[1] * 0.25
    raw = math.log2(1 + churn) + 1.6 * math.log2(1 + nareas) + (1.5 if core else 0) + math.log2(1 + ncrates) + 0.7 * math.log2(1 + discuss) + (1.5 if adr else 0)
    return round(max(1.0, min(10.0, raw / 2.6)), 2)

# ---------- identity
by_gh, by_git, by_lin = {}, {}, {}
for pid, p in persons.items():
    for g in p["gh"]: by_gh[g.lower()] = pid
    for g in p["git_names"] + p["git_emails"]: by_git[g.lower()] = pid
    for g in p["linear"]: by_lin[g.lower()] = pid

# ---------- commits
commits = jl("commits.jsonl")
tz_votes = collections.defaultdict(collections.Counter)
for c in commits:
    pid = by_git.get(c["author"].lower()) or by_git.get(c["email"].lower())
    c["pid"] = pid
    if pid: tz_votes[pid][c["author_date"][-6:]] += 1
TZ = {pid: v.most_common(1)[0][0] for pid, v in tz_votes.items()}

rows = collections.defaultdict(list)
def add(pid, **kw):
    r = {k: "" for k in COLS}; r.update(kw); r["person"] = pid; rows[pid].append(r)

def loc_sum(loc):
    s = collections.Counter()
    for ar, e in loc.items():
        for k, v in e.items(): s[k] += v
    return s

for c in commits:
    pid = c["pid"]
    if not pid: continue
    s = loc_sum(c["loc"])
    by_area = {a: e["prod_add"] + e["prod_del"] + e["test_add"] + e["test_del"] + e["doc_add"] + e["doc_del"] + e["other_add"] + e["other_del"] for a, e in c["loc"].items()}
    areas = sorted(by_area, key=by_area.get, reverse=True)
    crates = {x for x in (crate_of(p) for p in []) if x}
    m = re.search(r"\(#(\d+)\)\s*$", c["subject"])
    add(pid, record_type="commit", id=f'{c["repo"]}:{c["sha"][:10]}', repo=c["repo"], title=c["subject"][:200], state="COMMITTED",
        created_at=c["author_date"], start_at=c["author_date"], end_at=c["commit_date"], tz=c["author_date"][-6:], area_primary=areas[0] if areas else "", areas="|".join(areas[:6]),
        files=c["files"], prod_add=s["prod_add"], prod_del=s["prod_del"], test_add=s["test_add"], test_del=s["test_del"], doc_add=s["doc_add"], doc_del=s["doc_del"],
        other_add=s["other_add"], other_del=s["other_del"], commits=1, agent_commits=1 if c["agent"] else 0,
        complexity=complexity((s["prod_add"], s["prod_del"]), (s["test_add"], s["test_del"]), len(areas), len(areas), any(a in CORE for a in areas), 0, "docs" in areas),
        url=f'{gh_url(c["repo"])}/commit/{c["sha"]}', extra=f'pr={m.group(1)}' if m else "")

# ---------- CI runs (index by PR + branch for the PR rows)
runs = []
for repo in REPOS:
    for x in jl(f"runs-{repo}.jsonl"):
        x["repo"] = repo; runs.append(x)
ci_by_pr = collections.defaultdict(lambda: [0, 0.0, 0]); ci_by_branch = collections.defaultdict(lambda: [0, 0.0, 0])
for x in runs:
    st = x["run_started_at"] or x["created_at"]
    dur = (P(x["updated_at"]) - P(st)).total_seconds() / 60 if x["status"] == "completed" else 0
    x["minutes"] = max(0, dur)
    fail = 1 if x["conclusion"] in ("failure", "timed_out", "startup_failure") else 0
    for n in x["prs"]:
        k = ci_by_pr[(x["repo"], n)]; k[0] += 1; k[1] += x["minutes"]; k[2] += fail
    k = ci_by_branch[(x["repo"], x["branch"])]; k[0] += 1; k[1] += x["minutes"]; k[2] += fail
    pid = by_gh.get((x["actor"] or "").lower())
    if pid:
        add(pid, record_type="ci_run", id=f'{x["repo"]}:{x["id"]}:{x["attempt"]}', repo=x["repo"], title=x["name"], state=(x["conclusion"] or x["status"] or "").upper(),
            created_at=x["created_at"], start_at=st, end_at=x["updated_at"], duration_hours=round(x["minutes"] / 60, 4), tz=TZ.get(pid, ""),
            ci_runs=1, ci_minutes=round(x["minutes"], 2), ci_fail=1 if x["conclusion"] in ("failure", "timed_out", "startup_failure") else 0,
            url=f'{gh_url(x["repo"])}/actions/runs/{x["id"]}', extra=f'{x["event"]} {x["branch"]}')

# ---------- PRs
pr_info = {}
for repo in REPOS:
    for p in jl(f"prs-{repo}.jsonl"):
        login = ((p["author"] or {}).get("login") or "").lower()
        pid = by_gh.get(login)
        files = p["files"]["nodes"]
        loc = collections.defaultdict(lambda: collections.Counter()); crates = set()
        adr = False
        for f in files:
            ar = area_of(f["path"]); k = {"prod_rs": "prod", "test_rs": "test", "docs": "doc", "other": "other"}[kind(f["path"])]
            loc[ar][k + "_add"] += f["additions"]; loc[ar][k + "_del"] += f["deletions"]
            cr = crate_of(f["path"])
            if cr: crates.add(cr)
            if f["path"].startswith("docs/adr/") and f["additions"] > 0: adr = True
        s = collections.Counter()
        for ar, e in loc.items(): s.update(e)
        # final diff of the PR: the files list is capped at 100, so scale the split to the PR's true totals
        la = sum(v for k, v in s.items() if k.endswith("_add")); ld = sum(v for k, v in s.items() if k.endswith("_del"))
        if len(files) < p["changedFiles"] and (la or ld):
            for k in list(s):
                s[k] = round(s[k] * (p["additions"] / la if k.endswith("_add") and la else p["deletions"] / ld if k.endswith("_del") and ld else 1))
        by_area = {a: sum(e.values()) for a, e in loc.items()}
        areas = sorted(by_area, key=by_area.get, reverse=True)
        cm = p["comments"]["nodes"]; rv = p["reviews100"]["nodes"]
        bot_c = sum(1 for c in cm if BOT.search((c["author"] or {}).get("login") or "ghost"))
        bot_r = sum(1 for r in rv if BOT.search((r["author"] or {}).get("login") or "ghost"))
        chars = sum(len(c["bodyText"] or "") for c in cm) + sum(len(r["bodyText"] or "") for r in rv)
        ci = ci_by_pr.get((repo, p["number"])) or ci_by_branch.get((repo, p["headRefName"]), [0, 0.0, 0])
        end = p["mergedAt"] or p["closedAt"]
        cx = complexity((s["prod_add"], s["prod_del"]), (s["test_add"], s["test_del"]), len(areas), len(crates), any(a in CORE for a in areas),
                        p["comments"]["totalCount"] + p["reviews"]["totalCount"], adr)
        pr_info[(repo, p["number"])] = {"areas": areas, "cx": cx, "s": s}
        if not pid: continue
        add(pid, record_type="pr", id=f'{repo}#{p["number"]}', repo=repo, title=p["title"][:200], state=("DRAFT" if p["isDraft"] and p["state"] == "OPEN" else p["state"]),
            created_at=p["createdAt"], start_at=p["createdAt"], end_at=end or "", duration_hours=hours(p["createdAt"], end) if end else "", tz=TZ.get(pid, ""),
            area_primary=areas[0] if areas else "", areas="|".join(areas[:6]), crates=len(crates), files=p["changedFiles"],
            prod_add=s["prod_add"], prod_del=s["prod_del"], test_add=s["test_add"], test_del=s["test_del"], doc_add=s["doc_add"], doc_del=s["doc_del"], other_add=s["other_add"], other_del=s["other_del"],
            commits=p["commits"]["totalCount"], comments=p["comments"]["totalCount"] + p["reviews"]["totalCount"], comment_chars=chars, reviews=p["reviews"]["totalCount"],
            agent_comments=bot_c + bot_r, ci_runs=ci[0], ci_minutes=round(ci[1], 2), ci_fail=ci[2], complexity=cx,
            labels="|".join(l["name"] for l in p["labels"]["nodes"]),
            url=f'{gh_url(repo)}/pull/{p["number"]}',
            extra=f'adr={int(adr)} lines={p["additions"]}+/{p["deletions"]}-')

# ---------- tickets
PATH = re.compile(r"[A-Za-z0-9_./-]+\.(?:rs|toml|yml|md)\b")
for t in (jl("linear-issues.jsonl") if LINEAR else []):
    a = (t["assignee"] or {}).get("name", "").lower(); cr = (t["creator"] or {}).get("name", "").lower()
    pid = by_lin.get(a) or (by_lin.get(cr) if not a else None)
    if not pid: continue
    desc = t["description"] or ""
    paths = set(PATH.findall(desc)) ; paths = {m.group(0) for m in PATH.finditer(desc)}
    areas = collections.Counter(area_of(p) for p in paths if "/" in p)
    linked = []
    for at in t["attachments"]["nodes"]:
        m = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", at["url"] or "")
        if m and m.group(2) in REPOS: linked.append((m.group(2), int(m.group(3))))
    for k in linked:
        for ar in pr_info.get(k, {}).get("areas", [])[:2]: areas[ar] += 1
    areas = [x for x, _ in areas.most_common(6) if x != "other"]
    cm = t["comments"]["nodes"]; chars = sum(len(c["body"] or "") for c in cm)
    bot_c = sum(1 for c in cm if BOT.search((c["user"] or {}).get("name") or "") or "[bot]" in ((c["user"] or {}).get("name") or ""))
    start = t["startedAt"] or ""; end = t["completedAt"] or t["canceledAt"] or ""
    cx_pr = max([pr_info.get(k, {}).get("cx", 0) for k in linked] or [0])
    cx = round(max(cx_pr, min(10, 1 + math.log2(1 + len(desc) / 400) + 0.5 * math.log2(1 + len(cm)) + (len(areas) > 1) + (t["estimate"] or 0) / 4)), 2)
    s = collections.Counter()
    for k in linked: s.update(pr_info.get(k, {}).get("s", {}))
    add(pid, record_type="ticket", id=t["identifier"], repo="linear", title=t["title"][:200], state=t["state"]["name"], created_at=t["createdAt"],
        start_at=start or t["createdAt"], end_at=end, duration_hours=hours(start or t["createdAt"], end) if end else "", tz=TZ.get(pid, ""),
        area_primary=areas[0] if areas else "", areas="|".join(areas), files=len(paths), comments=len(cm), comment_chars=chars + len(desc), agent_comments=bot_c,
        prod_add=s["prod_add"], prod_del=s["prod_del"], test_add=s["test_add"], test_del=s["test_del"], doc_add=s["doc_add"], doc_del=s["doc_del"],
        complexity=cx, labels="|".join(l["name"] for l in t["labels"]["nodes"]), url=f'https://linear.app/{(LINEAR or {}).get("workspace", "workspace")}/issue/{t["identifier"]}',
        extra=f'creator={(t["creator"] or {}).get("name","")};linked_prs={len(linked)};parent={(t["parent"] or {}).get("identifier","")}')

# ---------- Claude sessions (this machine; the person flagged sessions:true)
for s in jl("sessions.jsonl"):
    pid = next((k for k, v in persons.items() if v.get("sessions")), None)
    if not pid: continue
    add(pid, record_type="session", id=s["session"][:12], repo="claude-code", title=s["project"], state="SESSION", created_at=s["start"], start_at=s["start"], end_at=s["end"],
        duration_hours=hours(s["start"], s["end"]), tz=TZ.get(pid, ""), agent_prompts=s["prompts"], agent_tool_calls=s["tool_calls"], active_minutes=s["active_min"],
        extra=f'subagents={s["subagents"]}')

# ---------- write
os.makedirs(D, exist_ok=True)
bundle = {}
for pid, rs in rows.items():
    rs.sort(key=lambda r: (r["record_type"], r["start_at"] or r["created_at"]))
    buf = io.StringIO(); w = csv.DictWriter(buf, COLS); w.writeheader(); w.writerows(rs)
    open(f"{D}{pid}.csv", "w").write(buf.getvalue()); bundle[pid] = buf.getvalue()
    print(pid, collections.Counter(r["record_type"] for r in rs), file=sys.stderr)
meta = {pid: {"name": persons[pid]["name"], "file": f"{pid}.csv", "tz": TZ.get(pid, "")} for pid in rows}
json.dump(meta, open(D + "manifest.json", "w"), indent=1)
seen = set(a for rs in rows.values() for r in rs for a in (r["areas"].split("|") if r["areas"] else []) + ([r["area_primary"]] if r["area_primary"] else []))
open(D + "bundle.js", "w").write("window.WRAPPED_MANIFEST=" + json.dumps(meta) + ";\nwindow.WRAPPED_AREAS=" + json.dumps(layout(seen)) + ";\nwindow.WRAPPED_TITLE=" + json.dumps(CFG["name"]) + ";\nwindow.WRAPPED_DATA=" + json.dumps(bundle) + ";\n")

#!/usr/bin/env python3
"""Incremental refresh of every raw source, then rebuild the CSVs.

  python3 update.py            # additive: only what changed since the last run
  python3 update.py --config ../configs/other.json   # any repo
  python3 update.py --full     # refetch everything (PRs, runs, Linear)
  python3 update.py --only prs,runs   # subset of: git,prs,runs,linear,sessions,build

Sources and how each stays additive (all upserts keyed by id, old rows are never dropped):
  git       local clones (git fetch first), rewritten from git log, merged by sha   -> raw/commits.jsonl
  prs       GitHub GraphQL, newest-updated first, stops at the stored watermark     -> raw/prs-<repo>.jsonl
  runs      GitHub Actions REST, newest first, stops when a page is fully known     -> raw/runs-<repo>.jsonl
  linear    Linear GraphQL via everything-cli, filtered by updatedAt watermark      -> raw/linear-issues.jsonl
  sessions  ~/.claude/projects transcripts (this machine only), merged by session   -> raw/sessions.jsonl
Retries every network call (TLS timeouts happen). Repos, people and area profile come from --config (default configs/example-generic.json); output goes to out/<name>/{raw,data}.
"""
import argparse, datetime as dt, json, os, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
_ap = argparse.ArgumentParser(); _ap.add_argument("--config", default=os.environ.get("WRAPPED_CONFIG") or "../configs/example-generic.json")
_ap.add_argument("--full", action="store_true"); _ap.add_argument("--only", default="git,prs,runs,linear,sessions,build")   # plus: discover
ARGS = _ap.parse_args(); os.environ["WRAPPED_CONFIG"] = os.path.abspath(ARGS.config); os.chdir(HERE)   # subprocesses inherit it
sys.path.insert(0, HERE)
from common import CFG, RAW as _RAW, REPOS, LINEAR
RAW = _RAW.rstrip("/")
if "discover" in ARGS.only.split(",") or CFG.get("repos_from_sessions"):
    subprocess.run([sys.executable, "discover_repos.py"], check=False)
    if CFG.get("repos_from_sessions") and os.path.exists(RAW + "/discovered-repos.json"):
        have = {r["github"] for r in REPOS.values()}
        for r in json.load(open(RAW + "/discovered-repos.json")):
            if r["github"] not in have and r["name"] not in REPOS: REPOS[r["name"]] = r; print("repo from sessions:", r["github"], file=sys.stderr)
GH = {n: r["github"] for n, r in REPOS.items()}
CLONES = {n: r["clone"] for n, r in REPOS.items()}
LINEAR_TEAM = (LINEAR or {}).get("team")
OVERLAP = dt.timedelta(days=3)
SINCE = dt.datetime.fromisoformat(CFG["since"]).replace(tzinfo=dt.timezone.utc) if CFG.get("since") else None   # optional config floor: older PRs/runs are never fetched

def log(*a): print(*a, file=sys.stderr, flush=True)
def load(path, key):
    d = {}
    if os.path.exists(path):
        for ln in open(path):
            if ln.strip(): r = json.loads(ln); d[key(r)] = r
    return d
def save(path, d):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        for r in d.values(): f.write(json.dumps(r) + "\n")
    os.replace(tmp, path)
def retry(cmd, parse, tries=6):
    for a in range(tries):
        r = subprocess.run(cmd, capture_output=True, text=True)
        try: return parse(r.stdout)
        except Exception: log("  retry", a, (r.stderr or r.stdout)[:100].strip()); time.sleep(5 * (a + 1))
    raise SystemExit("giving up: " + " ".join(cmd[:4]))
def ts(s): return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None

# ---------- git ----------
def do_git():
    for repo, p in CLONES.items():
        subprocess.run(["git", "-C", p, "fetch", "--all", "--prune", "-q"], check=False)
    path = f"{RAW}/commits.jsonl"; old = load(path, lambda r: (r["repo"], r["sha"]))
    subprocess.run([sys.executable, "extract_commits.py"], check=True)   # rewrites commits.jsonl from git
    new = load(path, lambda r: (r["repo"], r["sha"]))
    old.update(new); save(path, old); log("git commits", len(old), "total,", len(new), "scanned")

# ---------- PRs ----------
PRQ = """query($o:String!,$n:String!,$c:String){repository(owner:$o,name:$n){pullRequests(first:25,after:$c,orderBy:{field:UPDATED_AT,direction:DESC}){
pageInfo{hasNextPage endCursor}
nodes{number title state isDraft createdAt updatedAt mergedAt closedAt additions deletions changedFiles headRefName baseRefName
 author{login} mergedBy{login} bodyText labels(first:10){nodes{name}}
 commits(first:1){totalCount} reviews(first:1){totalCount} reviewThreads(first:1){totalCount}
 files(first:100){nodes{path additions deletions}}
 comments(first:100){totalCount nodes{author{login} createdAt bodyText}}
 reviews100: reviews(first:50){nodes{author{login} submittedAt state bodyText}}
}}}}"""
def do_prs(full):
    for repo, slug in GH.items():
        o, n = slug.split("/"); path = f"{RAW}/prs-{repo}.jsonl"; have = load(path, lambda r: r["number"])
        mark = None
        if have and not full:   # rows from before updatedAt existed fall back to their latest timestamp
            mark = max(ts(r.get("updatedAt") or r.get("closedAt") or r.get("mergedAt") or r["createdAt"]) for r in have.values()) - OVERLAP
        if SINCE and (mark is None or mark < SINCE): mark = SINCE
        cur, got, stop = None, 0, False
        while not stop:
            cmd = ["gh", "api", "graphql", "-f", f"query={PRQ}", "-F", f"o={o}", "-F", f"n={n}"] + (["-F", f"c={cur}"] if cur else [])
            d = retry(cmd, lambda s: json.loads(s)["data"]["repository"]["pullRequests"])
            for p in d["nodes"]:
                if mark and ts(p["updatedAt"]) < mark: stop = True; break
                have[p["number"]] = p; got += 1
            if not d["pageInfo"]["hasNextPage"]: break
            cur = d["pageInfo"]["endCursor"]
        save(path, dict(sorted(have.items()))); log(f"prs {repo}: {got} fetched, {len(have)} total")

# ---------- CI runs ----------
def do_runs(full):
    for repo, slug in GH.items():
        path = f"{RAW}/runs-{repo}.jsonl"; have = load(path, lambda r: r["id"]); page, got = 1, 0
        while True:
            runs = retry(["gh", "api", f"repos/{slug}/actions/runs?per_page=100&page={page}"], lambda s: json.loads(s)["workflow_runs"])
            if not runs: break
            fresh = 0
            if SINCE: runs_in = [x for x in runs if ts(x["created_at"]) >= SINCE]; older = len(runs_in) < len(runs); runs = runs_in
            else: older = False
            for x in runs:
                row = {"id": x["id"], "name": x["name"], "event": x["event"], "status": x["status"], "conclusion": x["conclusion"], "created_at": x["created_at"],
                       "run_started_at": x.get("run_started_at"), "updated_at": x["updated_at"], "actor": (x.get("triggering_actor") or x.get("actor") or {}).get("login"),
                       "branch": x["head_branch"], "prs": [p["number"] for p in x.get("pull_requests", [])], "attempt": x.get("run_attempt")}
                prev = have.get(x["id"])
                if prev is None or prev.get("status") != "completed" or prev.get("updated_at") != row["updated_at"]: fresh += 1
                have[x["id"]] = row; got += 1
            log(f"  runs {repo} page {page} (+{fresh} new/changed)"); page += 1
            if older or (fresh == 0 and not full): break     # a whole page we already had, all completed: older pages unchanged
        save(path, dict(sorted(have.items()))); log(f"runs {repo}: {got} seen, {len(have)} total")

# ---------- Linear ----------
LQ = """query($c:String,$f:IssueFilter){ team(id:"%s"){ issues(first:25, after:$c, filter:$f, includeArchived:true){
pageInfo{hasNextPage endCursor}
nodes{ identifier title createdAt updatedAt startedAt completedAt canceledAt archivedAt estimate priority
 state{name type} assignee{name email} creator{name email} project{name} parent{identifier}
 labels{nodes{name}} description
 comments(first:50){ nodes{ createdAt body user{name} } }
 attachments(first:10){ nodes{ url sourceType } } } } } }""" % LINEAR_TEAM
def do_linear(full):
    path = f"{RAW}/linear-issues.jsonl"; have = load(path, lambda r: r["identifier"]); f = {}
    if have and not full:
        mark = max(ts(r.get("updatedAt") or r.get("completedAt") or r.get("startedAt") or r["createdAt"]) for r in have.values()) - OVERLAP
        f = {"updatedAt": {"gt": mark.isoformat()}}
    cur, got = None, 0
    while True:
        v = {"c": cur, "f": f} if cur else {"f": f}
        d = retry(["everything-cli", "linear", "api", LQ, "--variables", json.dumps(v)], lambda s: json.loads(s)["team"]["issues"])
        for i in d["nodes"]: have[i["identifier"]] = i; got += 1
        if not d["pageInfo"]["hasNextPage"]: break
        cur = d["pageInfo"]["endCursor"]
    save(path, have); log(f"linear: {got} fetched, {len(have)} total")

# ---------- sessions ----------
def do_sessions():
    path = f"{RAW}/sessions.jsonl"; old = load(path, lambda r: r["session"])
    subprocess.run([sys.executable, "extract_sessions.py"], check=True)
    old.update(load(path, lambda r: r["session"])); save(path, old); log("sessions", len(old))

if __name__ == "__main__":
    a = ARGS; steps = a.only.split(",")
    if "git" in steps: do_git()
    if "prs" in steps: do_prs(a.full)
    if "runs" in steps: do_runs(a.full)
    if "linear" in steps and LINEAR_TEAM: do_linear(a.full)
    if "sessions" in steps: do_sessions()
    if "build" in steps: subprocess.run([sys.executable, "build_csv.py"], check=True)

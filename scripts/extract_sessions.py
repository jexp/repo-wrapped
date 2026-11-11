#!/usr/bin/env python3
"""Claude Code sessions on THIS machine for the configured projects -> raw/sessions.jsonl.
Per session: start/end, human prompts, tool calls, subagents, active minutes (gaps < 5 min), and token usage per model and per git branch
(main transcript + subagent transcripts, de-duplicated by API message id, since streamed messages are logged several times)."""
import glob, json, os, re, sys, datetime as dt, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RAW, CFG

def norm_model(m):
    m = (m or "unknown").replace("accounts/fireworks/models/", "")
    return re.sub(r"-\d{3,}$", "", m)          # drop router revision suffix (deepseek-v4p1-flash-1017)

def usage_of(msg):
    u = msg.get("usage") or {}
    return {"msgs": 1, "in": u.get("input_tokens") or 0, "out": u.get("output_tokens") or 0,
            "cr": u.get("cache_read_input_tokens") or 0, "cw": u.get("cache_creation_input_tokens") or 0}

def scan(path, acc, main):
    """acc: {'ts':[], 'prompts', 'tools', 'subag', 'msgs': {msg_id: (branch, model, usage)}}"""
    try:
        for line in open(path, errors="replace"):
            try: e = json.loads(line)
            except Exception: continue
            t = e.get("timestamp")
            if t and main: acc["ts"].append(t)
            m = e.get("message")
            if main and e.get("type") == "user" and (e.get("origin") or {}).get("kind") == "human" and not e.get("isSidechain"): acc["prompts"] += 1
            if e.get("type") == "assistant" and isinstance(m, dict):
                if main and isinstance(m.get("content"), list):
                    for c in m["content"]:
                        if c.get("type") == "tool_use":
                            acc["tools"] += 1
                            if c.get("name") in ("Agent", "Task"): acc["subag"] += 1
                mid = m.get("id") or e.get("uuid")
                acc["msgs"][mid] = (e.get("gitBranch") or "", norm_model(m.get("model")), usage_of(m), not main or bool(e.get("isSidechain")))
    except Exception: pass

out = open(RAW + "sessions.jsonl", "w"); n = 0
rx = re.compile(CFG.get("sessions_match", "$^"), re.I)
for d in glob.glob(os.path.expanduser("~/.claude/projects/*")):
    if not rx.search(os.path.basename(d)): continue
    for f in glob.glob(d + "/*.jsonl"):
        sid = os.path.basename(f)[:-6]
        acc = {"ts": [], "prompts": 0, "tools": 0, "subag": 0, "msgs": {}}
        scan(f, acc, True)
        for sub in glob.glob(f"{d}/{sid}/subagents/*.jsonl"): scan(sub, acc, False)
        if not acc["ts"] or not acc["msgs"]: continue
        p = sorted(dt.datetime.fromisoformat(x.replace("Z", "+00:00")) for x in acc["ts"])
        active = sum(min((b - a).total_seconds(), 300) for a, b in zip(p, p[1:])) / 60
        models = collections.defaultdict(collections.Counter); by_branch = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
        for br, model, u, side in acc["msgs"].values():
            models[model].update(u); by_branch[br or "?"][model].update(u)
        out.write(json.dumps({"session": sid, "project": os.path.basename(d), "start": p[0].isoformat(), "end": p[-1].isoformat(),
                              "prompts": acc["prompts"], "tool_calls": acc["tools"], "subagents": acc["subag"], "active_min": round(active, 1),
                              "models": models, "by_branch": by_branch}) + "\n"); n += 1
print(n, "sessions", file=sys.stderr)

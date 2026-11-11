#!/usr/bin/env python3
"""Claude Code sessions on THIS machine for the configured projects -> raw/sessions.jsonl (one person only: other people's
transcripts are not on this machine). Per session: start/end, human prompts, tool calls, active minutes (gaps < 5 min)."""
import glob, json, os, re, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RAW, CFG
out = open(RAW + "sessions.jsonl", "w"); n = 0
for d in glob.glob(os.path.expanduser("~/.claude/projects/*")):
    if not re.search(CFG.get("sessions_match", "$^"), os.path.basename(d), re.I): continue
    for f in glob.glob(d + "/*.jsonl"):
        ts, prompts, tools, subag = [], 0, 0, 0
        try:
            for line in open(f, errors="replace"):
                try: e = json.loads(line)
                except Exception: continue
                t = e.get("timestamp")
                if t: ts.append(t)
                if e.get("type") == "user" and (e.get("origin") or {}).get("kind") == "human" and not e.get("isSidechain"): prompts += 1
                m = e.get("message")
                if e.get("type") == "assistant" and isinstance(m, dict) and isinstance(m.get("content"), list):
                    for c in m["content"]:
                        if c.get("type") == "tool_use":
                            tools += 1
                            if c.get("name") in ("Agent", "Task"): subag += 1
        except Exception: continue
        if not ts or prompts == 0: continue
        p = sorted(dt.datetime.fromisoformat(x.replace("Z", "+00:00")) for x in ts)
        active = sum(min((b - a).total_seconds(), 300) for a, b in zip(p, p[1:])) / 60
        out.write(json.dumps({"session": os.path.basename(f)[:-6], "project": os.path.basename(d), "start": p[0].isoformat(), "end": p[-1].isoformat(),
                              "prompts": prompts, "tool_calls": tools, "subagents": subag, "active_min": round(active, 1)}) + "\n"); n += 1
print(n, "sessions")

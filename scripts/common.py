"""Shared config: WRAPPED_CONFIG (path to configs/<name>.json) selects repos, people, area profile and the out/<name>/ directory."""
import json, os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CFG_PATH = os.environ.get("WRAPPED_CONFIG") or os.path.join(ROOT, "configs", "example-generic.json")
CFG = json.load(open(CFG_PATH))
NAME = CFG["name"]
OUT = os.path.join(ROOT, "out", NAME); RAW = os.path.join(OUT, "raw") + "/"; DATA = os.path.join(OUT, "data") + "/"
os.makedirs(RAW, exist_ok=True); os.makedirs(DATA, exist_ok=True)
REPOS = {r["name"]: r for r in CFG["repos"]}
PERSONS = json.load(open(os.path.join(os.path.dirname(CFG_PATH), CFG["persons"])))
CODE_EXTS = tuple(CFG.get("code_exts") or [".rs"])
LINEAR = CFG.get("linear")
def gh_url(repo): return "https://github.com/" + REPOS[repo]["github"]

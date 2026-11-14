"""Area profile. config "areas" = "generic" (top-level directory = area) or a path to a Python file (relative to the config)
that defines AREAS=[(id,label,group)], area_of(path), crate_of(path) and optionally CORE (set of area ids counted as core)."""
import importlib.util, os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
from common import CFG, CFG_PATH, CODE_EXTS
PROFILE = CFG.get("areas", "generic")
if PROFILE == "generic":
    AREAS = []; CORE = set()
    def crate_of(path): return None
    def area_of(path):
        p = path.replace("\\", "/"); return p.split("/", 1)[0] if "/" in p else "(root)"
elif PROFILE == "maven":
    # module = the directory path before src/ (Maven/Gradle layout), e.g. community/kernel/src/main/java/... -> community/kernel
    AREAS = []; CORE = set()
    def crate_of(path): return None
    def area_of(path):
        p = path.replace("\\", "/"); parts = p.split("/")
        if "src" in parts: i = parts.index("src"); return "/".join(parts[:i]) or "(root)"
        return parts[0] if len(parts) > 1 else "(root)"
else:
    _p = os.path.join(os.path.dirname(CFG_PATH), PROFILE)
    _s = importlib.util.spec_from_file_location("area_profile", _p); _m = importlib.util.module_from_spec(_s); _s.loader.exec_module(_m)
    AREAS, area_of, crate_of = _m.AREAS, _m.area_of, _m.crate_of; CORE = getattr(_m, "CORE", set())
AREA_IDS = [a[0] for a in AREAS]

def is_code(path): return path.endswith(CODE_EXTS)
def is_test(path):
    p = path.replace("\\", "/")
    return bool(re.search(r'(^|/)(tests?|testing|testdata|__tests__|spec|benches|bench|examples)/', p) or re.search(r'(_tests?|_test|_spec|\.test|\.spec|test_[a-z0-9_]+)\.[a-z]+$', p) or p.endswith("tests.rs"))
def kind(path):
    """prod_rs | test_rs | docs | other  (the *_rs names are legacy: they mean 'code in config code_exts')"""
    if is_code(path): return "test_rs" if is_test(path) else "prod_rs"
    if path.endswith((".md", ".html", ".adoc", ".rst")) or path.startswith("docs/"): return "docs"
    return "other"
def layout(observed):
    """[[group title, group id, [[area id, label]]]] for the page's architecture overlay"""
    if PROFILE == "generic": return [["Top-level directories", "dirs", [[a, a] for a in sorted(observed)]]]
    if PROFILE == "maven": return [["Modules", "modules", [[a, a] for a in sorted(observed)]]]
    groups = {}
    for i, l, g in AREAS: groups.setdefault(g, []).append([i, l])
    return [[g.title(), g, v] for g, v in groups.items()]

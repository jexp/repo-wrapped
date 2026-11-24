---
name: repo-wrapped
description: Set up and run repo-wrapped for a repo or team — write the config (repos, persons, areas, pricing, sessions), run the scanner, rebuild the CSVs and open the page, while avoiding the known pitfalls. Use when asked to configure, run, refresh, or debug repo-wrapped, or to generate wrapped CSVs for a GitHub repo.
---

# repo-wrapped setup and run

Per-person CSVs (commits, PRs, tickets, CI runs, Claude sessions) + a single-file HTML page
(`index.html?out=<name>`). Sources: local git clones, GitHub (`gh`), Linear (`everything-cli`),
`~/.claude/projects` transcripts (this machine only).

## 1. Create the config

Config lives in `private/` (gitignored) whenever it names non-public repos, people's emails or a
Linear team id — never in tracked `configs/`. Three files, all relative to each other:

`private/<name>.json`:
```json
{
  "name": "<name>",
  "title": "Human title",
  "repos": [{"name": "<key>", "github": "OWNER/REPO", "clone": "/abs/path", "refs": ["--all"]}],
  "linear": {"team": "<team UUID>", "workspace": "<urlKey>"},
  "persons": "<name>.persons.json",
  "areas": "<name>-areas.py",
  "code_exts": [".rs", ".go", ".py", ".ts", ".js", ".java", ".swift", ".c", ".h"],
  "sessions_match": "regex|on|project|dir|names",
  "repos_from_sessions": false,
  "since": "2026-01-01",
  "pricing": {"<model>": {"in": 0.3, "cr": 0.006, "cw": 0, "out": 1.2}}
}
```
`private/<name>.persons.json` — one entry per person:
```json
{"<id>": {"name": "Real Name", "git_names": ["Real Name"], "git_emails": ["a@x", "b@y"],
          "gh": ["login"], "linear": ["Real Name"], "sessions": true}}
```
Optional keys: `since` (floor date for commits, PRs and CI runs); `repos_from_sessions: true` makes
`update.py` read the cwd of every session matching `sessions_match`, resolve it to its GitHub origin
and clone, and add repos not yet configured (`scripts/discover_repos.py`, or `--only discover`).

Set `sessions: true` for exactly one person: the machine's own transcripts are all attributed to them.

## 2. Discover the facts — never assume them

- **Clone paths**: a repo can be cloned anywhere; find it (`find` by dir name) and confirm with
  `git -C <path> remote -v`. `refs: ["--all"]` captures all branches; `["origin/main"]` is the
  conservative choice.
- **Identities**: `git -C <clone> log --all --no-merges --format='%an|%ae' | sort | uniq -c | sort -rn`
  gives names/emails per repo — one person often has several (name variants, second email; check for
  a `.mailmap`). Map every distinct pair or commits silently drop.
- **GitHub logins do NOT follow from emails.** Verify each login against GitHub's commit-author
  association: `gh api repos/OWNER/REPO/commits --jq '.[] | [.commit.author.email, .author.login]'`
  (or PR author lists). Real case: William Lyon = `lyonwj@gmail.com` but login `johnymontana`.
  An assumed login drops that person's PRs and CI rows to zero.
- **Linear**: the config needs the team **UUID**, not the key:
  `everything-cli linear api 'query{ teams(first:20){ nodes{ id key name } } }'`;
  workspace from `query{ organization{ urlKey } }`. Person matching is by assignee display name.
- **Sessions**: `sessions_match` is a regex over `~/.claude/projects/*` folder names (path with `/`
  → `-`). Cover every project dir that is this work, and no others — list them first.

## 3. Areas profile (optional but worth it)

`"areas": "generic"` = top-level directory per area — useless for a workspace repo. A profile file
next to the config defines `AREAS=[(id,label,group)]`, `area_of(path)`, `crate_of(path)`, `CORE`.
`"areas": "maven"` maps Maven/Gradle modules (directory before `src/`) to areas. A profile may also
define `EDGES=[(from_id,to_id)]` (or config `"edges"`) to draw a layered architecture diagram with
density colouring, and `GROUPS` (group id -> title, ordered top to bottom as layers; a group named
`sdlc` is a side column). Robust pattern: discover the crate/dir set from the configured clones at import time
(`os.listdir` each clone's `relate/`, `surfaces/`, … via `common.REPOS`) instead of hardcoding —
new crates then need no config edit, just a rebuild.

## 4. Pricing

Keys must match the **normalized** model ids the session extractor writes: `accounts/fireworks/models/`
stripped, trailing `-<3+digits>` revision dropped. `in/out` = USD per 1M tokens; `cr` = cached input;
`cw` = cache write (0 where the provider charges none, e.g. Fireworks). Unpriced models cost 0 —
the `extra` column lists them as `unpriced=...`. Find the ids actually present before pricing:
scan `~/.claude/projects/<dir>/*.jsonl` for `"message"."model"` (in Python; `grep -o` on transcripts
misfires — see pitfalls). Fireworks serverless rates: `https://fireworks.ai/pricing`.

## 5. Run

```bash
cd <repo-wrapped>/scripts
python3 update.py --config ../private/<name>.json          # additive: only what changed
python3 update.py --config ... --only build                # rebuild CSVs from raw/ (e.g. after pricing edit)
python3 update.py --config ... --full                      # refetch everything (old CI workflows need this)
```
Output: `out/<name>/raw/*.jsonl` (the durable source of truth) and `out/<name>/data/{<person>.csv,
manifest.json, bundle.js}`. Open with `index.html?out=<name>` — the page reads only `bundle.js`
(browsers block `file://` config fetches; that is why title + repo list are copied into it).

## 6. Verify

- `wc -l out/<name>/raw/*.jsonl` — commits, PRs per repo, runs, linear issues, sessions all nonzero
  (unless genuinely none).
- Per-person row counts print at build; any person with 0 rows = identity mismatch (section 2).
- Cost columns: sessions 24/24 costed, PRs with `cost_usd` > 0 only after `pricing` is set.

## Pitfalls (all hit in practice)

- **`private/` is the config's only home and it is gitignored** — a config left there exists on one
  machine only. Keep a copy elsewhere (second machine or a private repo) or it gets lost.
- **First run is a full fetch**: every PR and every CI run of every repo (a busy repo has ~18k runs)
  — run it in the background, expect minutes.
- **Additive forever**: raw files are upserted by id and never pruned; rows deleted upstream stay.
  Fix data in `raw/` or at the source — **never** in the CSVs, which are rebuilt wholesale.
- **Commits double-count** under `refs: ["--all"]` (all branches); the page therefore uses PRs for
  lines and person-days. PR lines are each PR's final diff, scaled when >100 files.
- **PR cost is joined by branch name**: two PRs that lived on one branch show the same (duplicate)
  spend — read them as one workstream.
- **Sessions are one machine's**; other people's agent usage appears only as bot comments and
  agent co-author trailers on commits.
- **Shell quoting of transcript dirs**: `~/.claude/projects` folders start with `-` (e.g.
  `-Users-mh-...`), so `grep`/`find` treat them as flags — prefix `./`. And transcripts contain long
  lines/NULs that make `grep` call them binary and return nothing: use `grep -a` or Python.
- **`git -C` and clone paths in the config must be absolute**; the scanner chdir's to `scripts/`.
- **Localize costs to request mode**: pricing is per model, not per request — Priority/Fast/Spot
  modes on the provider are not represented.

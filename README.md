# repo-wrapped

A "Wrapped" for any GitHub repo: per-person CSVs (commits, PRs, tickets, CI runs, agent sessions) and a single-file HTML page with heatmap, comment/CI/LOC charts, an architecture overlay, complexity and a person-days estimate (prod and test separate).

## Use
```
# 1. describe the repo(s) and people
cp configs/example-generic.json configs/myrepo.json   # + configs/myrepo.persons.json
# 2. pull + build (additive on every re-run; needs gh, git clones, optionally everything-cli for Linear)
python3 scripts/update.py --config configs/myrepo.json
# 3. open the page
open "index.html?out=myrepo"
```
`update.py` flags: `--full` refetch everything, `--only git,prs,runs,linear,sessions,build`.

## Config (`configs/<name>.json`)
- `title` (optional): fallback heading before data loads; the heading itself shows the repo with the most recent activity among the selected people (`<repo> Wrapped`). The page can't read the config file itself (browsers block `file://` fetches), so the build copies the title and repo list into `bundle.js`; clone paths, pricing and team ids are never copied
- `repos[]`: `name`, `github` (owner/repo), `clone` (local path), `refs` (git log refs, e.g. `["origin/main"]` or `["--all"]`)
- `persons`: file mapping person id to git names/emails, GitHub logins, Linear names, `sessions: true` for the person whose Claude transcripts are on this machine
- `linear`: `{team, workspace}` or `null`
- `areas`: `generic` (top-level directory = area) or a Python file next to the config defining `AREAS=[(id,label,group)]`, `area_of(path)`, `crate_of(path)`, optional `CORE`, for a custom architecture overlay
- `code_exts`: extensions counted as code (prod vs test split by path heuristic)
- `sessions_match`: regex on `~/.claude/projects/*` folder names

## Layout
`scripts/` pull + build, `configs/` per-repo config (keep private ones in `private/`, gitignored), `out/<name>/{raw,data}` generated (gitignored, including every CSV), `index.html` the page.

## Notes
- Re-runs are additive and idempotent: each source keeps a watermark from the stored data and upserts by id (PR number, run id, issue id, repo+sha, session id), so history is never lost or duplicated. The CSVs are derived output, rebuilt from `out/<name>/raw` on every run, so add data to the raw files or the sources, not to the CSVs. Known gaps: re-runs of old CI workflows need `--full`; rows deleted upstream are never removed. PR lines are each PR's final diff (scaled when a PR has more than 100 files); commit rows span all branches and double count, so the page uses PRs for lines and person-days.
- Complexity (1–10) and the person-days rates are heuristics; tune them in `build_csv.py` / the page sliders.
- Only the machine's own Claude sessions are visible; other people's agent usage shows up as bot comments and agent commit trailers.

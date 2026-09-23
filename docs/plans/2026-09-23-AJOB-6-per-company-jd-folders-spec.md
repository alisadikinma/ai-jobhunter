**Ticket:** AJOB-6

## Design

### Problem

Discovered postings only exist as rows in `.jobhunter/queue/jobs.jsonl` — no
human-browsable per-job JD text on disk. `tailor` writes its output to
`.jobhunter/applications/<slug>/`, a flat directory keyed by one combined
company+title slug, disconnected from the discovery source. There is no way
to see, at a glance, "what did we find for company X" without querying the
queue, and no mechanism to avoid re-running the full tailoring workflow when
the same templated JD is reposted by a different company (a common pattern:
recruiters and staffing agencies repost near-identical postings for several
clients).

### Goals

1. Every discovered posting gets a human-browsable JD file, organized by
   source and company, not just a queue row.
2. `tailor`'s output (CV, cover letter, requirements map, keyword report)
   lives next to the JD it was written for, in the same folder.
3. Re-tailoring a near-duplicate JD (same template, different company) gets
   a fast path that still respects the existing agreement-gate and
   evidence-provenance rules — no auto-approval, no invented company facts.

### Non-goals

- No migration of old data — `.jobhunter/applications/` does not exist yet
  in the reference project, so this ships as a clean cutover, not a
  migration.
- No change to `discover`'s jobsync boundary — it still never calls a
  jobsync MCP tool. This only adds a second *local* file write.
- No change to `score` or `promote` — they keep reading from the queue as
  they do today.

### Design

#### 1. Folder layout

Replace `.jobhunter/applications/<slug>/` with a source-keyed tree, rooted
at a new top-level `Data/` directory (sibling of `.jobhunter/`, in the
user's own project — not inside the plugin):

```
Data/
  LinkedIn/<Company>/<Role-slug>/
  Greenhouse/<Company>/<Role-slug>/
  Lever/<Company>/<Role-slug>/
  Ashby/<Company>/<Role-slug>/
    JD.md
    requirements-map.md
    cv.md
    cover-letter.md
    cv.pdf
    cover-letter.pdf
    keyword-report.md
```

The source-level folder name is exactly the queue row's `source` field —
`LinkedIn`, `Greenhouse`, `Lever`, `Ashby` (the four values `SOURCE_*`
constants in `apify.py` / `ats.py` already produce; no new naming scheme).
Board-search rows use whatever `source` value `queue-append` already accepts
today — unchanged.

`<Company>` and `<Role-slug>` are derived with the same slugging logic
`tailor` already uses for its single combined `<slug>`, split into two path
segments instead of one string. Filesystem-unsafe characters (`/`, `:`,
etc.) go through the same sanitizer.

#### 2. `discover` — extended write

`discover` keeps writing to `.jobhunter/queue/jobs.jsonl` as its primary
output (unchanged contract for scoring/promote). It additionally writes
`Data/<Source>/<Company>/<Role-slug>/JD.md` for every row that is **new**
this run (i.e. not a duplicate by `jobq.row_key`), containing the row's full
`jobDescription` text.

If the target folder already exists (a prior discover run already
materialized it, or `tailor` has already started work there), `discover`
does **not** overwrite `JD.md` — this protects in-progress or completed
tailor work from being clobbered by a rediscovery of the same posting later.
This mirrors the queue's own dedupe-by-`row_key` semantics, applied to the
filesystem.

`discover`'s `SKILL.md` "Output" section is updated to document this second
write target; it is still true that discover never writes to jobsync or
`.jobhunter/profile/`.

#### 3. `tailor` — relocated output, folder-based input

`tailor` gains a new input mode: point it at an existing
`Data/<Source>/<Company>/<Role-slug>/` folder (by path, or by
company + role identification) and it reads `JD.md` from there, in addition
to the existing three input modes (queue row, URL scrape, pasted text).

All of `tailor`'s output — `requirements-map.md`, `cv.md`,
`cover-letter.md`, `cv.pdf`, `cover-letter.pdf`, `keyword-report.md` — is
written into that same folder, replacing `.jobhunter/applications/<slug>/`
as the output root. Every existing rule stays in force unchanged: the
agreement gate blocks all writes until every row is agreed, `master-cv.md`
is never sent as-is, `render-pdf`/`render-docx` refuse on unresolved
`[verifikasi]`/`[Assumption]` markers, portal detection still picks DOCX
rendering for enterprise ATSes.

#### 4. Near-duplicate JD detection (new)

Before starting a fresh requirements-map walk, `tailor` checks the new JD
against every **previously tailored** JD (one whose
`requirements-map.md` carries an `approved:` line) for a near-duplicate
match:

1. Normalize both JD texts — strip the company name and any location line,
   lowercase, collapse whitespace.
2. Compute similarity with `difflib.SequenceMatcher(None, a, b).ratio()`
   (standard library — consistent with the project's stdlib-only rule).
3. A ratio ≥ **0.90** against any prior JD counts as a match. Below that,
   proceed with the normal from-scratch flow.
4. On a match, tell the user which company/role it matched and the exact
   ratio, then ask (AskUserQuestion): reuse the matched
   `requirements-map.md` as the **starting draft** for this JD's map (still
   walked row by row through the existing agreement gate — nothing is
   auto-approved), or discard it and build the map from scratch.
5. Regardless of that choice, the cover letter's company-specific paragraph
   (hiring-manager name / referral / "why this company" line) is always
   rebuilt or reconfirmed with the user for the new company — it is never
   copied from the matched application. This preserves the existing
   "nothing invented" rule; a reused paragraph praising the wrong company is
   exactly the kind of fabrication that rule exists to prevent.

### Data Integration Map

| Component | Data source | Existing? | Notes |
|---|---|---|---|
| `Data/<Source>/<Company>/<Role>/JD.md` | `discover` (per new queue row) | Partial — queue write exists, file write is new | Skips write if folder already exists |
| `requirements-map.md`, `cv.md`, `cover-letter.md`, `*.pdf`, `keyword-report.md` | `tailor` | Existing, relocated | Same generation logic, new output root |
| Near-duplicate match set | `tailor`, scanning `Data/**/requirements-map.md` for `approved:` | New | stdlib `difflib` only |

### Error handling

- `discover` folder write failure (permissions, disk full) is reported
  per-row in the existing `skipped` reporting mechanism — it does not fail
  the queue append, which is the run's primary output.
- `tailor` pointed at a folder with no `JD.md` → same
  `MissingFieldError`-style refusal the skill already raises for an
  unreadable JD source; no silent fallback to a generic document.
- Folder-name collisions (two different roles slugging to the same
  `<Role-slug>` under one company) — `tailor` and `discover` both need a
  deterministic disambiguation rule (e.g. append a short suffix derived
  from the job ID). Left as an open implementation decision for
  `gaspol-plan` to pin down with a concrete algorithm and test.

### Test impact

The project carries 857 unit tests (`python3 -m unittest discover -s tests
-t .`) plus a manifest test enforcing "nothing candidate-specific ships
under `skills/`". Expect:
- New/updated tests for `discover`'s folder-write behavior (new file, skip
  on existing folder, per-row error reporting).
- Updated tests for `tailor`'s new input mode and relocated output path
  (every existing `tailor` test that asserts on
  `.jobhunter/applications/<slug>/...` moves to the new path).
- New tests for the near-duplicate detector: exact match, near match at the
  threshold boundary, no match, and the "cover-letter paragraph always
  reconfirmed" behavior.

### Open questions for `gaspol-plan`

- Exact slug-collision disambiguation algorithm (see Error handling above).
- Whether `queue-list` / `queue-update` or any promote-path code reads
  `.jobhunter/applications/` by path anywhere and needs updating in lockstep
  (grep during planning, not assumed here).

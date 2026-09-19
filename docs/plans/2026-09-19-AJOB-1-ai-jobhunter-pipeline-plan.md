> **For Claude:** REQUIRED SKILL: Use gaspol-execute to implement this plan.
> **CRITICAL:** This plan specifies real integrations. During execution,
> NEVER substitute placeholders for real data sources without explicit
> user approval. If a data source doesn't exist yet, STOP and ask.
> **Progress ledger — HARD PER-PHASE GATE:** `.gaspol/progress/PROGRESS-AJOB-1.md`. After EACH phase and **BEFORE** starting the next, STOP and do BOTH: (a) tick that phase's `## Checklist` line, (b) append a `## Log` line ending with the handoff cursor. This is **blocking**, like a test gate: no next phase until both are written. **Never batch all updates at the end.** Update ONLY this file — never the shared `.gaspol/progress.md`.
> **Self-contained:** this plan is the COMPLETE spec. It must be executable by an agent with **no other context**. Every file path, contract, config key and convention it needs is written here verbatim.

**Ticket:** AJOB-1
**Ledger:** .gaspol/progress/PROGRESS-AJOB-1.md
**Spec:** docs/plans/2026-09-19-AJOB-1-ai-jobhunter-pipeline-spec.md
**Artifact:** https://claude.ai/artifact/HjE6YSXbX9Ptu8fvqnfiYG

## Goal

Build `ai-jobhunter`, a generic and publicly distributable Claude Code plugin that runs a
job hunt as a pipeline: discover roles, score them against a candidate profile, write a CV
and cover letter for one specific job description, draft recruiter outreach, and promote
the roles worth pursuing into a self-hosted jobsync tracker over MCP. Nothing
candidate-specific is bundled; everything personal arrives at runtime from `.jobhunter/`
in the user's own project. The deterministic parts — ATS fetching, the local queue,
deduplication, keyword overlap, request budgeting, jobsync payload construction — are
Python with tests. The judgement parts — scoring, tailoring, outreach copy — are Claude,
governed by evals rather than unit tests.

## Architecture Context

This project is new: `CLAUDE.md` at the repo root records only the plugin's purpose and the
ticket counter (`Prefix: AJOB`). There is no prior code to reuse inside this repo.

Two external things already exist and are not rebuilt here:

- **jobsync** — self-hosted tracker, running at `http://localhost:3737`, cloned to
  `/Users/alisadikin/Drive-D/Projects/jobsync`. Started with `docker compose up -d`; its
  `.env` holds generated `AUTH_SECRET` / `ENCRYPTION_KEY` and `MCP_ENABLED=true`. Its MCP
  endpoint is `http://localhost:3737/api/mcp` and rejects any request without
  `Authorization: Bearer <token>` (verified: HTTP 401).
- **`jobhunter-plugin` v0.2.0** at `/Users/alisadikin/Drive-D/claude-plugin/jobhunter-plugin`
  — the retired predecessor. Its `refs/refs-scoring.md`, `refs/refs-cv.md`,
  `refs/refs-email.md` and `refs/refs-contact.md` are useful prior art to read while writing
  the SKILL.md files in Phase F. Do not copy its backend-callback architecture: this plugin
  has no backend.

## Tech Stack

- **Python 3 standard library only.** No third-party packages, no `requirements.txt`, no
  virtualenv. Verified present: Python 3.14.7. `urllib.request`, `json`, `tomllib`, `re`,
  `hashlib`, `datetime`, `pathlib`, `unittest` cover everything this plan needs.
- **Config is TOML, never YAML.** The standard library ships `tomllib` (read-only, 3.11+)
  and no YAML parser. Using YAML would force a dependency and break the promise above.
- **Tests are `unittest`**, not pytest — pytest is not installed and a public plugin must
  not require users to install anything. `ruff` is likewise not installed and is not used.
- **Skills are Markdown** (`skills/<name>/SKILL.md`), invoked as `/ai-jobhunter:<name>`.
- Network access lives in exactly one module and is never exercised by a test; tests read
  recorded JSON fixtures from disk.

### Verification commands for this project

`detect-stack` printed **zero lines** for this repo (no stack markers existed when it ran,
the project being empty). The commands below are therefore plan-declared, and every phase
uses these exact two:

- static: `python3 -m compileall -q scripts tests`
- unit: `python3 -m unittest discover -s tests -t . -v`

## Data Integration Map

| Feature | Data Source | Hook/API | Exists? | Action |
|---|---|---|---|---|
| Profile from website | `https://<user site>` | `mcp__firecrawl__firecrawl_scrape` | Yes — verified 2026-09-19, HTTP 200, 1 credit | Use existing MCP tool from the skill |
| Profile from LinkedIn | user-exported PDF | `mcp__xberg__extract_file` | Yes | Use existing MCP tool; native Read cannot parse PDF |
| Jobs from boards | LinkedIn/Indeed/etc. pages | `mcp__firecrawl__firecrawl_search`, `..._scrape` | Yes | Use existing MCP tools from the skill |
| Jobs from companies | Greenhouse/Lever/Ashby public JSON | `scripts/ats.py` | **No** | Create real HTTP client (Phase C) |
| New-posting watch | career pages | `mcp__firecrawl__firecrawl_monitor_create` | Yes | Use existing MCP tool from the skill |
| Local work queue | `.jobhunter/queue/jobs.jsonl` | `scripts/jobq.py` | **No** | Create (Phase A) |
| Config + profile paths | `.jobhunter/config.toml` | `scripts/config.py` | **No** | Create (Phase B) |
| Keyword coverage | JD text + master CV | `scripts/keywords.py` | **No** | Create (Phase D) |
| jobsync payloads + budget | queue rows | `scripts/promote.py` | **No** | Create (Phase E) |
| jobsync write | `http://localhost:3737/api/mcp` | jobsync MCP tools | Yes — server running, token pending | Skill calls the MCP tools; `promote.py` only builds and validates the payloads |
| Scoring judgement | JD + profile | Claude (Sonnet) | n/a | Governed by `docs/evals/scoring.md` (Phase G) |
| CV + cover letter | JD + profile | Claude (Opus) | n/a | Governed by `docs/evals/tailoring.md` (Phase G) |
| Outreach draft | contact + JD + profile | Claude + Gmail MCP | Gmail MCP **unverified** | Phase F writes the `.eml` fallback path; skill must check availability at run time and say which it used |

## jobsync MCP contract (read from source 2026-09-19 — do not re-derive)

Read from `/Users/alisadikin/Drive-D/Projects/jobsync/src/models/mcp.schema.ts` and
`wiki/mcp.md` on the running instance. Nine tools, **all writes**: `add_job`,
`add_jobs_batch` (max 10), `find_job`, `update_job`, `add_question`, `review_resume`,
`save_resume_review`, `save_match_result`, `save_match_results_batch`.

**There is no list/read tool.** An agent cannot ask jobsync what is unscored. This is why
the working queue is local.

**Rate limit: 60 MCP requests per hour**, across every tool and token. A batch costs one
request *per item*. `add_job` with `upsert: true` makes `find_job` unnecessary on re-runs,
which halves the cost per job — use `upsert`, not `find_job`.

`add_job` / `add_jobs_batch` item fields:

| Field | Type | Notes |
|---|---|---|
| `company` | string, required | min length 1 |
| `jobTitle` | string, required | min length 1 |
| `jobDescription` | string, required | **≥10 chars, or the literal `"N/A"`**. Full posting text, not summarised |
| `location` | string, optional | city/state/country or `Remote`; no street address |
| `source` | string, optional | board name; infer from URL domain when unstated |
| `jobType` | string, optional | `Full-time` / `Part-time` / `Contract` |
| `workplaceType` | enum, optional | **`Remote` / `Hybrid` / `Onsite`** — case and separators are folded, so `On-site` and `REMOTE` validate |
| `status` | enum, optional | lower-cased before checking; defaults to jobsync's own default |
| `dueDate` | ISO-8601 with offset, optional | |
| `applied` | bool, optional | |
| `appliedDate` | ISO-8601 with offset, optional | |
| `jobUrl` | URL, optional | |
| `salaryRange` | string, optional | free-form, e.g. `$120k–$150k` |
| `tags` | string[], optional | **max 10 applied, extras silently dropped** |
| `allowDuplicate` | bool, optional | force-create; not used by this plugin |
| `upsert` | bool, optional | **set `true` on every promote run** |

`save_match_result` / `save_match_results_batch` item fields:

| Field | Type | Notes |
|---|---|---|
| `jobId` | string, required | the id `add_job` returned |
| `resumeId` | string, optional | as given in the add_job directive |
| `matchText` | string, ≥20 chars, required | **must begin** `SCORES: match=<0-100> recommendation=<strong\|good\|partial\|weak>` then a markdown body |

**`review_resume` and `save_resume_review` are out of scope for v1.** Their schema requires
an `ats=<0-100>` number in the SCORES line, and spec §6 decided this plugin does not claim
an ATS score. Using them would contradict that decision.

**`work_authorization` has no field in jobsync.** Carry it as a tag — `visa:open`,
`visa:unclear`, `visa:closed` — and restate it in the `matchText` body. Tags are capped at
10, so the tag budget is: 1 visa tag, 1 variant tag, up to 8 skill tags.

**Score mapping**, fixed here so it is not re-invented per run:

| `fit_score` | `recommendation` |
|---|---|
| 80–100 | `strong` |
| 65–79 | `good` |
| 50–64 | `partial` |
| 0–49 | `weak` |

## Scored-row field contract (pinned 2026-09-19)

After `/ai-jobhunter:score` runs, a queue row carries these fields in addition to the ones
`normalize_*` produced. `promote.py` reads exactly these names; `score`'s SKILL.md must write
exactly these names.

| Field | Type | Notes |
|---|---|---|
| `fit_score` | int 0-100 | absent or `None` means unscored, and `promote` refuses the row |
| `score_reasons` | dict | one entry per rubric dimension; the salary entry is **absent** when the posting states no salary, never `0` |
| `work_authorization` | `"open"` / `"unclear"` / `"closed"` | `closed` rows are refused for promotion |
| `suggested_variant` | str | a key from the user's `variants.toml` |
| `skills` | ordered list of str | drives the skill tags; only the first 8 survive the tag cap |

## Phases

### Phase A: local queue — append, dedupe, read

**Estimated time:** 12 minutes

**Files:**
- Create: `scripts/jobq.py`
- Create: `tests/test_jobq.py`, `tests/__init__.py`

**Steps:**
1. Write failing test for `jobq.append_rows` writing one JSONL line per row to a temp queue path. Expected error: `ModuleNotFoundError: No module named 'jobq'`
2. Run `python3 -m unittest discover -s tests -t . -v`, confirm it fails for that reason
3. Implement `scripts/jobq.py` with `load(path)`, `append_rows(path, rows)`, `row_key(row)`, `iter_unscored(rows)`, `iter_unpromoted(rows)` and `update_rows(path, updates, key=row_key)`. `row_key` is `sha256` of `jobUrl` when present, else of `company|jobTitle|location` lower-cased and whitespace-collapsed. `iter_unpromoted` yields rows with no truthy `promoted` field — without it the promote step re-upserts rows already in jobsync and spends the hourly budget twice. `update_rows` merges fields into matching rows by writing a temp file and `os.replace`-ing it, preserving the existing file mode and any line it could not parse verbatim
4. Add tests for the enumerated edge cases: empty file, missing file, a row with no `jobUrl`, two rows differing only by URL query string, a duplicate appended twice, a malformed (non-JSON) line, 1000 rows, and a row whose `company` differs only by trailing whitespace
5. Run tests, confirm all pass
6. Commit: "feat(queue): local JSONL work queue with URL-and-identity dedupe"

**Completeness ladder:**
- Happy path: rows append and read back in order.
- Error paths: unreadable file, malformed JSONL line (skip it and count it — never abort the run over one bad line), unwritable directory.
- Edge cases: empty, missing, single row, duplicate, URL differing only by query string, whitespace-only fields, 1000 rows.
- Observability: `append_rows` returns `(written, skipped_duplicates, malformed)` so a caller can print real counts.

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t . -v` passes
- [ ] A malformed line is counted and skipped, and does not abort the read
- [ ] Re-appending an identical row writes nothing and reports one skipped duplicate
- [ ] No placeholder/TODO comments in new code

### Phase B: config + profile paths

**Estimated time:** 12 minutes

**Files:**
- Create: `scripts/config.py`
- Create: `tests/test_config.py`
- Create: `templates/config.toml`

**Steps:**
1. Write failing test for `config.load` reading `.jobhunter/config.toml` and returning budgets. Expected error: `ModuleNotFoundError: No module named 'config'`
2. Run tests, confirm it fails for that reason
3. Implement `scripts/config.py` using `tomllib`, with defaults: `budgets.firecrawl_credits_per_run = 150`, `budgets.jobsync_requests_per_run = 50`, `targets.min_salary_usd = 0` meaning **unset**
4. Add tests for: file missing (raise a named error that tells the user to run `/ai-jobhunter:profile`), malformed TOML, unknown top-level key (warn, do not fail), `min_salary_usd` absent vs `0`, a relative `linkedin_pdf` path resolving against the config file's own directory
4b. Implement `resolve_profile_sources(cfg)` returning an ordered list of `(tier, path_or_url)`. **Project directories are allow-listed:** only names in `profile_sources.projects.allowed` are returned, joined onto `projects.root`. The function never lists the root directory to discover candidates
4c. Add tests for the allow-list: a directory present on disk but absent from `allowed` is **not** returned; an `allowed` name that does not exist raises a named error rather than being skipped silently; an `allowed` entry containing `..` or an absolute path is rejected; an empty `allowed` returns no project sources; `allowed` names are matched exactly, with no glob expansion
5. Write `templates/config.toml` containing the commented example from spec §4 verbatim
6. Run tests, confirm all pass
7. Commit: "feat(config): TOML config loader with explicit budget defaults"

**Completeness ladder:**
- Happy path: a valid config returns a typed dict with every default filled, plus an ordered source list.
- Error paths: missing file, malformed TOML, wrong value type for a budget, an allow-listed project directory that does not exist, a path-traversal attempt in `allowed`.
- Edge cases: absent vs `0` for `min_salary_usd` (absent and `0` both mean unset and must not be treated as a real floor), empty `companies`, empty `allowed`, relative vs absolute paths, unknown key, a project directory on disk that is not allow-listed.
- Observability: the loader reports which values came from the file and which from defaults, and prints the resolved source list in precedence order so the user can see exactly what will be read.

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t . -v` passes
- [ ] `min_salary_usd = 0` and an absent key both resolve to "unset", not to a zero floor
- [ ] A missing config raises an error naming the skill that creates it
- [ ] A project directory present on disk but absent from `allowed` is never returned
- [ ] An `allowed` entry containing `..` or an absolute path is rejected
- [ ] No placeholder/TODO comments in new code

### Phase C: ATS fetchers (Greenhouse, Lever, Ashby)

**Estimated time:** 15 minutes

**Files:**
- Create: `scripts/ats.py`
- Create: `tests/test_ats.py`
- Create: `tests/fixtures/greenhouse_acme.json`, `tests/fixtures/lever_acme.json`, `tests/fixtures/ashby_acme.json`

**Steps:**
1. Write failing test for `ats.normalize_greenhouse(fixture)` returning queue rows with `company`, `jobTitle`, `jobDescription`, `jobUrl`, `location`, `source="Greenhouse"`. Expected error: `ModuleNotFoundError: No module named 'ats'`
2. Run tests, confirm it fails for that reason
3. Record the three fixtures by trimming a real response from the verified endpoints above down to 2–3 postings each; commit them as files so **no test ever touches the network**
4. Implement `scripts/ats.py`: one `fetch(board, slug, dest)` using `urllib.request` with a timeout that **streams the response to `dest`** (boards reach 5 MB), and one pure `normalize_<board>(path)` per provider reading from disk. Fetch and normalise stay separate so normalisation is testable offline
5. Add tests for: empty job list, a posting with no location, HTML-only description (strip tags, keep text), a description under 10 characters (must emit `"N/A"`, because jobsync rejects 1–9 characters), a non-JSON response body, HTTP 404 carrying `{"ok":false,"error":"Document not found"}`, a timeout, an Ashby row with `isListed: false` (must be dropped), and a Greenhouse `location.name` that maps to no workplace type (field must be absent, not guessed)
6. Run tests, confirm all pass
7. Commit: "feat(ats): Greenhouse/Lever/Ashby fetch and normalisation"

**Completeness ladder:**
- Happy path: each provider's payload becomes valid queue rows.
- Error paths: 404, 500, timeout, non-JSON body, provider schema change (a missing expected key names the key in the error).
- Edge cases: zero postings, missing location, HTML description, description under 10 chars, duplicate postings inside one payload, non-ASCII company name.
- Observability: `fetch` logs board, slug, HTTP status and row count.

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t . -v` passes
- [ ] No test performs network I/O — run the suite with `socket.socket.connect`,
      `connect_ex`, `create_connection` and `getaddrinfo` raising; every test still passes
- [ ] A description under 10 characters normalises to `"N/A"`, satisfying the jobsync minimum
- [ ] No placeholder/TODO comments in new code

### ATS endpoints — verified live 2026-09-19 (do not re-derive)

No registration, no API key, no account. Each provider exposes a public JSON board keyed by
the company's own slug, taken from its careers URL.

| Provider | Endpoint | Verified |
|---|---|---|
| Greenhouse | `https://boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=true` | HTTP 200, 667 jobs, 5.1 MB (slug `stripe`) |
| Lever | `https://api.lever.co/v0/postings/<slug>?mode=json` | HTTP 200, 11 postings (slug `leverdemo`) |
| Ashby | `https://api.ashbyhq.com/posting-api/job-board/<slug>` | HTTP 200, 148 jobs, 2.5 MB (slug `ramp`) |

Slug source: `boards.greenhouse.io/<slug>`, `jobs.lever.co/<slug>`, `jobs.ashbyhq.com/<slug>`.
A slug that is not a customer of that provider returns a clean failure — Lever answers HTTP
404 with body `{"ok":false,"error":"Document not found"}` — so a wrong slug is detectable,
never silently empty.

Response keys actually returned, read off the live payloads:

| Provider | Container | Per-job keys used |
|---|---|---|
| Greenhouse | `{"jobs":[...]}` | `title`, `content` (HTML-escaped), `absolute_url`, `location.name`, `company_name`, `id`, `updated_at` |
| Lever | top-level array | `text` (title), `descriptionPlain`, `hostedUrl`, `categories`, `workplaceType`, `country`, `id` |
| Ashby | `{"jobs":[...]}` | `title`, `descriptionPlain`, `descriptionHtml`, `jobUrl`, `applyUrl`, `location`, `isRemote`, `workplaceType`, `employmentType`, `isListed`, `id` |

Two consequences for the implementation:

1. **Payloads are large** (5 MB for one Greenhouse board). `fetch` must stream to a file and
   `normalize_*` must read it from disk. Never load a whole board into conversation context.
2. **Only Ashby and Lever state `workplaceType` directly.** Greenhouse gives free-text
   `location.name` only. `normalize_greenhouse` reads the arrangement **solely from words
   that state one** — `remote`, `hybrid`, `on-site`/`onsite`, `in-office` — and leaves the
   field absent otherwise. A bare place name says where an office is, not how the role is
   worked: measured on the live 667-job Stripe board, 560 locations were a place name alone
   and **none** said "hybrid" or "onsite". Reading those as `Onsite` invented an arrangement
   for 329 postings. Conversely, a separator must not veto a stated word — "NYC or Remote"
   is remote. After the word-only rule: 107 `Remote`, 560 absent, zero invented values.
   Hybrid wins over Remote when both appear, being the narrower statement.
   Ashby also carries `isListed`: rows where it is false are not public and must be dropped.

### Phase D: keyword coverage report

**Estimated time:** 12 minutes

**Files:**
- Create: `scripts/keywords.py`
- Create: `tests/test_keywords.py`

**Steps:**
1. Write failing test for `keywords.coverage(jd_text, cv_text)` returning `covered` and `missing` term lists. Expected error: `ModuleNotFoundError: No module named 'keywords'`
2. Run tests, confirm it fails for that reason
3. Implement extraction: lower-case, split on non-word characters, drop a stopword list defined in the module, keep 1–3 word phrases that appear in the JD, then compare against the CV text
4. Add tests for: empty JD, empty CV, a term appearing only inside a longer word (`java` inside `javascript` must not count as covered), case and punctuation differences, a hyphenated term (`end-to-end`), a term repeated many times (counted once), and non-ASCII text
5. Implement `render(report)` producing the `keyword-report.md` body, whose heading states it is a **keyword overlap report, not an ATS score**
6. Run tests, confirm all pass
7. Commit: "feat(keywords): JD-vs-CV coverage report"

**Completeness ladder:**
- Happy path: covered and missing terms, ranked by JD frequency. The report is truncated to `DEFAULT_TOP_N = 40` terms per list unless `--top` says otherwise — an untruncated report ran to 699 lines and 12.3 KB, which is not a thing a candidate reads before applying. Both headings state the full count so the truncation is never silent..
- Error paths: empty or whitespace-only input on either side (return an empty report with a stated reason, never divide by zero).
- Edge cases: substring false positives, hyphenation, casing, repeats, non-ASCII, a CV longer than the JD and the reverse.
- Observability: the rendered report states how many terms were extracted and how many survived stopword removal.

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t . -v` passes
- [ ] `java` in the CV does not mark `javascript` covered, nor the reverse
- [ ] The rendered heading says keyword overlap and does not claim an ATS score
- [ ] No placeholder/TODO comments in new code

### Phase E: promote — payload building and request budget

**Estimated time:** 15 minutes

**Files:**
- Create: `scripts/promote.py`
- Create: `tests/test_promote.py`

**Steps:**
1. Write failing test for `promote.to_add_job(row)` producing a dict with `upsert: True` and a `workplaceType` of exactly `Remote`, `Hybrid` or `Onsite`. Expected error: `ModuleNotFoundError: No module named 'promote'`
2. Run tests, confirm it fails for that reason
3. Implement `to_add_job(row)` (field mapping per the contract table above), `to_match_text(row)` (the `SCORES: match=<n> recommendation=<...>` first line plus a markdown body that names the work-authorization bucket), `build_tags(row)` (1 visa tag + 1 variant tag + up to 8 skill tags, hard-capped at 10), `chunk(rows, 10)`, `plan_budget(rows, limit)` returning what fits and what waits, and `match_quality(row)` implementing spec §8's two posting-text rules: a posting under `FULL_MATCH_MIN_WORDS = 150` words returns `"provisional"` (promote it, but say in `matchText` that the match is *Provisional*), and a title-only row — one whose cleaned `jobDescription` is the `N/A` sentinel — raises `TitleOnlyError` and is never promoted at all, because jobsync cannot produce a match without the posting text
4. Add tests for: a row missing `jobDescription` (emits `"N/A"`), `workplaceType` given as `On-site` and as `REMOTE`, `fit_score` exactly 80 / 79 / 65 / 64 / 50 / 49 / 0 / 100 at each recommendation boundary, 11 skill tags (must truncate to 8 skill tags and keep both the visa and variant tags), a batch of exactly 10 and of 11, a budget of 0, and a `matchText` body under 20 characters (must be padded by the real body, never shipped short), a posting of exactly 149 and exactly 150 words (provisional vs full), and a title-only row (must raise `TitleOnlyError`, never promote)
5. Run tests, confirm all pass
6. Commit: "feat(promote): jobsync payload mapping with tag cap and request budget"

**Completeness ladder:**
- Happy path: a scored row becomes a valid `add_job` payload plus a valid `save_match_result` payload.
- Error paths: a row with no score (refuse to promote and say so), an unmappable `workplaceType`, a budget already spent, and a title-only row (refuse — spec §8; a match built from a title alone is worse than no match, because it looks like one).
- Edge cases: every recommendation boundary, tag overflow, batch of exactly 10 and of 11, empty input, a row whose description is exactly 9 and exactly 10 characters.
- Observability: `plan_budget` returns `(sending, waiting, requests_needed)` so the skill can print what will happen before it happens.

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t . -v` passes
- [ ] Every generated `matchText` begins with a `SCORES:` line matching `^SCORES: match=\d{1,3} recommendation=(strong|good|partial|weak)$`
- [ ] `tags` never exceeds 10 and always retains the visa tag and the variant tag
- [ ] Batches never exceed 10 items
- [ ] No placeholder/TODO comments in new code

### Phase E.5: `scripts/jobhunter.py`, the one command the skills call

**Estimated time:** 15 minutes

**Files:**
- Create: `scripts/jobhunter.py`
- Test: `tests/test_cli.py`

**Why this phase exists.** A SKILL.md is prose read by a model, and prose
naming a Python function is not a way to call it. Without this file the
skills say "read with `config.load(path)`" and nothing in the repository
says where `config.py` lives or how to reach it — the only code that knows
is the test suite's own `sys.path.insert`. The first person to install the
plugin would have to guess an absolute path inside their plugin cache. This
was the review's first Critical finding: **nothing was runnable.**

**Steps:**
1. Write failing test for `main(["config-show", "--config", <path>])` printing one JSON document on stdout. Expected error: `ModuleNotFoundError: No module named 'jobhunter'`
2. Run tests, confirm it fails for that reason
3. Implement `scripts/jobhunter.py` as ONE `argparse` entrypoint with nine subcommands: `config-show`, `ats-fetch`, `ats-normalize`, `queue-append`, `queue-list` (`--unscored`, `--unpromoted`), `queue-update`, `queue-key`, `keywords-report` (`--top`, `--markdown`), `promote-prepare`. Every skill invokes exactly `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" <subcommand>` — never a bare path, never a Python function name
4. Large payloads arrive as `--rows @path` / `--updates @path`, because a whole job description on a command line is mangled by the shell
5. `main()` catches **every** exception and emits `{"error": "<class>", "message": "..."}` as JSON on stderr, exit 1. A traceback is not a result a skill can report, and the contract stated in all six SKILL.md is JSON either way
6. `--company` is required for `lever` and `ashby` (their payloads carry no company name) and refused for `greenhouse` (its payload states its own, so the flag would be silently ignored). Validate this BEFORE the network call
7. `promote-prepare` validates each row FIRST and budgets over the survivors. Budgeting over the raw rows counts refusals against the request ceiling — measured on 25 bad rows ahead of 50 good ones with `--limit 30`: the old order prepared **0** and held 60 rows back, the new order prepares 15
8. Run tests, confirm all pass
9. Commit: "feat(cli): single entrypoint every skill invokes"

**Completeness ladder:**
- Happy path: each subcommand prints one JSON document on stdout, nothing else. Logging goes to stderr — `ats.fetch`'s log line on stdout made `json.load` fail on a real fetch.
- Error paths: malformed JSON in `--rows`, a missing `@file`, a bad `--jd` path, a missing or surplus `--company`, a non-positive `--top`. Each is a named JSON refusal, never a traceback.
- Edge cases: empty queue, every row refused, a board whose postings all fail to normalise, `--limit` above the jobsync hourly ceiling.
- Tests: `tests/test_cli.py` calls `main(argv)` in-process and reads stdout, because the contract the skills depend on is the bytes on stdout, not a return value.
- Observability: `ats-*` report `skipped` postings alongside `rows`, so a board that came back short says so.

**Verification:**
- [ ] `python3 -m compileall -q scripts` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] Every subcommand documented in a SKILL.md exists, and every flag documented with it exists on that subcommand (`tests/test_manifest.py`)
- [ ] stdout holds one parseable JSON document for every subcommand except `keywords-report --markdown`
- [ ] No placeholder/TODO comments in new code

### Phase F: the six skills and the plugin manifest

**Estimated time:** 15 minutes

**Files:**
- Create: `skills/profile/SKILL.md`, `skills/discover/SKILL.md`, `skills/score/SKILL.md`, `skills/promote/SKILL.md`, `skills/tailor/SKILL.md`, `skills/outreach/SKILL.md`
- Create: `.claude-plugin/plugin.json`
- Create: `README.md`
- Create: `tests/test_manifest.py`
- Depends on: `scripts/jobhunter.py` from Phase E.5 — every command a SKILL.md writes must be one that file accepts

**Steps:**
1. Write failing test asserting `.claude-plugin/plugin.json` parses and that every directory under `skills/` has a `SKILL.md` whose front matter declares a `name` and `description`. Expected error: `FileNotFoundError: .claude-plugin/plugin.json`
2. Run tests, confirm it fails for that reason
3. Write `.claude-plugin/plugin.json` with `name: "ai-jobhunter"`, version `0.1.0`, MIT licence, author Ali Sadikin
4. Write the six SKILL.md files. Each states its inputs, the exact **commands** it runs — always `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" <subcommand>`, never a Python function name — the MCP tools it may use, and what it refuses to do. `outreach` must check for a Gmail MCP tool at run time and fall back to writing `.eml` files, saying in its output which path it took. `promote` is the only skill permitted to call jobsync MCP tools
4b. `profile`'s SKILL.md specifies the four compilation passes from spec §4.2 verbatim: **ingest** each source to `.jobhunter/profile/sources/<name>.md` with its URL/path and fetch date and never edit it; **extract** each atomic claim with its source file and line, carrying `verified: false` for any claim the source itself flags unverified (markers in use: `[verifikasi]`, `[Assumption]`); **reconcile** by the configured tier precedence, writing anything precedence cannot settle to `.jobhunter/profile/conflicts.md`; **render** `master-cv.md` with a source named on every bullet. It states two hard rules: a `verified: false` claim is never rendered into any outward document, and only allow-listed project directories are ever opened
5. Read `/Users/alisadikin/Drive-D/claude-plugin/jobhunter-plugin/refs/` for prior art on CV, email and contact wording before writing `tailor` and `outreach`
6. Run tests, confirm all pass
7. Commit: "feat(skills): six pipeline skills and plugin manifest"

**Completeness ladder:**
- Happy path: the plugin loads and all six commands resolve.
- Error paths: a skill whose front matter lacks `name` or `description` fails the manifest test; a missing `.jobhunter/config.toml` makes every skill but `profile` stop with the same named error.
- Edge cases: a skill directory with no `SKILL.md`, a `plugin.json` with a trailing comma, a skill name that does not match its directory.
- Observability: every skill prints what it read, what it wrote and what it spent (Firecrawl credits, MCP requests) before it finishes.
- Not applicable: no automated behavioural test of the prose itself — that is what Phase G's evals are for.

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t . -v` passes
- [ ] No SKILL.md bundles any candidate-specific value — grep for `alisadikin`, `INDUSIA` and `Obsidian` across `skills/` returns nothing
- [ ] `tailor`'s SKILL.md states that reading the target job description is mandatory and that `master-cv.md` is never sent as-is
- [ ] `outreach`'s SKILL.md contains no send path, only draft creation
- [ ] `profile`'s SKILL.md states the `verified: false` suppression rule and the project allow-list rule
- [ ] No placeholder/TODO comments in new code

### Phase G: evals for the judgement steps

**Estimated time:** 12 minutes

**Files:**
- Create: `docs/evals/scoring.md`
- Create: `docs/evals/tailoring.md`
- Create: `docs/evals/profile.md`
- Create: `docs/evals/fixtures/` (at least 6 real job descriptions, saved verbatim)

**Steps:**
1. Write failing test asserting all three eval files exist and each names at least 5 cases with expected outcomes. Expected error: `FileNotFoundError: docs/evals/scoring.md`
2. Run tests, confirm it fails for that reason
3. Collect at least 6 real job descriptions into `docs/evals/fixtures/`: one that explicitly sponsors, one stating "no sponsorship", one US-remote silent on authorization, one requiring a PhD and model-training research, one clear `ai_product_lead` posting and one clear `vibe_coding` posting
4. Write `docs/evals/scoring.md` with capability cases (correct `work_authorization` bucket, correct variant) and regression cases (the model-research posting must score **low** on role fit; the "no sponsorship" posting must come back `closed`; a posting with no salary must leave the salary dimension empty rather than scoring it 0)
5. Write `docs/evals/tailoring.md`: every run must produce a CV differing from `master-cv.md`, must quote at least three JD-specific terms, and must not invent an employer, a date or a metric absent from the profile
5b. Write `docs/evals/profile.md` with fixtures built from two sources that disagree. Cases: a metric stated differently in two tiers resolves to the higher-precedence tier; two same-tier sources that disagree land in `conflicts.md` rather than being picked; a claim marked `[verifikasi]` never appears in the rendered CV; two true statements about different subjects that share a number (for example "products used across 16 countries" and "a cohort drawn from 16 countries") are **not** fused into one claim; every rendered bullet names a source
6. Run tests, confirm all pass
7. Commit: "test(evals): scoring and tailoring eval suites with real fixtures"

**Completeness ladder:**
- Happy path: each eval names its cases, fixtures and pass criteria.
- Error paths: a fixture that is unreadable or empty fails the eval rather than being skipped silently.
- Edge cases: a posting with no salary, no location, no description, and one that is a duplicate of another fixture.
- Observability: each eval records pass@k so a regression is visible as a number, not an impression.
- Not applicable: deterministic unit assertions on model output — that is precisely why these are evals.

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t . -v` passes
- [ ] All three eval files name ≥5 cases each with explicit pass criteria
- [ ] The "no sponsorship" fixture is a named regression case expecting `closed`
- [ ] The model-research fixture is a named regression case expecting a **low** role-fit score
- [ ] `docs/evals/profile.md` has a named case proving a `[verifikasi]` claim is suppressed
- [ ] No placeholder/TODO comments in new code

## Out of scope

- Auto-apply of any kind, and any browser automation that submits a form.
- `review_resume` / `save_resume_review` — their schema demands an `ats=<0-100>` number this plugin will not claim.
- Any `status` skill: jobsync already ships a Kanban UI.
- Publishing to a marketplace, and any CI configuration.
- Migrating existing data out of `jobhunter-plugin` or its FastAPI backend.

## Open items

1. **jobsync MCP token.** The server runs and its schema is read, but no token exists yet.
   Phase F's `promote` skill can be written and unit-tested without one; a live end-to-end
   promote requires the user to create an account at `http://localhost:3737` and generate a
   token under Settings → MCP Access. Do not fabricate a token or mock the server as if it
   had succeeded.
2. **Gmail MCP availability is unverified.** Phase F must implement the `.eml` fallback and
   report which path it used, rather than assuming Gmail is reachable.
3. **LinkedIn PDF export** is a manual user action and cannot be automated. `profile` must
   fail with a clear instruction when the configured path does not exist.

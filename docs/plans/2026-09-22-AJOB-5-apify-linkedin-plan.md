> **For Claude:** REQUIRED SKILL: Use gaspol-execute to implement this plan.
> **CRITICAL:** This plan specifies real integrations. During execution,
> NEVER substitute placeholders for real data sources without explicit
> user approval. If a data source doesn't exist yet, STOP and ask.
> **Progress ledger — HARD PER-PHASE GATE:** `.gaspol/progress/PROGRESS-AJOB-5.md` (created by `gaspol-plan` at plan-write time). After EACH phase and **BEFORE** starting the next, STOP and do BOTH: (a) tick that phase's `## Checklist` line, (b) append a `## Log` line ending with the handoff cursor. This is **blocking**, like a test gate: no next phase until both are written. **Never batch all updates at the end** — a crash mid-run must leave a truthful state, not a stale one. Update ONLY this file — never the shared `.gaspol/progress.md`.
> **Self-contained:** this plan is the COMPLETE spec. It must be executable by an agent with **no other context**. Every file path, contract, config key, and convention it needs is written here **verbatim**.

**Ticket:** AJOB-5
**Ledger:** .gaspol/progress/PROGRESS-AJOB-5.md
**Spec:** docs/plans/2026-09-22-AJOB-5-apify-linkedin-spec.md

## Goal

Move `discover`'s network sources off MCP and onto stdlib REST calls with keys the user keeps in
`.env`: LinkedIn postings through the Apify actor `bebity/linkedin-jobs-scraper` (`APIFY_TOKEN`),
board search/scrape through Firecrawl REST v2 (`FIRECRAWL_API_KEY`). Budgets are enforced in code
before each call; payloads go to disk; LinkedIn re-fetches are cut by an automatic posted-date
window and a canonical job URL. The Firecrawl monitor is removed from `discover` (no config key
ever fed it; it spends credits outside any run budget).

## Architecture Context (from CLAUDE.md — read it first, it is short)

- Python 3 **standard library only** — no pip, no pytest, no PyYAML. Tests are `unittest`; config
  is TOML via `tomllib`.
- **The one entrypoint.** Skills run only
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" <subcommand> [options]`. Every subcommand
  prints one JSON document on stdout; logging goes to stderr; a refusal is
  `{"error": "<class>", "message": "..."}` on stderr, exit 1, never a traceback
  (`scripts/jobhunter.py::main` already does this for any exception).
- Existing modules reused:
  - `scripts/ats.py` — `_clean_description(raw)`, `_Rows(list)` (carries `.skipped`),
    `_normalize_all(source, jobs, normalizer)` (skip one bad posting, raise the first
    `MissingFieldError` if all fail), `MissingFieldError(provider, key)`. Pattern for a
    fetch-to-disk function: `ats.fetch` (streams in 65536-byte chunks, logs one stderr line).
  - `scripts/jobq.py` — `append_rows(path, rows) -> (written, skipped_duplicates, malformed)`,
    `row_key(row)` = sha256 of normalised `jobUrl`, else of `company|jobTitle|location`.
  - `scripts/config.py` — `load(path)`; `_KNOWN_TOP_LEVEL_KEYS`; `_BUDGET_DEFAULTS`
    (`firecrawl_credits_per_run: 150`, `jobsync_requests_per_run: 50`);
    `_require_budget_int(name, value)` raises `BudgetTypeError` for bool/non-int/negative;
    `_warn_unknown_section_keys(section, raw, known)`; returns a dict with `_provenance`.
  - `scripts/promote.py` — `_WORKPLACE_TYPES = {"remote": "Remote", "hybrid": "Hybrid",
    "onsite": "Onsite"}`, `_WORKPLACE_FOLD_RE = re.compile(r"[\s\-_]+")`.
- Queue rows use **camelCase**: `company`, `jobTitle`, `jobDescription`, `location`, `source`,
  `jobType`, `workplaceType`, `jobUrl`. Only fields that could be established are set.
- Hard rules that apply: never auto-applies; nothing candidate-specific under `skills/`
  (enforced by `tests/test_manifest.py`); error class names are quoted verbatim in SKILL.md prose.
- Debugging checklist: when you add a guard, **mutate the thing it guards and watch it fail**.
- `tests/test_manifest.py` parses every skill's documented commands (backslash continuations
  included) and checks each subcommand and flag exists in `jobhunter.py --help`.
  `TestConfigTemplateMatchesTheSpec` requires `templates/config.toml` to equal (after `.strip()`)
  a ```` ```toml ```` block containing `profile_sources` in **exactly one** `docs/plans/*-spec.md`
  and **exactly one** `docs/plans/*-plan.md` — today those are
  `docs/plans/2026-09-19-AJOB-1-ai-jobhunter-pipeline-spec.md` and
  `docs/plans/2026-09-19-AJOB-1-ai-jobhunter-pipeline-plan.md`. **This plan must never contain a
  TOML block with `profile_sources` in it.**

## Tech Stack

stdlib: `urllib.request`, `urllib.error`, `urllib.parse`, `json`, `math`, `os`, `re`, `time`,
`datetime`, `tomllib`, `unittest`, `unittest.mock`.

Verification commands (from CLAUDE.md; `detect-stack` printed no markers for this repo):

- static: `python3 -m compileall -q scripts tests`
- unit: `python3 -m unittest discover -s tests -t .` (baseline: 744 tests, OK)

## Verified external facts (fetched 2026-09-22 — copy, do not re-derive)

**Apify** (docs.apify.com, actor build `0.0.222` via `GET https://api.apify.com/v2/acts/bebity~linkedin-jobs-scraper`):

- Auth header `Authorization: Bearer <token>`; never `?token=`.
- Start: `POST https://api.apify.com/v2/acts/bebity~linkedin-jobs-scraper/runs?maxItems=<n>&maxTotalChargeUsd=<usd>`,
  body = actor input JSON → 201, `{"data": {"id", "status", "defaultDatasetId", ...}}`.
- Poll: `GET https://api.apify.com/v2/actor-runs/{runId}?waitForFinish=60` → `data.status` ∈
  `READY, RUNNING, SUCCEEDED, FAILED, TIMING-OUT, TIMED-OUT, ABORTING, ABORTED`;
  `data.usageTotalUsd` (number), `data.defaultDatasetId`.
- Abort: `POST https://api.apify.com/v2/actor-runs/{runId}/abort`.
- Items: `GET https://api.apify.com/v2/datasets/{datasetId}/items?format=json&clean=true&limit=<n>` → JSON array.
- Limits: `GET https://api.apify.com/v2/users/me/limits` →
  `data.limits.maxMonthlyUsageUsd`, `data.current.monthlyUsageUsd`.
- Error body `{"error": {"type": "...", "message": "..."}}`. 401 bad token; 402/403 credit or
  permission; 404 not found; 429 rate limit.
- Actor input fields: `titles` (array), `locations` (array), `rows` (int 0-1000, **per
  title×location search**, default 0 = all), `publishedAt` (enum `""`, `"r2592000"` month,
  `"r604800"` week, `"r86400"` 24 h), `workTypes` (array of `"1"` On-site, `"2"` Remote,
  `"3"` Hybrid), `companyProfile` (bool, default **true**), `enrichCompany` (bool, default false,
  premium). **No exclude-ids field.**
- Pricing: PAY_PER_EVENT; `apify-default-dataset-item` FREE tier **$0.0015**/job;
  `apify-actor-start` $0.00005/GB; `premium-company` (enrichCompany) FREE $0.001/job.
- Output fields documented: `title`, `description`, `descriptionHtml`, `location`, `companyName`,
  `jobUrl`, `id`, `workType` (on-site/remote/hybrid), `contractType`, `experienceLevel`,
  `salary`, `postedTime`, `publishedAt`, `posterFullName`, `posterProfileUrl`, `posterHeadline`,
  `posterPhoto`. Whether `workType` is present **without** `enrichCompany` is unverified — Phase C
  settles it.

**Firecrawl** (docs.firecrawl.dev, API v2):

- Base `https://api.firecrawl.dev`, header `Authorization: Bearer fc-...`.
- `POST /v2/search` body `{query (≤500 chars), limit (≤100), tbs?, location?, scrapeOptions?}`
  → `{"success", "data": {"web": [{"url", "title", "description", "markdown"?, "metadata"}]},
  "creditsUsed"}`. Search cost: 2 credits per 10 results; `scrapeOptions` adds the scrape cost per
  result.
- `POST /v2/scrape` body `{url, formats: ["markdown"], onlyMainContent, proxy: "basic"|"enhanced"|"auto",
  timeout (ms, 1000-300000)}` → `{"success", "data": {"markdown", "metadata": {"statusCode",
  "sourceURL", ...}}}`. Whether it returns `creditsUsed` is unverified — treat as optional.
- `GET /v2/team/credit-usage` → `{"success", "data": {"remainingCredits", "planCredits",
  "billingPeriodStart", "billingPeriodEnd"}}`.
- Errors `{"success": false, "error": "...", "details"?}`: 401 invalid key; 402 insufficient
  credits; 408 timeout (retryable); 429 rate limit with `Retry-After` (retryable); 5xx retryable.

## Data Integration Map

| Feature | Data Source | Hook/API | Exists? | Action |
|---------|-----------|----------|---------|--------|
| Key lookup | process env + `.env` | `envfile.read_key` | No | Create `scripts/envfile.py` |
| LinkedIn run | Apify `/v2/acts/bebity~linkedin-jobs-scraper/runs` | `apify.fetch_linkedin` | No | Create, real HTTP |
| LinkedIn status + cost | `/v2/actor-runs/{id}` | `apify.fetch_linkedin` | No | Create |
| LinkedIn postings | `/v2/datasets/{id}/items` | `apify.fetch_linkedin` | No | Create, stream to disk |
| Apify credit | `/v2/users/me/limits` | `apify.remaining_credit_usd` | No | Create |
| LinkedIn → rows | fixture from a real run | `apify.normalize_linkedin` | No | Create |
| Board search | Firecrawl `/v2/search` | `firecrawl.search` | No (was MCP) | Create |
| Posting page | Firecrawl `/v2/scrape` | `firecrawl.scrape` | No (was MCP) | Create |
| Firecrawl credit | `/v2/team/credit-usage` | `firecrawl.remaining_credits` | No | Create |
| Queue write | `.jobhunter/queue/jobs.jsonl` | `jobq.append_rows` | Yes | Use existing |
| Description clean | — | `ats._clean_description` | Yes | Use existing |
| Skip-and-report | — | `ats._Rows`, `ats._normalize_all`, `ats.MissingFieldError` | Yes | Use existing |
| Budget ints | config | `config._require_budget_int` | Yes | Use existing |
| Search terms | `[linkedin]` in config | `config.load` | No | Extend |
| LinkedIn window state | `<queue dir>/linkedin-state.json` | `apify.choose_window` / `apify.write_state` | No | Create |
| Firecrawl run state | `--run-state` file | `firecrawl.Budget` | No | Create |

## Out of scope

Firecrawl monitors (removed, not replaced); Remotive/Jobicy sources; IDF pre-rank in `score`;
multi-token rotation (Apify General Terms forbid multiple Personal Accounts).

---

### Phase A: `.env` key reader

**Estimated time:** 10 minutes

**Files:**
- Create: `scripts/envfile.py`
- Create: `tests/test_envfile.py`
- Modify: `.gitignore` (add `.env` under a `# secrets` comment)

**Contract:** `read_key(name, env_file=".env") -> str | None`.
1. `os.environ.get(name)` non-empty after `.strip()` → return it.
2. Else, if `env_file` exists: read UTF-8, per line: strip; skip empty and lines starting `#`;
   drop a leading `export ` ; split on the first `=`; key = left `.strip()`; value = right
   `.strip()`; if value is wrapped in one matching pair of `'` or `"`, remove them. First line
   whose key == `name` with a non-empty value → return value.
3. Else `None`. A missing file is not an error. An unreadable file (`OSError` other than
   not-found) raises `EnvFileError(f"cannot read {env_file}: {exc.strerror}")` — the message
   never contains file content.

Also `key_status(names, env_file) -> dict` → `{name: "present"|"missing", "env_file": <abs path>|"not found"}`.

**Steps:**
1. Write failing test for `read_key` returning the env var over the file value. Expected error: `ModuleNotFoundError: No module named 'envfile'`
2. Run `python3 -m unittest tests.test_envfile`, confirm it fails for that reason.
3. Add tests (each its own method): file fallback; `export KEY=v`; `KEY="v"` and `KEY='v'`;
   `KEY=a=b` returns `a=b`; `# KEY=x` ignored; blank env var falls through to file; missing file
   → `None`; key absent → `None`; mismatched quotes kept verbatim; `key_status` never contains a
   value (assert the secret string is absent from `json.dumps(result)`).
4. Implement `scripts/envfile.py` (module docstring states why env wins and that values are never
   echoed). Use `mock.patch.dict(os.environ, ..., clear=False)` and `tempfile` in tests.
5. Add `.env` to `.gitignore`; confirm `git check-ignore -q .env` exits 0.
6. Mutation check: make `read_key` prefer the file over env; watch the env-wins test fail; revert.
7. Commit: `feat(envfile): read provider keys from env or .env`

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] Security: no key value in any return other than `read_key`; `.env` is git-ignored
- [ ] Mutation of env-precedence made a test fail
- [ ] No placeholder/TODO comments in new code

---

### Phase B: config `[linkedin]` + `apify_max_items_per_run`

**Estimated time:** 15 minutes

**Files:**
- Modify: `scripts/config.py`
- Modify: `templates/config.toml`
- Modify: `docs/plans/2026-09-19-AJOB-1-ai-jobhunter-pipeline-spec.md` (its config TOML block)
- Modify: `docs/plans/2026-09-19-AJOB-1-ai-jobhunter-pipeline-plan.md` (its config TOML block)
- Test: `tests/test_config.py`

**Contract:**
- `_KNOWN_TOP_LEVEL_KEYS` gains `"linkedin"`.
- `_BUDGET_DEFAULTS` gains `"apify_max_items_per_run": 100`.
- `_KNOWN_LINKEDIN_KEYS = frozenset({"keywords", "locations", "work_types"})`; unknown keys warn
  via `_warn_unknown_section_keys("linkedin", ...)`.
- `cfg["linkedin"] = {"keywords": list, "locations": list, "work_types": list}` (empty lists when
  the section is absent — `load` does not require it; `linkedin-fetch` does, Phase F).
- Each of the three must be a list of non-empty strings, else `ConfigError(f"linkedin.{key} must
  be a list of non-empty strings, got {value!r}")`.
- `work_types` values must be in `("on-site", "remote", "hybrid")`, else
  `ConfigError(f"linkedin.work_types: {value!r} is not one of on-site, remote, hybrid")`.
- Provenance: `linkedin.keywords` / `linkedin.locations` / `linkedin.work_types` → `"file"` or
  `"default"`.

Text to add to `templates/config.toml` — after the `[targets]` table, before `[budgets]`:

```text
[linkedin]
# Fetched through the Apify actor bebity/linkedin-jobs-scraper. The token is
# APIFY_TOKEN in .env, never here. Every keyword is searched in every location.
keywords   = ["AI engineer"]
locations  = ["United States"]
work_types = ["remote"]                 # on-site | remote | hybrid; checked again on output
```

and inside `[budgets]`, after `jobsync_requests_per_run`:

```text
apify_max_items_per_run = 100           # LinkedIn postings per run; 0 turns LinkedIn off
```

Apply the identical edit to the ```` ```toml ```` block that contains `profile_sources` in each of
the two AJOB-1 documents, so all three copies stay byte-identical after `.strip()`.

**Steps:**
1. Write failing test for `load` returning `budgets["apify_max_items_per_run"] == 100` by default. Expected error: `KeyError: 'apify_max_items_per_run'`
2. Run it, confirm the failure.
3. Add tests: file value 25 kept with provenance `file`; `"25"` → `BudgetTypeError`; `-1` →
   `BudgetTypeError`; `[linkedin]` parsed; absent section → empty lists; `keywords = "x"` →
   `ConfigError`; `keywords = [""]` → `ConfigError`; `work_types = ["remote-ish"]` →
   `ConfigError`; unknown `[linkedin] keyword = [...]` → `UserWarning`; `[linkedin]` no longer
   triggers the unknown-top-level warning.
4. Implement in `scripts/config.py`.
5. Update `templates/config.toml` and both AJOB-1 docs; run
   `python3 -m unittest tests.test_manifest` — `TestConfigTemplateMatchesTheSpec` must pass.
6. Mutation check: drop `"linkedin"` from `_KNOWN_TOP_LEVEL_KEYS`, watch the warning test fail;
   revert. Edit one AJOB-1 copy only, watch the drift guard fail; revert.
7. Commit: `feat(config): [linkedin] section and apify_max_items_per_run budget`

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] `templates/config.toml` equals the AJOB-1 spec and plan blocks (drift guard green)
- [ ] Both mutations made a test fail
- [ ] No placeholder/TODO comments in new code

---

### Phase C: capture real fixtures (needs the user's keys)

**Estimated time:** 10 minutes + user action

**Files:**
- Create: `tests/fixtures/apify_linkedin.json`
- Create: `tests/fixtures/firecrawl_search.json`

**Precondition — STOP and ask the user if unmet:** a `.env` in the worktree root holding
`APIFY_TOKEN=...` and `FIRECRAWL_API_KEY=...` (Phase A git-ignored it). Never print either value;
read them with `python3 -c 'import sys; sys.path.insert(0,"scripts"); import envfile; ...'`
inside the capture script, never `cat .env`.

**Steps:**
1. Write failing test for the fixture's shape in `tests/test_apify.py`: the file loads as a JSON
   list of ≥ 1 objects each having `title`, `companyName`, `description`, `jobUrl`. Expected error: `FileNotFoundError: ... tests/fixtures/apify_linkedin.json`
2. Run it, confirm the failure.
3. Write a throwaway capture script in the session scratchpad (not the repo) that uses stdlib
   `urllib` with the Bearer header to: start a run of `bebity~linkedin-jobs-scraper` with
   `?maxItems=5&maxTotalChargeUsd=0.05` and input `{"titles": ["software engineer"],
   "locations": ["United States"], "rows": 5, "publishedAt": "r604800", "companyProfile": false,
   "enrichCompany": false}`; poll with `waitForFinish=60`; download items with `limit=5`.
   Report the run's `usageTotalUsd` to the user.
4. **Gate on `workType`:** inspect the items. If no item has a non-empty `workType` (or an
   equivalent on-site/remote/hybrid field — record the exact field name found), STOP and ask the
   user via AskUserQuestion: `[enrichCompany on — +$0.001/job]` / `[ship without workplaceType]`.
   Record the answer under `## Keputusan saat jalan` in the ledger. If they choose enrich, re-run
   the capture with `"enrichCompany": true`.
5. Scrub before saving: delete keys `posterFullName`, `posterProfileUrl`, `posterHeadline`,
   `posterPhoto`, and any other key whose value is a person's name or a `linkedin.com/in/` URL.
   Keep everything else verbatim. Save to `tests/fixtures/apify_linkedin.json` (indent 2).
6. Firecrawl: `POST /v2/search` with `{"query": "software engineer jobs greenhouse", "limit": 2,
   "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": true, "proxy": "basic"}}`; save
   the full response to `tests/fixtures/firecrawl_search.json`. Record `creditsUsed`. Also call
   `GET /v2/team/credit-usage` once and record the response **keys only** in the ledger.
7. Run the shape test, confirm it passes; add the same kind of shape test for
   `firecrawl_search.json` (`success` true, `data.web` list, each with `url`, `markdown`).
8. `git grep -n -i "linkedin.com/in/" tests/fixtures/` must print nothing.
9. Commit: `test(fixtures): real bebity and Firecrawl search payloads for AJOB-5`

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] Both fixtures came from real calls; spend recorded in the ledger
- [ ] `workType` gate decided and recorded
- [ ] Security: no key in any committed file (`git grep -n "fc-" tests/` shows only doc text, if any); no personal profile data in fixtures
- [ ] No placeholder/TODO comments in new code

---

### Phase D: `normalize_linkedin`

**Estimated time:** 15 minutes

**Files:**
- Create: `scripts/apify.py` (normaliser part + error classes)
- Test: `tests/test_apify.py`

**Contract:**
- Classes: `ApifyError(Exception)`, `ApifyTokenMissingError(ApifyError)`,
  `ApifyCreditError(ApifyError)`. `SOURCE_LINKEDIN = "LinkedIn"`.
- `_canonical_job_url(raw)`: find the numeric id with `re.search(r"(?:/jobs/view/(?:[^/?#]*-)?|currentJobId=)(\d{6,})", raw)`;
  return `f"https://www.linkedin.com/jobs/view/{id}/"`; no match → `None`. If the posting has an
  `id` field that is all digits, prefer it.
- `_normalize_linkedin_job(job)`: required `companyName`→`company`, `title`→`jobTitle`,
  `description`→`jobDescription` (via `ats._clean_description`), `jobUrl`→ canonical `jobUrl`.
  Missing/empty required, or no canonical id → `ats.MissingFieldError("LinkedIn", "<key>")`.
  Optional: `location`; `contractType`→`jobType`; work type (field name as found in Phase C) →
  `workplaceType` = `promote`'s canonical value when `_WORKPLACE_FOLD_RE.sub("", v.strip().lower())`
  is in `_WORKPLACE_TYPES` (`"onsite"` → `"Onsite"`), else absent. `source = "LinkedIn"`.
- `normalize_linkedin(path)`: load JSON; non-list → `ApifyError("LinkedIn dataset is not a JSON
  array")`; `rows, skipped = ats._normalize_all("LinkedIn", jobs, _normalize_linkedin_job)`;
  return `ats._Rows(rows, skipped)`.

**Steps:**
1. Write failing test for `normalize_linkedin` on the real fixture returning rows with `source ==
   "LinkedIn"` and canonical `jobUrl`. Expected error: `ModuleNotFoundError: No module named 'apify'`
2. Run it, confirm the failure.
3. Add tests: canonical URL from `https://www.linkedin.com/jobs/view/senior-ai-engineer-at-acme-4012345678?refId=x&trk=y`,
   from `.../jobs/view/4012345678/`, from `...?currentJobId=4012345678`, from `id` field; no id →
   skipped with key `jobUrl`; missing `title` → skipped naming `title`; every posting bad →
   `MissingFieldError`; `"Remote"`, `"on-site"`, `"On Site"`, `"HYBRID"` fold; `"Contract"` as
   work type → no `workplaceType`; two postings same id different tracking → same `jobq.row_key`;
   non-list JSON → `ApifyError`.
4. Implement.
5. Mutation check: return the raw `jobUrl` instead of the canonical one; watch the row_key test
   fail; revert.
6. Commit: `feat(apify): normalise bebity LinkedIn postings to queue rows`

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] Rows built from the real fixture, not hand-written data
- [ ] Mutation made a test fail
- [ ] No placeholder/TODO comments in new code

---

### Phase E: Apify fetch, credit brake, window state

**Estimated time:** 15 minutes

**Files:**
- Modify: `scripts/apify.py`
- Test: `tests/test_apify.py`

**Contract:**
- Constants (each with a source+date comment): `_ACTOR = "bebity~linkedin-jobs-scraper"`,
  `_API = "https://api.apify.com/v2"`, `_PRICE_PER_JOB_USD = 0.0015`, `_CAP_HEADROOM = 1.5`,
  `_POLL_WAIT_SECONDS = 60`, `_CEILING_SECONDS = 900`, `_WORK_TYPE_CODES = {"on-site": "1",
  "remote": "2", "hybrid": "3"}`, `_WINDOWS = (("r86400", 24h), ("r604800", 7d))`,
  fallback `"r2592000"`.
- `_request(method, url, token, body=None, timeout=90)` → parsed JSON; sets
  `Authorization: Bearer`, `Content-Type: application/json`, `User-Agent: gaspol-jobhunter/0.3`.
  `HTTPError`: parse `error.message` if JSON; 402 → `ApifyCreditError`; else `ApifyError(f"Apify
  {method} {path} failed: HTTP {code} {message}")` where `path` excludes the query string. Token
  never in the URL or message. `URLError`/`TimeoutError` → `ApifyError`.
- `charge_cap_usd(max_items)` → `round(max_items * _PRICE_PER_JOB_USD * _CAP_HEADROOM, 4)`.
- `build_actor_input(linkedin_cfg, max_items, window)` → dict per the spec table; `rows =
  math.ceil(max_items / (len(keywords) * len(locations)))`; `companyProfile: False`,
  `enrichCompany`: per Phase C decision; `workTypes` omitted when `work_types` is empty.
- `remaining_credit_usd(token)` → `limits.maxMonthlyUsageUsd - current.monthlyUsageUsd`.
- `fetch_linkedin(actor_input, max_items, token, dest, *, clock=time.monotonic, sleep=time.sleep)`:
  start run → poll until terminal (each poll is itself a 60 s long-poll; `clock` checked each
  loop; past `_CEILING_SECONDS` → abort call, then `ApifyError("... aborted after 900 s")`) →
  status ≠ `SUCCEEDED` → `ApifyError(f"LinkedIn run {run_id} ended {status}")` → stream items to
  `dest` → return `{"run_id", "status", "returned", "usd_charged"}`. Logs one stderr line:
  `apify.fetch: run=<id> status=<s> returned=<n> usd=<x>`.
- `choose_window(state_path, now)` → publishedAt value; unreadable/invalid state → `"r2592000"`
  plus a stderr warning.
- `write_state(state_path, now)` → `{"last_success_at": now.isoformat()}` written atomically
  (temp file + `os.replace`).

**Steps:**
1. Write failing test for `fetch_linkedin` success path with a fake `urlopen` (a sequence of
   canned responses: start 201 → poll RUNNING → poll SUCCEEDED with `usageTotalUsd` 0.0075 →
   items). Expected error: `AttributeError: module 'apify' has no attribute 'fetch_linkedin'`
2. Run it, confirm the failure.
3. Add tests: Bearer header present on every request; no request URL contains the token; start URL
   has `maxItems=100&maxTotalChargeUsd=0.225` for 100 items; `rows` = 50 for 2 keywords × 1
   location × 100, 34 for 3 × 1 × 100; 401 → `ApifyError` with "HTTP 401"; 402 →
   `ApifyCreditError`; 404; 429; terminal `FAILED`, `ABORTED`, `TIMED-OUT` → `ApifyError`
   naming the status; ceiling → abort POST sent then `ApifyError`; empty dataset → returned 0,
   no error; non-JSON body → `ApifyError`; token absent from every raised message and from
   captured stderr. `remaining_credit_usd` arithmetic. `choose_window`: no file, 3 h, 30 h,
   8 days, garbage file. `write_state` round-trip.
4. Implement.
5. Mutation check: remove the ceiling check; watch the ceiling test hang-guard (use a fake clock)
   fail; revert. Put the token in the query string; watch the no-token-in-URL test fail; revert.
6. Commit: `feat(apify): run bebity with charge cap, poll, stream dataset`

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] Security: token only in the Authorization header; never in URL, log, or error text
- [ ] Both mutations made a test fail
- [ ] No placeholder/TODO comments in new code

---

### Phase F: `linkedin-fetch` subcommand

**Estimated time:** 15 minutes

**Files:**
- Modify: `scripts/jobhunter.py` (import `apify`, `envfile`; add `cmd_linkedin_fetch`, parser)
- Test: `tests/test_cli.py`

**Contract:** flags `--config` (required), `--queue` (required), `--dest` (required),
`--env-file` (default `.env`). Order:
1. `cfg = config.load(args.config)`; `max_items = cfg["budgets"]["apify_max_items_per_run"]`.
   `max_items == 0` → emit `{"skipped_source": "linkedin", "reason": "apify_max_items_per_run is 0"}`, exit 0.
2. `keywords`/`locations` empty → `config.ConfigError("linkedin-fetch needs [linkedin] keywords and locations in <config>")`.
3. `token = envfile.read_key("APIFY_TOKEN", args.env_file)`; `None` →
   `ApifyTokenMissingError("APIFY_TOKEN is not set in the environment or in <env-file>")`.
4. `cap = apify.charge_cap_usd(max_items)`; `remaining = apify.remaining_credit_usd(token)`;
   `remaining < cap` → `ApifyCreditError(f"remaining Apify credit ${remaining:.2f} is below this run's cap ${cap:.2f}")` — nothing started.
5. `state = os.path.join(os.path.dirname(os.path.abspath(args.queue)), "linkedin-state.json")`;
   `window = apify.choose_window(state, datetime.now(timezone.utc))`.
6. fetch → `rows = apify.normalize_linkedin(args.dest)` → `written, dup, malformed = jobq.append_rows(args.queue, list(rows))` → `apify.write_state(state, now)`.
7. Emit `{"window", "requested": max_items, "returned", "new": written, "duplicate": dup,
   "skipped": rows.skipped, "usd_charged", "credit_remaining_usd": remaining - usd_charged}`.

**Steps:**
1. Write failing test for `linkedin-fetch` emitting the report with `apify.fetch_linkedin` and
   `apify.remaining_credit_usd` patched and the real fixture copied to `--dest`. Expected error: argparse `invalid choice: 'linkedin-fetch'` in the JSON usage error on stderr.
2. Run it, confirm the failure.
3. Add tests: budget 0 → skip report, no network call; missing `[linkedin]` → `ConfigError`;
   no token (env cleared, no file) → `ApifyTokenMissingError` JSON, exit 1; credit below cap →
   `ApifyCreditError` and `fetch_linkedin` never called; second run with the same fixture →
   `new` 0, `duplicate` = first run's `new`; failed fetch → state file unchanged; `--help` lists
   all four flags.
4. Implement.
5. Mutation check: write state before the fetch; watch the failed-fetch test fail; revert.
6. Commit: `feat(cli): linkedin-fetch subcommand`

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] Security: key read only via `envfile`; never emitted
- [ ] Mutation made a test fail
- [ ] No placeholder/TODO comments in new code

---

### Phase G: Firecrawl REST client and run budget

**Estimated time:** 15 minutes

**Files:**
- Create: `scripts/firecrawl.py`
- Create: `tests/test_firecrawl.py`

**Contract:**
- Classes: `FirecrawlError(Exception)`, `FirecrawlKeyMissingError`, `FirecrawlCreditError`,
  `FirecrawlBudgetError` (all subclass `FirecrawlError`).
- `_API = "https://api.firecrawl.dev/v2"`; `_RETRIES = 3`; backoff 2, 4, 8 s, or `Retry-After`
  seconds on 429 (capped at 60); `sleep` injectable.
- `_request(method, path, key, body=None)`: Bearer header; 401 → `FirecrawlError("Firecrawl
  rejected the key (HTTP 401)")`; 402 → `FirecrawlCreditError` (not retried); 408/429/5xx →
  retried, then `FirecrawlError` with status and the body's `error` text; `success: false` on 200
  → `FirecrawlError`.
- `search(key, query, limit, dest, *, tbs=None, location=None)`: `limit` 1-100 else `ValueError`;
  body per the facts section with `scrapeOptions {"formats": ["markdown"], "onlyMainContent":
  true, "proxy": "basic"}`; writes `data.web` to `dest`; returns `(results_count, credits_used or None)`.
- `scrape(key, url, dest)`: body `{"url", "formats": ["markdown"], "onlyMainContent": true,
  "proxy": "basic", "timeout": 60000}`; writes `data` to `dest`; returns `credits_used or None`.
- `remaining_credits(key)` → `data.remainingCredits`.
- `estimate(kind, limit=None)`: search → `2 * math.ceil(limit / 10) + limit`; scrape → `1`.
- `class Budget(path, ceiling)`: JSON `{"start_remaining", "reported", "ceiling"}`.
  `Budget.open(path, ceiling, remaining_now)` creates on first use. `spent(remaining_now)` →
  `max(reported, start_remaining - remaining_now)`. `check(kind, limit, remaining_now)` raises
  `FirecrawlBudgetError(f"Firecrawl budget {ceiling} credits: {spent} spent, next call needs up to {estimate}")`
  when `spent + estimate > ceiling`. `record(credits_used)` adds to `reported` (None adds 0) and
  saves atomically.

**Steps:**
1. Write failing test for `search` writing `data.web` from the real fixture (served by a fake
   `urlopen`) to `dest`. Expected error: `ModuleNotFoundError: No module named 'firecrawl'`
2. Run it, confirm the failure.
3. Add tests: request body exact (incl. `proxy: "basic"`); Bearer header; key in no URL/message;
   401; 402 not retried (one call); 429 with `Retry-After: 3` sleeps 3 then succeeds; 5xx three
   times → `FirecrawlError`; `success: false` → error; limit 0 and 101 → `ValueError`; `estimate`
   for limits 1, 10, 11; `Budget`: fresh file, over-ceiling refuses before the call, `max(reported,
   delta)` both directions, corrupted file → `FirecrawlError` naming the path.
4. Implement.
5. Mutation check: make 402 retryable; watch the not-retried test fail; revert. Use `min` instead
   of `max` in `spent`; watch the delta test fail; revert.
6. Commit: `feat(firecrawl): REST v2 search/scrape with an enforced run budget`

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] Security: key only in the Authorization header
- [ ] Both mutations made a test fail
- [ ] No placeholder/TODO comments in new code

---

### Phase H: `firecrawl-search`, `firecrawl-scrape`, `keys-check` subcommands

**Estimated time:** 15 minutes

**Files:**
- Modify: `scripts/jobhunter.py`
- Test: `tests/test_cli.py`

**Contract:**
- `firecrawl-search --config --run-state --query --limit (int, default 10) --dest [--env-file .env] [--tbs] [--location]`
- `firecrawl-scrape --config --run-state --url --dest [--env-file .env]`
- Both: load config → `key = envfile.read_key("FIRECRAWL_API_KEY", env_file)` or
  `FirecrawlKeyMissingError("FIRECRAWL_API_KEY is not set in the environment or in <env-file>")`
  → `remaining = firecrawl.remaining_credits(key)` → `Budget.open(run_state,
  cfg["budgets"]["firecrawl_credits_per_run"], remaining)` → `check(...)` → call → `record(...)`.
  Emit `{"dest", "results" (search) | "url" (scrape), "credits_spent_run",
  "credits_budget", "credits_remaining_account"}`.
- `keys-check [--env-file .env]` → `envfile.key_status(["APIFY_TOKEN", "FIRECRAWL_API_KEY"], env_file)`.

**Steps:**
1. Write failing test for `keys-check` reporting `present`/`missing` without the value. Expected error: argparse `invalid choice: 'keys-check'`.
2. Run it, confirm the failure.
3. Add tests: search happy path with `firecrawl.search` / `remaining_credits` patched; budget
   exhausted → `FirecrawlBudgetError` JSON on stderr, `search` never called; missing key →
   `FirecrawlKeyMissingError`; scrape happy path; the run-state file accumulates across two
   calls; `--help` of each lists every flag.
4. Implement.
5. Mutation check: call before `check`; watch the budget-exhausted test fail; revert.
6. Commit: `feat(cli): firecrawl-search, firecrawl-scrape, keys-check`

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] Security: `keys-check` output contains no key value (asserted)
- [ ] Mutation made a test fail
- [ ] No placeholder/TODO comments in new code

---

### Phase I: `discover` SKILL.md, manifest guards, CLAUDE.md

**Estimated time:** 15 minutes

**Files:**
- Modify: `skills/discover/SKILL.md`
- Modify: `tests/test_manifest.py`
- Modify: `CLAUDE.md` (Stack test count, subcommand list, Layout table rows for `apify.py`,
  `firecrawl.py`, `envfile.py`, error-class list)
- Modify: `.claude-plugin/plugin.json` (version `0.4.0`)

**SKILL.md changes:**
- Remove every `mcp__firecrawl__*` reference and the monitor paragraph; description line drops
  "and watched career pages".
- New "Keys" section: keys live in `.env` at the project root as `APIFY_TOKEN=...` and
  `FIRECRAWL_API_KEY=...`; run `keys-check` first; warn if `git check-ignore -q .env` fails;
  a missing key skips that source and the report says so; no source falls back to another.
- New "LinkedIn" section with the `linkedin-fetch` command block, the window rule, the credit
  brake, what `requested` vs `returned` means, and the ToS note (public guest listings only; the
  user's LinkedIn account is never used; LinkedIn User Agreement §8.2 prohibits scraping and that
  risk is the user's).
- "Boards" section with `firecrawl-search` / `firecrawl-scrape` command blocks and a fresh
  `--run-state` path per run (e.g. `/tmp/fc-run-$(date +%s).json`).
- Error classes quoted verbatim: `apify.ApifyTokenMissingError`, `apify.ApifyCreditError`,
  `apify.ApifyError`, `firecrawl.FirecrawlKeyMissingError`, `firecrawl.FirecrawlCreditError`,
  `firecrawl.FirecrawlBudgetError`, `firecrawl.FirecrawlError`.
- Final-report lines for LinkedIn and Firecrawl as in the spec.

**Steps:**
1. Write failing test in `tests/test_manifest.py` asserting `linkedin-fetch` is collected with
   flags `{"--config", "--queue", "--dest", "--env-file"}`. Expected error: `AssertionError: 'linkedin-fetch' not found in ...`
2. Run it, confirm the failure.
3. Add tests: `firecrawl-search` flags collected; `firecrawl-scrape` flags collected; `keys-check`
   collected; `skills/discover/SKILL.md` contains no `mcp__firecrawl__`; every error class named
   in the SKILL.md exists as an attribute of its module.
4. Rewrite the SKILL.md sections; update CLAUDE.md (measure the new test count by running the
   suite — do not guess it); bump plugin version.
5. Mutation check: misspell one flag in SKILL.md; watch the flag guard fail; revert.
6. Commit: `docs(discover): REST sources with keys in .env; drop Firecrawl MCP and monitors`

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] CLAUDE.md test count equals the measured count
- [ ] Mutation made a test fail
- [ ] No placeholder/TODO comments in new code

---

### Phase J: live end-to-end run

**Estimated time:** 10 minutes + user action

**Files:** none committed (scratch queue under the session scratchpad).

**Steps:**
1. Write failing test for nothing new — this phase is a live check; step 1 is to run
   `keys-check` in the worktree and confirm both keys are `present`. Expected error if not: `{"APIFY_TOKEN": "missing"}` → STOP and ask the user.
2. With a scratch config (`[linkedin] keywords = ["software engineer"]`, `locations =
   ["United States"]`, `apify_max_items_per_run = 5`, `firecrawl_credits_per_run = 10`) run
   `linkedin-fetch` into a scratch queue; confirm `returned` ≤ 5, rows on the queue, state file
   written, `usd_charged` ≤ 0.0113.
3. Run it again immediately; confirm `window` is `r86400` and `duplicate` > 0 or `returned` 0.
4. Run `firecrawl-search --limit 2` twice then `firecrawl-scrape` once with the same
   `--run-state`; confirm `credits_spent_run` grows and a third search that would pass 10 is
   refused with `FirecrawlBudgetError`.
5. Record the outputs (no keys) and total spend in the ledger.

**Verification:**
- [ ] Live LinkedIn rows land on the queue with canonical `jobUrl` and full description
- [ ] Second run dedupes
- [ ] Firecrawl budget refusal observed live
- [ ] Total spend recorded in the ledger
- [ ] No placeholder/TODO comments in new code

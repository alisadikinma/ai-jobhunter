**Ticket:** AJOB-5

# LinkedIn discovery through Apify — spec

## Design

### Problem

`discover` has no dependable LinkedIn source. LinkedIn serves a login wall and HTTP 999 to
automated requests, so a Firecrawl search/scrape of LinkedIn postings does not return the full
description text that `score` and `promote` depend on. LinkedIn becomes a dedicated source,
fetched through one Apify actor.

### Decisions (made in brainstorm, 2026-09-22)

| Decision | Choice | Why |
| --- | --- | --- |
| How Apify is called | New stdlib subcommand `linkedin-fetch` (urllib, no SDK, no MCP) | Testable; the budget is enforced in code, not in skill prose; payloads go to disk, not into conversation context |
| Actor | `bebity/linkedin-jobs-scraper` | Only top-4 actor with a clean `workType` output (on-site/remote/hybrid) — `score` weights remote at 15 and `promote` canonicalises `workplaceType`. No login, no cookies. Research: vault `90-Inbox/agent-learnings/2026-09-22-apify-linkedin-jobs-actors.md` |
| Search input | `[linkedin] keywords` + `locations` in config | `targets.geo` values (`"US-remote"`) are not LinkedIn locations; mapping them would be a guess |
| Budget | `budgets.apify_max_items_per_run` (one number) | bebity is pay-per-event, so the `maxItems` query param does not cap its charge. The script derives a `maxTotalChargeUsd` from the item count as the money brake |
| Token | One `APIFY_TOKEN`, from the environment only (user keeps it in `.env`) | Never in `config.toml`, which may be committed |
| Repeat avoidance | Automatic posted-date window from local run state + existing queue dedupe | Keeps spend on new postings |

**Out of scope, deliberately.** No multi-token rotation or automatic failover between Apify
accounts. Apify's General Terms forbid creating or using multiple Personal Accounts
(<https://docs.apify.com/legal/general-terms-and-conditions>). The plugin reads exactly one
`APIFY_TOKEN`; what value it holds is the user's business, and nothing in the plugin cycles it.

### Config

```toml
[linkedin]
keywords   = ["AI engineer", "LLM engineer"]   # required and non-empty for linkedin-fetch
locations  = ["United States", "Worldwide"]    # required and non-empty
work_types = ["remote"]                         # optional; sent to the actor, never trusted

[budgets]
apify_max_items_per_run = 100                   # default 100; whole number >= 0; 0 disables LinkedIn
```

- `linkedin` joins `_KNOWN_TOP_LEVEL_KEYS`; unknown keys inside it warn like other sections.
- `apify_max_items_per_run` joins `_BUDGET_DEFAULTS` and goes through `_require_budget_int`
  (a quoted number or a negative raises `config.BudgetTypeError`).
- `work_types` values must be in {`on-site`, `remote`, `hybrid`}; anything else raises
  `config.ConfigError` naming the value.
- `templates/config.toml` gains the `[linkedin]` block and the new budget line; the three copies
  guarded by the byte-identity test are updated together.
- **Not in config:** the token. `APIFY_TOKEN` comes from the process environment. The skill tells
  the user to keep it in `.env` and to confirm `.env` is in their `.gitignore`.

### Components

**`scripts/apify.py`** — mirrors `ats.py`.

- `fetch_linkedin(search, max_items, token, dest, *, window)` — the only network code in the
  module. Async run, not run-sync (run-sync cuts off at 300 s with HTTP 408):
  1. `POST https://api.apify.com/v2/acts/bebity~linkedin-jobs-scraper/runs?maxTotalChargeUsd=<cap>`
     with the actor input as the JSON body and `Authorization: Bearer <token>`.
  2. Poll `GET /v2/actor-runs/{runId}?waitForFinish=60` until a terminal status
     (`SUCCEEDED`, `FAILED`, `TIMED-OUT`, `ABORTED`). Wall-clock ceiling 15 minutes; past it the
     run is aborted (`POST /v2/actor-runs/{runId}/abort`) and `ApifyError` is raised.
  3. `GET /v2/datasets/{defaultDatasetId}/items?format=json&clean=true&limit=<max_items>`,
     streamed to `dest` in chunks.
  4. Returns `{"run_id", "status", "returned", "usd_charged"}`, with `usd_charged` read from the
     run's `usageTotalUsd`.
- `normalize_linkedin(path)` — pure; reads `dest`, returns `ats._Rows` so skipped postings are
  reported on the same `skipped` key as `ats-fetch`.
- `remaining_credit_usd(token)` — reads the account's monthly usage and limit. The exact endpoint
  and field names are verified against docs.apify.com during planning, not assumed here.
- Charge cap: `maxTotalChargeUsd = max_items × 0.001 × 2`, i.e. twice bebity's listed
  $1.00 / 1,000 results (fetched 2026-09-22). The constant carries its source and date in a
  comment.

**Actor input** (bebity field names; exact enum strings for `publishedAt` and `workTypes`, and
whether an exclude-ids field exists, are read from the actor's live input schema during
planning — never guessed):

| Config | Actor input |
| --- | --- |
| `linkedin.keywords` | `titles` |
| `linkedin.locations` | `locations` |
| `linkedin.work_types` | `workTypes` |
| automatic window (below) | `publishedAt` |
| `apify_max_items_per_run` | `rows` |

**Repeat avoidance.**

- State file `.jobhunter/queue/linkedin-state.json`: `{"last_success_at": "<ISO-8601 UTC>"}`.
  Written only after a run whose status is `SUCCEEDED` and whose rows were appended. A failed run
  leaves it untouched, so the next run does not skip the window the failed one missed.
- Window: gap since `last_success_at` < 24 h → past 24 h; < 7 days → past week; else, or no state
  file → past month.
- The state file is local and not keyed to any account, so changing `APIFY_TOKEN` does not reset it.
- Queue dedupe (`jobq.row_key`, by `jobUrl`) keeps a re-fetched posting from being written twice.
- If bebity's live input schema has an exclude-by-id field, the LinkedIn job ids already in the
  queue are passed in it so they are not charged again. If it has none, overlap inside the window
  is still charged, and the report shows how much (`duplicate` count).

**Credit brake.** Before starting a run, `linkedin-fetch` reads the remaining monthly credit. If it
is below that run's `maxTotalChargeUsd`, the command refuses with `apify.ApifyCreditError` and
starts nothing. The brake exists so a run never starts that the account cannot pay for.

**`scripts/jobhunter.py`** — new subcommand:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" linkedin-fetch \
  --config .jobhunter/config.toml \
  --queue .jobhunter/queue/jobs.jsonl \
  --dest /tmp/linkedin.json
```

It reads config, checks the token and the credit, fetches, normalises, and appends to the queue,
then updates the state file. It prints one JSON document:
`{"window", "requested", "returned", "new", "duplicate", "skipped", "usd_charged",
"credit_remaining_usd"}`. `rows` is not echoed; they are already on the queue.

### Normalisation (bebity output → queue row)

| bebity | queue | Rule |
| --- | --- | --- |
| `companyName` | `company` | required |
| `title` | `jobTitle` | required |
| `description` | `jobDescription` | required; through `ats._clean_description` |
| `jobUrl` | `jobUrl` | required |
| `location` | `location` | when present |
| `workType` | `workplaceType` | only `on-site`/`remote`/`hybrid` (folded like `promote._canonicalize_workplace_type`); any other value leaves the field absent, never guessed |
| `contractType` | `jobType` | when present |
| — | `source` | `"LinkedIn"` |

A posting missing a required field is `skipped` with the field named. Every posting failing is a
schema change and raises `MissingFieldError` loudly, exactly as `ats._normalize_all` does.

### Errors

New classes in `scripts/apify.py`; each surfaces as `{"error": "<class>", "message": "..."}` on
stderr, exit 1:

- `ApifyError` — base: HTTP 401/403/404/429 and other non-2xx (message carries the status and
  Apify's `error.message`), a terminal status other than `SUCCEEDED`, the 15-minute ceiling,
  a non-JSON body.
- `ApifyTokenMissingError(ApifyError)` — `APIFY_TOKEN` unset or empty.
- `ApifyCreditError(ApifyError)` — remaining credit below the run's cap, or HTTP 402.
- Missing `[linkedin]`, or empty `keywords`/`locations` → `config.ConfigError`.

Fewer postings than requested is **not** an error. LinkedIn caps searches and blocks with HTTP 999;
the report shows `requested` vs `returned`.

CLAUDE.md's error-class list gains `apify.{ApifyError, ApifyTokenMissingError, ApifyCreditError}`.

### Skill `discover`

- LinkedIn is fetched only through `linkedin-fetch`. Firecrawl is no longer used for LinkedIn
  postings.
- No `APIFY_TOKEN`, or `apify_max_items_per_run = 0` → LinkedIn is skipped and the final report
  says so. No fallback to Firecrawl for LinkedIn.
- `ApifyCreditError` → LinkedIn stops for this run and the report says credit is exhausted;
  other sources continue.
- A short ToS note: the actor reads public guest listings only; the user's LinkedIn account is
  never used; LinkedIn's User Agreement §8.2 still prohibits scraping, and that risk is the user's.
- The final report adds the LinkedIn line: window, returned, new, duplicate, USD charged,
  credit remaining.

### Tests (stdlib `unittest`)

- **Fixture from a real run.** One live run with the user's token (5 postings, about $0.01),
  saved to `tests/fixtures/apify_linkedin.json`. Not hand-written. Any personal data in the
  posting (poster name, profile URL) is scrubbed before commit.
- `normalize_linkedin` against the fixture: required fields, `workType` fold, unknown `workType`
  left absent, one bad posting skipped, all bad raises.
- `fetch_linkedin` with a fake `urlopen`: success path; 401; 402; 404; 429; `FAILED`; `ABORTED`;
  `TIMED-OUT`; ceiling reached, which also sends abort; empty dataset; non-JSON body. Asserts the
  Bearer header, the `maxTotalChargeUsd` value, and that the token never appears in a URL or in
  any logged line.
- Window selection: no state, 3 h, 30 h, 8 days. The state file is untouched after a failed run.
- Config: `[linkedin]` validation, `apify_max_items_per_run` default/negative/quoted, invalid
  `work_types`.
- Credit brake: below cap refuses before any POST; equal or above proceeds.
- `test_manifest.py` still passes (nothing candidate-specific under `skills/`).
- Per the debugging checklist: every guard is mutated once to watch its test fail.

## Data Integration Map

| Component | Data source | Existing? | Notes |
| --- | --- | --- | --- |
| Actor run | Apify REST v2 `/acts/.../runs` | external, live | token from env |
| Run status + cost | `/actor-runs/{id}` `usageTotalUsd` | external, live | |
| Postings | `/datasets/{id}/items` | external, live | streamed to disk |
| Remaining credit | Apify user limits endpoint | external, live | endpoint verified at plan time |
| Queue | `.jobhunter/queue/jobs.jsonl` via `jobq.append_rows` | yes | dedupe by `row_key` |
| Run state | `.jobhunter/queue/linkedin-state.json` | new | local, account-agnostic |
| Search terms | `.jobhunter/config.toml` `[linkedin]` | new section | |

No placeholder: every source above is real. The fixture comes from a real run.

**Ticket:** AJOB-5

# Discovery over REST with keys in `.env` — LinkedIn through Apify, boards through Firecrawl — spec

## Design

### Problem

1. `discover` has no dependable LinkedIn source. LinkedIn serves a login wall and HTTP 999 to
   automated requests, so a Firecrawl search/scrape of LinkedIn postings does not return the full
   description text that `score` and `promote` depend on.
2. `discover` reaches Firecrawl through MCP tools. The Firecrawl key then lives in the MCP server
   config (`~/.claude.json`), not in the user's project, and `budgets.firecrawl_credits_per_run`
   is enforced only by skill prose — nothing in code stops a call past the ceiling.

Both are fixed the same way: stdlib Python calls the provider's REST API with a key the user keeps
in `.env`, writes payloads to disk, and enforces the budget before each call.

### Decisions (brainstorm, 2026-09-22)

| Decision | Choice | Why |
| --- | --- | --- |
| How providers are called | New stdlib subcommands (urllib). No SDK, no MCP | Testable; budgets enforced in code; payloads on disk, not in conversation context |
| Keys | `APIFY_TOKEN`, `FIRECRAWL_API_KEY` from the process env, else from `.env` | The user asked for `.env`; env wins so CI/shell exports still work |
| LinkedIn actor | `bebity/linkedin-jobs-scraper` | Only top-4 actor that is documented to emit a work-type field; no login, no cookies. Research: vault `90-Inbox/agent-learnings/2026-09-22-apify-linkedin-jobs-actors.md` |
| LinkedIn search input | `[linkedin] keywords` + `locations` | `targets.geo` values (`"US-remote"`) are not LinkedIn locations; mapping them would be a guess |
| LinkedIn budget | `budgets.apify_max_items_per_run` (one number) | Script derives the actor's `rows`, the run's `maxItems`, and a `maxTotalChargeUsd` money brake from it |
| Firecrawl budget | existing `budgets.firecrawl_credits_per_run`, now enforced in code | Checked before every call against the account's real credit balance |
| Repeat avoidance | Automatic posted-date window from local run state + queue dedupe on a canonical LinkedIn URL | Spend goes to new postings; tracking params never create a second row |

**Rejected, with reasons.**

- **Multi-token rotation / automatic failover between Apify accounts.** Apify's General Terms:
  "you shall not create or use multiple Personal Accounts, either directly or through third
  parties, even if registered with different email addresses"
  (<https://docs.apify.com/legal/general-terms-and-conditions>). The plugin reads exactly one
  `APIFY_TOKEN`; nothing in it cycles tokens.
- **`Panniantong/Agent-Reach`.** Its LinkedIn channel logs in with the user's own LinkedIn account
  through browser automation (`mcp-server-linkedin --login`), needs non-stdlib binaries
  (yt-dlp, gh, uvx, Node, third-party CLIs), installs by executing a remote markdown's shell
  commands, and enforces no budget. Taken: only the idea of a per-source `check()` that reports
  whether its key is present and how to fix it.
- **jobsync as a discovery source.** Its "Automations" poll Greenhouse/Lever/Ashby (already in
  `ats.py`) plus Remotive/Jobicy, internally only; none of its 9 MCP tools starts or reads
  discovery. Taken: key LinkedIn dedupe on the numeric job id, not the raw URL.

### Keys: `scripts/envfile.py`

- `read_key(name, env_file)` → the value of `os.environ[name]` when set and non-empty; else the
  value of a `name=...` line in `env_file`; else `None`.
- `.env` parsing, stdlib only: skip blank lines and `#` comments; accept an optional leading
  `export `; split on the first `=`; strip surrounding whitespace and one pair of matching
  `'` or `"` quotes. Only the requested key is returned; the file is never echoed.
- `env_file` defaults to `.env` in the current directory (the user's project root, where skills
  run). A missing file is not an error — it is "no key".
- The key never appears in a URL, a log line, an error message, or stdout. Tests assert this.

### Config

```toml
[linkedin]
keywords   = ["AI engineer", "LLM engineer"]   # required and non-empty for linkedin-fetch
locations  = ["United States", "Worldwide"]    # required and non-empty
work_types = ["remote"]                         # optional; on-site | remote | hybrid

[budgets]
apify_max_items_per_run = 100                   # default 100; whole number >= 0; 0 disables LinkedIn
```

- `linkedin` joins `_KNOWN_TOP_LEVEL_KEYS`; unknown keys inside it warn like other sections.
- `apify_max_items_per_run` joins `_BUDGET_DEFAULTS` and goes through `_require_budget_int`.
- A `work_types` value outside {`on-site`, `remote`, `hybrid`} raises `config.ConfigError`.
- `templates/config.toml` gains the `[linkedin]` block and the budget line. The drift guard
  `tests/test_manifest.py::TestConfigTemplateMatchesTheSpec` requires the template to equal the
  TOML block in `docs/plans/2026-09-19-AJOB-1-ai-jobhunter-pipeline-spec.md` §4 and in
  `docs/plans/2026-09-19-AJOB-1-ai-jobhunter-pipeline-plan.md`; all three are updated in one
  commit. This spec and its plan carry no `profile_sources` TOML block, so the guard's
  "exactly one document" rule still holds.
- Keys are **not** in config.

### LinkedIn: `scripts/apify.py`

Facts verified 2026-09-22 against the actor's live build `0.0.222` and docs.apify.com:

| Actor input | Value sent |
| --- | --- |
| `titles` | `linkedin.keywords` |
| `locations` | `linkedin.locations` |
| `workTypes` | `linkedin.work_types` mapped `on-site`→`"1"`, `remote`→`"2"`, `hybrid`→`"3"` |
| `publishedAt` | automatic window: `"r86400"` / `"r604800"` / `"r2592000"` |
| `rows` | `ceil(max_items / (len(keywords) × len(locations)))` — `rows` is **per title×location search**, and its default `0` means "all" |
| `companyProfile` | `false` (default is `true`; company data is unused and slows the run) |
| `enrichCompany` | `false` (premium add-on, extra charge per job) |

The actor has **no** field for excluding already-seen job ids; overlap inside a window is charged.

- `fetch_linkedin(actor_input, max_items, token, dest)` — the only network code:
  1. `POST https://api.apify.com/v2/acts/bebity~linkedin-jobs-scraper/runs?maxItems=<max_items>&maxTotalChargeUsd=<cap>`,
     JSON body = actor input, header `Authorization: Bearer <token>`. Async, not run-sync
     (run-sync ends at 300 s with HTTP 408).
  2. Poll `GET /v2/actor-runs/{runId}?waitForFinish=60` until `SUCCEEDED`, `FAILED`,
     `TIMED-OUT` or `ABORTED`. Wall-clock ceiling 15 minutes; past it,
     `POST /v2/actor-runs/{runId}/abort` and raise `ApifyError`.
  3. `GET /v2/datasets/{defaultDatasetId}/items?format=json&clean=true&limit=<max_items>`,
     streamed to `dest` in chunks.
  4. Returns `{"run_id", "status", "returned", "usd_charged"}`; `usd_charged` = run `usageTotalUsd`.
- `remaining_credit_usd(token)` — `GET /v2/users/me/limits`;
  `data.limits.maxMonthlyUsageUsd − data.current.monthlyUsageUsd`.
- Charge cap: `maxTotalChargeUsd = max_items × 0.0015 × 1.5`. `0.0015` is bebity's FREE-tier
  price per job result (`apify-default-dataset-item`, fetched 2026-09-22 from
  `GET /v2/acts/bebity~linkedin-jobs-scraper`); the 1.5 covers the actor-start event and a
  price change. The constant carries source and date in a comment.
- `normalize_linkedin(path)` — pure; returns `ats._Rows`.

**Normalisation (bebity → queue row).**

| bebity | queue | Rule |
| --- | --- | --- |
| `companyName` | `company` | required |
| `title` | `jobTitle` | required |
| `description` | `jobDescription` | required; through `ats._clean_description` |
| `jobUrl` | `jobUrl` | required; rewritten to `https://www.linkedin.com/jobs/view/<id>/` using the numeric id, so tracking params never produce a second row. No id found → posting skipped |
| `location` | `location` | when present |
| `workType` | `workplaceType` | `on-site`/`remote`/`hybrid` folded as `promote._canonicalize_workplace_type` does; anything else → field absent, never guessed |
| `contractType` | `jobType` | when present |
| — | `source` | `"LinkedIn"` |

A posting missing a required field is `skipped` with the field named; every posting failing is a
schema change and raises `MissingFieldError`, as `ats._normalize_all` does.

**Gate on `workType`.** The actor's pricing text lists "work type" in the base job result, while
its input docs list "workplace type" among `enrichCompany`'s premium signals. The fixture run
settles it. If the base result carries no work-type value, execution STOPS and asks the user
whether to turn on `enrichCompany` (FREE tier +$0.001 per job) or ship LinkedIn rows without
`workplaceType`.

**Repeat avoidance.**

- State file `<queue dir>/linkedin-state.json`: `{"last_success_at": "<ISO-8601 UTC>"}`, written
  only after a `SUCCEEDED` run whose rows were appended. A failed run leaves it untouched.
- Window: gap < 24 h → `r86400`; < 7 days → `r604800`; else, or no state → `r2592000`.
- Local and account-agnostic: changing `APIFY_TOKEN` does not reset it.
- Queue dedupe (`jobq.row_key` on the canonical `jobUrl`) keeps a re-fetched posting out.

**Credit brake.** Before starting, `linkedin-fetch` reads the remaining monthly credit; below the
run's `maxTotalChargeUsd` it refuses with `apify.ApifyCreditError` and starts nothing.

Free-plan arithmetic, stated so nobody over-plans: $5/month ÷ $0.0015 ≈ 3,300 jobs/month; 100 a
day uses about $4.50 of it.

### Boards: `scripts/firecrawl.py`

Facts verified 2026-09-22 against docs.firecrawl.dev (API v2):

- `search(key, query, limit, dest, *, tbs=None, location=None)` →
  `POST https://api.firecrawl.dev/v2/search`, body `{query, limit, tbs?, location?,
  scrapeOptions: {formats: ["markdown"], onlyMainContent: true, proxy: "basic"}}`, header
  `Authorization: Bearer <key>`. Full page markdown comes back in the same call, which satisfies
  the skill's "full posting text, not a snippet" rule. Response `data.web[]` written to `dest`.
- `scrape(key, url, dest)` → `POST /v2/scrape`, body `{url, formats: ["markdown"],
  onlyMainContent: true, proxy: "basic", timeout: 60000}`. `proxy: "basic"` is deliberate:
  `auto` may escalate to a pricier proxy, and LinkedIn — the site that needed it — now goes
  through Apify.
- `remaining_credits(key)` → `GET /v2/team/credit-usage`, `data.remainingCredits`.
- Errors: body `{"success": false, "error": "..."}`. 401 → `FirecrawlError`; 402 →
  `FirecrawlCreditError`; 408/429/5xx → retried up to 3 times with backoff, honouring
  `Retry-After` on 429, then `FirecrawlError`.

**Budget enforced in code.** A run-state file (`--run-state`, one per discover run) records the
credit balance when the run started and the credits spent so far. Before each call:

- spent = max(sum of `creditsUsed` reported by responses, start balance − current balance);
- estimate for the call: search = `2 × ceil(limit / 10)` + `limit` (the markdown scrape of each
  result); scrape = `1`;
- spent + estimate > `budgets.firecrawl_credits_per_run` → refuse with
  `FirecrawlBudgetError`, call not made. The per-call estimate is documented as an upper bound;
  where docs.firecrawl.dev gives no flat per-page price, the balance delta is the truth.

Rows found before the ceiling are still appended; the report says how many credits were spent and
how many remained when it stopped — the existing SKILL.md rule, now backed by code.

**Monitors — removed (user confirmed at spec review, 2026-09-22).** The skill documents `firecrawl_monitor_create` for
"configured career pages", but no config key has ever held a career-page list, so the tool has no
input. A monitor also spends credits on its own schedule, outside any run's budget. This spec drops
it; a later ticket can add `[targets] career_pages` and REST `/v2/monitor` together if wanted.

### CLI (`scripts/jobhunter.py`)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" linkedin-fetch \
  --config .jobhunter/config.toml --queue .jobhunter/queue/jobs.jsonl \
  --dest /tmp/linkedin.json [--env-file .env]

python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" firecrawl-search \
  --config .jobhunter/config.toml --run-state /tmp/fc-run.json \
  --query "<query>" --limit 10 --dest /tmp/search.json [--env-file .env]

python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" firecrawl-scrape \
  --config .jobhunter/config.toml --run-state /tmp/fc-run.json \
  --url "<posting url>" --dest /tmp/posting.json [--env-file .env]

python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" keys-check [--env-file .env]
```

- `linkedin-fetch` reads config, key, credit; fetches; normalises; appends to the queue; updates
  state. Prints `{"window", "requested", "returned", "new", "duplicate", "skipped",
  "usd_charged", "credit_remaining_usd"}`.
- `firecrawl-search` / `firecrawl-scrape` print `{"dest", "results"|"url", "credits_spent_run",
  "credits_budget", "credits_remaining_account"}`. Turning board markdown into queue rows stays
  the model's job, then `queue-append` — exactly as today.
- `keys-check` prints `{"APIFY_TOKEN": "present"|"missing", "FIRECRAWL_API_KEY": ..., "env_file":
  "<path>"|"not found"}` — presence only, never a value.

### Errors

New classes, each `{"error": "<class>", "message": "..."}` on stderr, exit 1:

- `apify.{ApifyError, ApifyTokenMissingError, ApifyCreditError}`
- `firecrawl.{FirecrawlError, FirecrawlKeyMissingError, FirecrawlCreditError, FirecrawlBudgetError}`
- Missing `[linkedin]` or empty `keywords`/`locations`, invalid `work_types` → `config.ConfigError`.

Fewer LinkedIn postings than requested is not an error; the report shows `requested` vs
`returned`. CLAUDE.md's error-class list and subcommand list are updated.

### Skill `discover`

- All `mcp__firecrawl__*` tool references are removed; board search/scrape go through
  `firecrawl-search` / `firecrawl-scrape`. LinkedIn goes only through `linkedin-fetch`.
- Start of run: `keys-check`. A missing key skips that source and the final report says which key
  is missing and that it belongs in `.env`. No source falls back to another.
- `.env` must be in the project's `.gitignore`; the skill checks with `git check-ignore -q .env`
  and warns if not.
- `ApifyCreditError` / `FirecrawlCreditError` / `FirecrawlBudgetError` stop that source for the
  run; other sources continue.
- ToS note: the LinkedIn actor reads public guest listings only; the user's LinkedIn account is
  never used; LinkedIn's User Agreement §8.2 still prohibits scraping, and that risk is the user's.
- Final report adds: LinkedIn window/returned/new/duplicate/USD/credit left; Firecrawl credits
  spent/budget/account balance.

### Tests (stdlib `unittest`)

- **Real fixture.** One live bebity run with the user's token (5 postings, ≈ $0.01) saved to
  `tests/fixtures/apify_linkedin.json`, recruiter name/profile URL/photo scrubbed. One live
  Firecrawl search (limit 2) saved to `tests/fixtures/firecrawl_search.json`. Not hand-written.
- `envfile`: env wins; `.env` fallback; comments, `export`, quotes, `=` inside value; missing
  file; key absent.
- `normalize_linkedin`: required fields, canonical `jobUrl` from several URL shapes, `workType`
  fold, unknown `workType` absent, one bad posting skipped, all bad raises.
- `fetch_linkedin` with a fake `urlopen`: success; 401; 402; 404; 429; `FAILED`; `ABORTED`;
  `TIMED-OUT`; ceiling → abort sent; empty dataset; non-JSON. Asserts Bearer header, `maxItems`,
  `maxTotalChargeUsd`, `rows` arithmetic, and that the token is in no URL, log line or message.
- Window: no state, 3 h, 30 h, 8 days; state untouched after a failed run.
- Credit brakes (Apify and Firecrawl): below → refused before any POST; equal/above → proceeds.
- Firecrawl budget: estimate + spent over the ceiling refuses; `max(reported, delta)` used;
  429 with `Retry-After` retried; 402 not retried.
- Config: `[linkedin]` validation, `apify_max_items_per_run` default/negative/quoted,
  `work_types` values; template drift guard green with all three copies updated.
- `test_manifest.py`: new subcommands and their flags collected from SKILL.md (a per-command
  assertion like `test_template_check_and_all_six_of_its_flags_are_collected`), and no
  `mcp__firecrawl__` left in `skills/discover/SKILL.md`.
- Every guard is mutated once to watch its test fail (CLAUDE.md debugging checklist).

## Data Integration Map

| Component | Data source | Existing? | Notes |
| --- | --- | --- | --- |
| Keys | process env, `.env` | new reader | presence-only reporting |
| LinkedIn run | Apify `/v2/acts/bebity~linkedin-jobs-scraper/runs` | external, live | |
| LinkedIn run status + cost | `/v2/actor-runs/{id}` `usageTotalUsd` | external, live | |
| LinkedIn postings | `/v2/datasets/{id}/items` | external, live | streamed to disk |
| Apify credit | `/v2/users/me/limits` | external, live | |
| Board search | Firecrawl `/v2/search` | external, live | replaces MCP |
| Posting page | Firecrawl `/v2/scrape` | external, live | replaces MCP |
| Firecrawl credit | `/v2/team/credit-usage` | external, live | |
| Queue | `.jobhunter/queue/jobs.jsonl` via `jobq.append_rows` | yes | dedupe by `row_key` |
| LinkedIn run state | `.jobhunter/queue/linkedin-state.json` | new | local |
| Firecrawl run state | `--run-state` path | new | one per run |
| Search terms | `.jobhunter/config.toml` `[linkedin]` | new section | |

No placeholder: every source is real; both fixtures come from real calls.

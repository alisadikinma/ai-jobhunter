# PROGRESS — AJOB-5: discovery over REST with keys in .env (Apify LinkedIn + Firecrawl)

**Ticket:** AJOB-5
**Plan:** docs/plans/2026-09-22-AJOB-5-apify-linkedin-plan.md
**Spec:** docs/plans/2026-09-22-AJOB-5-apify-linkedin-spec.md

## Pre-flight

| Gate | Result |
|---|---|
| Git clean | PASS — baseline `9869206` (spec) |
| Baseline suite | PASS — `python3 -m unittest discover -s tests -t .`, 744 lulus / 0 gagal |
| detect-stack | no stack markers — commands from CLAUDE.md |

## Keputusan saat jalan

- 2026-09-22 Monitor Firecrawl dihapus dari discover — diputuskan Ali di review spec.

## Checklist

### [ ] Phase A: `.env` key reader
- [ ] Write failing test for `read_key` returning the env var over the file value. Expected error: `ModuleNotFoundError: No module named 'envfile'`
- [ ] Run `python3 -m unittest tests.test_envfile`, confirm it fails for that reason.
- [ ] Add tests (each its own method): file fallback; `export KEY=v`; `KEY="v"` and `KEY='v'`;
  `KEY=a=b` returns `a=b`; `# KEY=x` ignored; blank env var falls through to file; missing file
  → `None`; key absent → `None`; mismatched quotes kept verbatim; `key_status` never contains a
  value (assert the secret string is absent from `json.dumps(result)`).
- [ ] Implement `scripts/envfile.py` (module docstring states why env wins and that values are never
  echoed). Use `mock.patch.dict(os.environ, ..., clear=False)` and `tempfile` in tests.
- [ ] Add `.env` to `.gitignore`; confirm `git check-ignore -q .env` exits 0.
- [ ] Mutation check: make `read_key` prefer the file over env; watch the env-wins test fail; revert.
- [ ] Commit: `feat(envfile): read provider keys from env or .env`
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] Security: no key value in any return other than `read_key`; `.env` is git-ignored
- [ ] Mutation of env-precedence made a test fail
- [ ] No placeholder/TODO comments in new code

### [ ] Phase B: config `[linkedin]` + `apify_max_items_per_run`
- [ ] Write failing test for `load` returning `budgets["apify_max_items_per_run"] == 100` by default. Expected error: `KeyError: 'apify_max_items_per_run'`
- [ ] Run it, confirm the failure.
- [ ] Add tests: file value 25 kept with provenance `file`; `"25"` → `BudgetTypeError`; `-1` →
  `BudgetTypeError`; `[linkedin]` parsed; absent section → empty lists; `keywords = "x"` →
  `ConfigError`; `keywords = [""]` → `ConfigError`; `work_types = ["remote-ish"]` →
  `ConfigError`; unknown `[linkedin] keyword = [...]` → `UserWarning`; `[linkedin]` no longer
  triggers the unknown-top-level warning.
- [ ] Implement in `scripts/config.py`.
- [ ] Update `templates/config.toml` and both AJOB-1 docs; run
  `python3 -m unittest tests.test_manifest` — `TestConfigTemplateMatchesTheSpec` must pass.
- [ ] Mutation check: drop `"linkedin"` from `_KNOWN_TOP_LEVEL_KEYS`, watch the warning test fail;
  revert. Edit one AJOB-1 copy only, watch the drift guard fail; revert.
- [ ] Commit: `feat(config): [linkedin] section and apify_max_items_per_run budget`
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] `templates/config.toml` equals the AJOB-1 spec and plan blocks (drift guard green)
- [ ] Both mutations made a test fail
- [ ] No placeholder/TODO comments in new code

### [ ] Phase C: capture real fixtures (needs the user's keys)
- [ ] Write failing test for the fixture's shape in `tests/test_apify.py`: the file loads as a JSON
  list of ≥ 1 objects each having `title`, `companyName`, `description`, `jobUrl`. Expected error: `FileNotFoundError: ... tests/fixtures/apify_linkedin.json`
- [ ] Run it, confirm the failure.
- [ ] Write a throwaway capture script in the session scratchpad (not the repo) that uses stdlib
  `urllib` with the Bearer header to: start a run of `bebity~linkedin-jobs-scraper` with
  `?maxItems=5&maxTotalChargeUsd=0.05` and input `{"titles": ["software engineer"],
  "locations": ["United States"], "rows": 5, "publishedAt": "r604800", "companyProfile": false,
  "enrichCompany": false}`; poll with `waitForFinish=60`; download items with `limit=5`.
  Report the run's `usageTotalUsd` to the user.
- [ ] **Gate on `workType`:** inspect the items. If no item has a non-empty `workType` (or an
  equivalent on-site/remote/hybrid field — record the exact field name found), STOP and ask the
  user via AskUserQuestion: `[enrichCompany on — +$0.001/job]` / `[ship without workplaceType]`.
  Record the answer under `## Keputusan saat jalan` in the ledger. If they choose enrich, re-run
  the capture with `"enrichCompany": true`.
- [ ] Scrub before saving: delete keys `posterFullName`, `posterProfileUrl`, `posterHeadline`,
  `posterPhoto`, and any other key whose value is a person's name or a `linkedin.com/in/` URL.
  Keep everything else verbatim. Save to `tests/fixtures/apify_linkedin.json` (indent 2).
- [ ] Firecrawl: `POST /v2/search` with `{"query": "software engineer jobs greenhouse", "limit": 2,
  "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": true, "proxy": "basic"}}`; save
  the full response to `tests/fixtures/firecrawl_search.json`. Record `creditsUsed`. Also call
  `GET /v2/team/credit-usage` once and record the response **keys only** in the ledger.
- [ ] Run the shape test, confirm it passes; add the same kind of shape test for
  `firecrawl_search.json` (`success` true, `data.web` list, each with `url`, `markdown`).
- [ ] `git grep -n -i "linkedin.com/in/" tests/fixtures/` must print nothing.
- [ ] Commit: `test(fixtures): real bebity and Firecrawl search payloads for AJOB-5`
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] Both fixtures came from real calls; spend recorded in the ledger
- [ ] `workType` gate decided and recorded
- [ ] Security: no key in any committed file (`git grep -n "fc-" tests/` shows only doc text, if any); no personal profile data in fixtures
- [ ] No placeholder/TODO comments in new code

### [ ] Phase D: `normalize_linkedin`
- [ ] Write failing test for `normalize_linkedin` on the real fixture returning rows with `source ==
  "LinkedIn"` and canonical `jobUrl`. Expected error: `ModuleNotFoundError: No module named 'apify'`
- [ ] Run it, confirm the failure.
- [ ] Add tests: canonical URL from `https://www.linkedin.com/jobs/view/senior-ai-engineer-at-acme-4012345678?refId=x&trk=y`,
  from `.../jobs/view/4012345678/`, from `...?currentJobId=4012345678`, from `id` field; no id →
  skipped with key `jobUrl`; missing `title` → skipped naming `title`; every posting bad →
  `MissingFieldError`; `"Remote"`, `"on-site"`, `"On Site"`, `"HYBRID"` fold; `"Contract"` as
  work type → no `workplaceType`; two postings same id different tracking → same `jobq.row_key`;
  non-list JSON → `ApifyError`.
- [ ] Implement.
- [ ] Mutation check: return the raw `jobUrl` instead of the canonical one; watch the row_key test
  fail; revert.
- [ ] Commit: `feat(apify): normalise bebity LinkedIn postings to queue rows`
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] Rows built from the real fixture, not hand-written data
- [ ] Mutation made a test fail
- [ ] No placeholder/TODO comments in new code

### [ ] Phase E: Apify fetch, credit brake, window state
- [ ] Write failing test for `fetch_linkedin` success path with a fake `urlopen` (a sequence of
  canned responses: start 201 → poll RUNNING → poll SUCCEEDED with `usageTotalUsd` 0.0075 →
  items). Expected error: `AttributeError: module 'apify' has no attribute 'fetch_linkedin'`
- [ ] Run it, confirm the failure.
- [ ] Add tests: Bearer header present on every request; no request URL contains the token; start URL
  has `maxItems=100&maxTotalChargeUsd=0.225` for 100 items; `rows` = 50 for 2 keywords × 1
  location × 100, 34 for 3 × 1 × 100; 401 → `ApifyError` with "HTTP 401"; 402 →
  `ApifyCreditError`; 404; 429; terminal `FAILED`, `ABORTED`, `TIMED-OUT` → `ApifyError`
  naming the status; ceiling → abort POST sent then `ApifyError`; empty dataset → returned 0,
  no error; non-JSON body → `ApifyError`; token absent from every raised message and from
  captured stderr. `remaining_credit_usd` arithmetic. `choose_window`: no file, 3 h, 30 h,
  8 days, garbage file. `write_state` round-trip.
- [ ] Implement.
- [ ] Mutation check: remove the ceiling check; watch the ceiling test hang-guard (use a fake clock)
  fail; revert. Put the token in the query string; watch the no-token-in-URL test fail; revert.
- [ ] Commit: `feat(apify): run bebity with charge cap, poll, stream dataset`
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] Security: token only in the Authorization header; never in URL, log, or error text
- [ ] Both mutations made a test fail
- [ ] No placeholder/TODO comments in new code

### [ ] Phase F: `linkedin-fetch` subcommand
- [ ] Write failing test for `linkedin-fetch` emitting the report with `apify.fetch_linkedin` and
  `apify.remaining_credit_usd` patched and the real fixture copied to `--dest`. Expected error: argparse `invalid choice: 'linkedin-fetch'` in the JSON usage error on stderr.
- [ ] Run it, confirm the failure.
- [ ] Add tests: budget 0 → skip report, no network call; missing `[linkedin]` → `ConfigError`;
  no token (env cleared, no file) → `ApifyTokenMissingError` JSON, exit 1; credit below cap →
  `ApifyCreditError` and `fetch_linkedin` never called; second run with the same fixture →
  `new` 0, `duplicate` = first run's `new`; failed fetch → state file unchanged; `--help` lists
  all four flags.
- [ ] Implement.
- [ ] Mutation check: write state before the fetch; watch the failed-fetch test fail; revert.
- [ ] Commit: `feat(cli): linkedin-fetch subcommand`
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] Security: key read only via `envfile`; never emitted
- [ ] Mutation made a test fail
- [ ] No placeholder/TODO comments in new code

### [ ] Phase G: Firecrawl REST client and run budget
- [ ] Write failing test for `search` writing `data.web` from the real fixture (served by a fake
  `urlopen`) to `dest`. Expected error: `ModuleNotFoundError: No module named 'firecrawl'`
- [ ] Run it, confirm the failure.
- [ ] Add tests: request body exact (incl. `proxy: "basic"`); Bearer header; key in no URL/message;
  401; 402 not retried (one call); 429 with `Retry-After: 3` sleeps 3 then succeeds; 5xx three
  times → `FirecrawlError`; `success: false` → error; limit 0 and 101 → `ValueError`; `estimate`
  for limits 1, 10, 11; `Budget`: fresh file, over-ceiling refuses before the call, `max(reported,
  delta)` both directions, corrupted file → `FirecrawlError` naming the path.
- [ ] Implement.
- [ ] Mutation check: make 402 retryable; watch the not-retried test fail; revert. Use `min` instead
  of `max` in `spent`; watch the delta test fail; revert.
- [ ] Commit: `feat(firecrawl): REST v2 search/scrape with an enforced run budget`
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] Security: key only in the Authorization header
- [ ] Both mutations made a test fail
- [ ] No placeholder/TODO comments in new code

### [ ] Phase H: `firecrawl-search`, `firecrawl-scrape`, `keys-check` subcommands
- [ ] Write failing test for `keys-check` reporting `present`/`missing` without the value. Expected error: argparse `invalid choice: 'keys-check'`.
- [ ] Run it, confirm the failure.
- [ ] Add tests: search happy path with `firecrawl.search` / `remaining_credits` patched; budget
  exhausted → `FirecrawlBudgetError` JSON on stderr, `search` never called; missing key →
  `FirecrawlKeyMissingError`; scrape happy path; the run-state file accumulates across two
  calls; `--help` of each lists every flag.
- [ ] Implement.
- [ ] Mutation check: call before `check`; watch the budget-exhausted test fail; revert.
- [ ] Commit: `feat(cli): firecrawl-search, firecrawl-scrape, keys-check`
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] Security: `keys-check` output contains no key value (asserted)
- [ ] Mutation made a test fail
- [ ] No placeholder/TODO comments in new code

### [ ] Phase I: `discover` SKILL.md, manifest guards, CLAUDE.md
- [ ] Write failing test in `tests/test_manifest.py` asserting `linkedin-fetch` is collected with
  flags `{"--config", "--queue", "--dest", "--env-file"}`. Expected error: `AssertionError: 'linkedin-fetch' not found in ...`
- [ ] Run it, confirm the failure.
- [ ] Add tests: `firecrawl-search` flags collected; `firecrawl-scrape` flags collected; `keys-check`
  collected; `skills/discover/SKILL.md` contains no `mcp__firecrawl__`; every error class named
  in the SKILL.md exists as an attribute of its module.
- [ ] Rewrite the SKILL.md sections; update CLAUDE.md (measure the new test count by running the
  suite — do not guess it); bump plugin version.
- [ ] Mutation check: misspell one flag in SKILL.md; watch the flag guard fail; revert.
- [ ] Commit: `docs(discover): REST sources with keys in .env; drop Firecrawl MCP and monitors`
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] CLAUDE.md test count equals the measured count
- [ ] Mutation made a test fail
- [ ] No placeholder/TODO comments in new code

### [ ] Phase J: live end-to-end run
- [ ] Write failing test for nothing new — this phase is a live check; step 1 is to run
  `keys-check` in the worktree and confirm both keys are `present`. Expected error if not: `{"APIFY_TOKEN": "missing"}` → STOP and ask the user.
- [ ] With a scratch config (`[linkedin] keywords = ["software engineer"]`, `locations =
  ["United States"]`, `apify_max_items_per_run = 5`, `firecrawl_credits_per_run = 10`) run
  `linkedin-fetch` into a scratch queue; confirm `returned` ≤ 5, rows on the queue, state file
  written, `usd_charged` ≤ 0.0113.
- [ ] Run it again immediately; confirm `window` is `r86400` and `duplicate` > 0 or `returned` 0.
- [ ] Run `firecrawl-search --limit 2` twice then `firecrawl-scrape` once with the same
  `--run-state`; confirm `credits_spent_run` grows and a third search that would pass 10 is
  refused with `FirecrawlBudgetError`.
- [ ] Record the outputs (no keys) and total spend in the ledger.
- [ ] Live LinkedIn rows land on the queue with canonical `jobUrl` and full description
- [ ] Second run dedupes
- [ ] Firecrawl budget refusal observed live
- [ ] Total spend recorded in the ledger
- [ ] No placeholder/TODO comments in new code

## Phase log

| Phase | Status | Commit |
|---|---|---|

## Utang terbuka

(kosong)

## Log
- 2026-09-22 plan ditulis — NEXT: Phase A

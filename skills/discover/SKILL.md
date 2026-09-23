---
name: discover
description: Find roles from job boards, direct ATS APIs (Greenhouse/Lever/Ashby), and LinkedIn through Apify; normalise and append them to the local work queue. Never writes to jobsync. Invoked as /gaspol-jobhunter:discover.
---

# /gaspol-jobhunter:discover

Finds candidate roles and appends normalised rows to the local queue at
`.jobhunter/queue/jobs.jsonl`. This skill only writes to the local queue; it
never calls a jobsync MCP tool. `/gaspol-jobhunter:promote` is the only skill in
this plugin permitted to write to jobsync.

## Inputs

- `.jobhunter/config.toml`, read with `config-show` (see the commands below). If it is missing,
  this skill stops with the same named error every skill but `profile` uses
  (`config.ConfigMissingError`) and tells the user to run
  `/gaspol-jobhunter:profile` first.
- `targets.companies` — ATS slugs to poll directly.
- `targets.geo` — the geographies to search boards for.
- `[linkedin] keywords` / `locations` / `work_types` — search terms for the Apify LinkedIn actor.
- `budgets.firecrawl_credits_per_run` — the hard ceiling for board search/scrape this run.
- `budgets.apify_max_items_per_run` — the hard ceiling for LinkedIn postings this run; `0` turns
  LinkedIn off for the run.

## Keys

`APIFY_TOKEN` and `FIRECRAWL_API_KEY` live in a `.env` file at the project root, never in
`config.toml`. At the start of a run, call `keys-check` (see below). A missing key skips that
source — LinkedIn or board search/scrape — and the final report says which key is missing and
that it belongs in `.env`. No source falls back to another; a missing Apify key does not make
`discover` search boards instead of LinkedIn, and vice versa.

Warn once at the start of a run if `.env` is not git-ignored: run `git check-ignore -q .env` and
if it exits non-zero (not ignored), tell the user before doing anything else — an un-ignored
`.env` risks committing a live key.

## Scripts this skill calls

- `scripts/ats.py` — `ats.fetch(board, slug, dest)` streams a live
  Greenhouse/Lever/Ashby board to disk for each slug in `targets.companies`,
  then `ats.normalize_greenhouse(path)` / `ats.normalize_lever(path, company)`
  / `ats.normalize_ashby(path, company)` turns it into queue rows. `fetch`
  is the only network call; normalisation always runs against the file it
  wrote, never against data held only in conversation context — a single
  Greenhouse board can be several megabytes.
- `scripts/apify.py`, through the `linkedin-fetch` subcommand — runs the Apify actor
  `bebity/linkedin-jobs-scraper` against `[linkedin] keywords`/`locations`/`work_types`, enforces
  a per-run charge cap before starting, and normalises the result to queue rows in one step.
- `scripts/firecrawl.py`, through the `firecrawl-search` / `firecrawl-scrape` subcommands —
  board search and individual posting pages, over Firecrawl's REST API directly.
  Each call is checked against this run's own credit budget before it is made.
- `scripts/jobq.py` — `queue-append` appends the normalised
  rows to `.jobhunter/queue/jobs.jsonl`. Its own dedupe (by `jobq.row_key`)
  means calling `append_rows` again with rows already on the queue is safe;
  it reports duplicates, it does not double-write them.
- `scripts/jdstore.py`, through the `jd-write` subcommand — materializes
  `Data/<source>/<company>/<role>/JD.md` (plus a `.jobmeta.json` identity marker) for the rows
  this run collected. Idempotent: a folder already carrying this exact posting's identity is left
  untouched, so a rediscovered posting never clobbers in-progress or completed `tailor` output
  sitting in that same folder. A row with no `jobDescription` is reported in `errors`, never
  written as an empty file.

## Full posting text, not just a link

jobsync's match-result quality depends on the full posting text: roughly
150+ words gets a full match, shorter is stored but flagged *Provisional*,
and a title-only row is refused outright by `/gaspol-jobhunter:promote` later.
This skill therefore always captures the full description text at discovery
time — from `ats.normalize_*` for ATS boards, from `linkedin-fetch` for
LinkedIn (the actor returns the full `description` field), and from a scrape
of the posting page itself (not just the search-result snippet) for board
search results.

## LinkedIn

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" linkedin-fetch \
  --config .jobhunter/config.toml --queue .jobhunter/queue/jobs.jsonl \
  --dest /tmp/linkedin.json [--env-file .env]
```

Prints `{"window", "requested", "returned", "new", "duplicate", "skipped", "usd_charged",
"credit_remaining_usd"}`. `requested` is `budgets.apify_max_items_per_run`; `returned` is how
many postings the actor actually sent back — fewer than requested is not an error, LinkedIn may
simply not have that many matches.

**Window:** each successful run records when it finished. The next run automatically narrows
`publishedAt` to only-new postings (last 24 hours if the previous run was recent, last 7 days
otherwise, widening back out if there is no usable state) — repeated runs do not keep re-fetching
the same postings.

**Credit brake:** before starting a run, `linkedin-fetch` computes this run's charge cap and
checks it against the account's remaining Apify credit. If the remaining credit is below the
cap, it refuses with `apify.ApifyCreditError` and starts nothing — no partial charge.

**ToS note:** the actor reads public guest LinkedIn listings only; this skill never uses the
user's own LinkedIn account or credentials. LinkedIn's User Agreement §8.2 still prohibits
scraping its site; that risk is the user's to accept by configuring `[linkedin]` at all.

## Boards

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" firecrawl-search \
  --config .jobhunter/config.toml --run-state /tmp/fc-run-$(date +%s).json \
  --query "<query>" --limit 10 --dest /tmp/search.json [--env-file .env]

python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" firecrawl-scrape \
  --config .jobhunter/config.toml --run-state /tmp/fc-run-$(date +%s).json \
  --url "<posting url>" --dest /tmp/posting.json [--env-file .env]
```

Use a fresh `--run-state` path per run (e.g. `/tmp/fc-run-$(date +%s).json`) so each run's budget
starts clean; reusing a stale path from an earlier run carries its spend forward. Both print
`{"dest", "results"|"url", "credits_spent_run", "credits_budget", "credits_remaining_account"}`.
Turning board markdown into queue rows stays the model's job, then `queue-append` — exactly as
before. Every call is checked against `budgets.firecrawl_credits_per_run` before it is made; on
reaching that ceiling, `firecrawl.FirecrawlBudgetError` stops issuing new calls immediately and
reports how many credits were spent and how many remained unspent when it stopped. It never
serves a partial or cached result as if the sweep had completed. Rows already found and
normalised before the ceiling was reached are still appended to the queue — the run is real work
up to the point it stopped, not discarded.

`ats.fetch` calls do not spend Firecrawl credits (they are direct HTTP calls
to public ATS JSON endpoints) and are not counted against this budget.

## Deduplication

`jobq.append_rows` dedupes by `jobq.row_key(row)` — the normalised `jobUrl`
when present, else a hash of `company|jobTitle|location`. A posting
rediscovered on a later run, or found on two boards, is written once.

## Errors

Each is `{"error": "<class>", "message": "..."}` on stderr, exit 1. `apify.ApifyCreditError` /
`firecrawl.FirecrawlCreditError` / `firecrawl.FirecrawlBudgetError` stop that one source for the
run; the other sources continue.

- `apify.ApifyError`, `apify.ApifyTokenMissingError`, `apify.ApifyCreditError`
- `firecrawl.FirecrawlError`, `firecrawl.FirecrawlKeyMissingError`,
  `firecrawl.FirecrawlCreditError`, `firecrawl.FirecrawlBudgetError`
- Missing `[linkedin]` or empty `keywords`/`locations`, or an invalid `work_types` value →
  `config.ConfigError`.

## Output

Appends to `.jobhunter/queue/jobs.jsonl`, and materializes
`Data/<source>/<company>/<role>/JD.md` for the rows collected this run. Writes nothing to
jobsync and nothing under `.jobhunter/profile/`. The jobsync boundary is unchanged — `jd-write`
is a second **local** file write, never a network call.

Before finishing, this skill prints: which sources it queried (boards, ATS slugs, LinkedIn),
how many rows it wrote versus how many were skipped as duplicates, the `jd-write` counts
(`written` / `skipped_existing` / `errors`, naming each errored posting), and for LinkedIn the
window/returned/new/duplicate/USD spent/credit remaining, and for Firecrawl the credits
spent/budget/account balance.

## How to run the scripts

Every deterministic step in this skill is one command. `${CLAUDE_PLUGIN_ROOT}`
is set by Claude Code to this plugin's installed directory — never hardcode a
path. Reach every script through this command; the module and function names
that appear elsewhere in this file describe what a command wraps, and are not
an instruction to import anything.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" <subcommand> [options]
```

Run it with `--help`, or a subcommand with `--help`, to see the options. Every
subcommand prints JSON on stdout — except `keywords-report --markdown`, which
prints the markdown report itself so it can be redirected to a file. A refusal prints
`{"error": "<class>", "message": "..."}` on stderr and exits non-zero — report
it, do not retry it blindly.

### Commands this skill uses

```bash
# Check which provider keys are present, before spending anything
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" keys-check [--env-file .env]

# Fetch one ATS board and normalise it in one step
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" ats-fetch \
  --board greenhouse --slug <slug> --dest /tmp/<slug>.json

# lever and ashby need --company: their payloads carry no company name
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" ats-fetch \
  --board ashby --slug <slug> --company "<Company>" --dest /tmp/<slug>.json

# Append rows to the local queue (deduped by row_key)
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" queue-append \
  --queue .jobhunter/queue/jobs.jsonl --rows @/tmp/rows.json

# Materialize Data/<source>/<company>/<role>/JD.md for the same rows, after queue-append.
# queue-append reports counts only, so pass the same rows file. jd-write leaves a folder
# that already holds this posting untouched, and reports a posting whose stored JD.md
# differs in `errors` instead of overwriting it. It writes JD.md formatted (headings and
# bullets on their own lines, `Apply: <jobUrl>` on top (a row without an http(s) jobUrl is refused), images and link URLs dropped), refuses a listing page (5+ job
# links = not one JD, one JD = one posting) into `errors`, and reports link-heavy pages
# (site navigation came along) in `warnings`. A JD under 400 characters is refused too (truncated scrape or stub). Re-scrape any errored or warned posting from
# its single posting URL - never keep a whole careers page as a JD.
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" jd-write \
  --root Data --rows @/tmp/rows.json

# LinkedIn rows are queued inside linkedin-fetch and never pass through queue-append, so
# take them from the queue: queue-list prints {"count", "rows"}, which jd-write accepts.
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" queue-list \
  --queue .jobhunter/queue/jobs.jsonl > /tmp/queue.json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" jd-write \
  --root Data --rows @/tmp/queue.json
```

When a single posting cannot be normalised the rest of the board still comes
through, and the postings that did not make it are listed in the `skipped` key
of the JSON **on stdout** — each entry naming the posting and the field that
moved. stderr carries only counts, and only when there is something to count: a clean
`ats-fetch` writes one line, plus one more if any posting was skipped and (Ashby)
one if any posting was unlisted. Read `skipped`; a board that came
back short says so there, not in the log. Pass the rows through a file with
`@path` rather than inline — a board is megabytes.

---
name: discover
description: Find roles from job boards, direct ATS APIs (Greenhouse/Lever/Ashby), and watched career pages; normalise and append them to the local work queue. Never writes to jobsync. Invoked as /gaspol-jobhunter:discover.
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
- `budgets.firecrawl_credits_per_run` — the hard ceiling for this run.

## Scripts and MCP tools this skill calls

- `mcp__firecrawl__firecrawl_search` and `mcp__firecrawl__firecrawl_scrape` —
  find and read board listings and individual postings.
- `mcp__firecrawl__firecrawl_monitor_create` — register a watch on a
  configured career page so future runs get only new postings instead of
  re-sweeping the whole page.
- `scripts/ats.py` — `ats.fetch(board, slug, dest)` streams a live
  Greenhouse/Lever/Ashby board to disk for each slug in `targets.companies`,
  then `ats.normalize_greenhouse(path)` / `ats.normalize_lever(path, company)`
  / `ats.normalize_ashby(path, company)` turns it into queue rows. `fetch`
  is the only network call; normalisation always runs against the file it
  wrote, never against data held only in conversation context — a single
  Greenhouse board can be several megabytes.
- `scripts/jobq.py` — `queue-append` appends the normalised
  rows to `.jobhunter/queue/jobs.jsonl`. Its own dedupe (by `jobq.row_key`)
  means calling `append_rows` again with rows already on the queue is safe;
  it reports duplicates, it does not double-write them.

## Full posting text, not just a link

jobsync's match-result quality depends on the full posting text: roughly
150+ words gets a full match, shorter is stored but flagged *Provisional*,
and a title-only row is refused outright by `/gaspol-jobhunter:promote` later.
This skill therefore always captures the full description text at discovery
time — from `ats.normalize_*` for ATS boards, and from a scrape of the
posting page itself (not just the search-result snippet) for board search
results.

## Budget ceiling

Every `firecrawl_search` and `firecrawl_scrape` call spends Firecrawl
credits. This skill tracks its running spend against
`budgets.firecrawl_credits_per_run` and, on reaching that ceiling, **stops
issuing new Firecrawl calls immediately** and reports how many credits were
spent and how many remained unspent when it stopped. It never serves a
partial or cached result as if the sweep had completed. Rows already found
and normalised before the ceiling was reached are still appended to the
queue — the run is real work up to the point it stopped, not discarded.

`ats.fetch` calls do not spend Firecrawl credits (they are direct HTTP calls
to public ATS JSON endpoints) and are not counted against this budget.

## Deduplication

`jobq.append_rows` dedupes by `jobq.row_key(row)` — the normalised `jobUrl`
when present, else a hash of `company|jobTitle|location`. A posting
rediscovered by a monitor re-report, or found on two boards, is written once.

## Output

Appends to `.jobhunter/queue/jobs.jsonl`. Writes nothing to jobsync and
nothing under `.jobhunter/profile/`.

Before finishing, this skill prints: which sources it queried (boards, ATS
slugs, monitors), how many rows it wrote versus how many were skipped as
duplicates, and how many Firecrawl credits it spent against the configured
budget.

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
# Fetch one ATS board and normalise it in one step
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" ats-fetch \
  --board greenhouse --slug <slug> --dest /tmp/<slug>.json

# lever and ashby need --company: their payloads carry no company name
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" ats-fetch \
  --board ashby --slug <slug> --company "<Company>" --dest /tmp/<slug>.json

# Append rows to the local queue (deduped by row_key)
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" queue-append \
  --queue .jobhunter/queue/jobs.jsonl --rows @/tmp/rows.json
```

When a single posting cannot be normalised the rest of the board still comes
through, and the postings that did not make it are listed in the `skipped` key
of the JSON **on stdout** — each entry naming the posting and the field that
moved. stderr carries only counts, and only when there is something to count: a clean
`ats-fetch` writes one line, plus one more if any posting was skipped and (Ashby)
one if any posting was unlisted. Read `skipped`; a board that came
back short says so there, not in the log. Pass the rows through a file with
`@path` rather than inline — a board is megabytes.


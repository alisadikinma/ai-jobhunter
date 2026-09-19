---
name: promote
description: Push scored queue rows that clear the visa gate into jobsync via add_jobs_batch and save_match_results_batch, within the hourly MCP request budget. The only skill in this plugin permitted to call jobsync MCP tools. Invoked as /ai-jobhunter:promote.
---

# /ai-jobhunter:promote

Pushes rows from the local queue into a self-hosted jobsync instance over
its MCP server. **This is the only skill in this plugin permitted to call a
jobsync MCP tool.** `/ai-jobhunter:discover` and `/ai-jobhunter:score` only
ever touch the local queue file.

## Inputs

- `.jobhunter/config.toml`, read with `config-show` (see the commands below). If missing, this
  skill stops with `config.ConfigMissingError` and tells the user to run
  `/ai-jobhunter:profile` first.
- `budgets.jobsync_requests_per_run` — this run's own ceiling, itself always
  clamped to jobsync's hard hourly limit of 60 MCP requests (see
  `promote.MAX_REQUESTS_PER_HOUR`).
- `.jobhunter/queue/jobs.jsonl`, read with `queue-list` (see the commands below). Only rows
  carrying a `fit_score` (i.e. already run through `/ai-jobhunter:score`),
  with `work_authorization != "closed"`, and **not already promoted** are
  eligible. Read them with `queue-list --unscored`'s counterpart
  `queue-list --unpromoted`: a row already in jobsync costs two requests to
  re-upsert against a ceiling of sixty an hour, so re-sending old rows is
  how a run spends its whole budget before reaching a new posting.
  Everything else is
  left on the queue untouched.

## Scripts this skill calls

- `scripts/promote.py` — `promote.to_add_job(row)`, `promote.to_match_text(row)`,
  `promote.build_tags(row)`, `promote.chunk(rows, size=10)`,
  `promote.plan_budget(rows, limit)`. This module builds and validates every
  payload; it makes no MCP call itself (enforced by its own AST-based
  no-network-import test).

## MCP tools this skill calls

- `add_jobs_batch` (max 10 items per call) for the eligible rows, chunked
  with `promote.chunk`. Every payload from `promote.to_add_job` sets
  `upsert: true`. **`find_job` is never called** — `upsert: true` on
  `add_job`/`add_jobs_batch` makes it unnecessary, and calling it anyway
  would double the request cost for no benefit.
- `save_match_results_batch`, once `add_jobs_batch` has returned the ids
  jobsync assigned, using `promote.to_match_text(row)` for each `matchText`.

`review_resume` and `save_resume_review` are **not used** by this skill or
this plugin. Their schema requires a SCORES line carrying an
`ats=<0-100>` number, and per spec §6 this plugin does not claim an ATS
score anywhere — `/ai-jobhunter:tailor`'s keyword-overlap report explicitly
says it is not one. Using either tool would contradict that decision, so
they are out of scope for good, not just unimplemented yet.

## Request budget — 60 per hour, two requests per job

jobsync enforces **60 MCP requests per hour, across every tool and every
token**, and a batch call costs **one request per item**, not one request
per call. Promoting one job costs two requests regardless of batching: one
for its `add_job`/`add_jobs_batch` item, one for its
`save_match_result`/`save_match_results_batch` item.

Before calling anything, this skill runs
`promote.plan_budget(rows, limit)` to get `(sending, waiting,
requests_needed)`, and prints that plan before spending a single request.
When `waiting > 0`, the run **stops cleanly at the ceiling** rather than
retrying against a limit that only resets hourly: it reports exactly how
many rows are still waiting and leaves them on the queue, unpromoted, for
the next run.

## Refusal conditions

- **jobsync MCP unreachable** — this skill refuses to run at all and prints
  the setup steps (start jobsync with `docker compose up -d`, create an
  account at its local URL, generate a token under Settings → MCP Access,
  and configure the MCP connection) rather than silently writing nothing or
  writing to a substitute tracker.
- **A row with no `fit_score`** — `promote.to_add_job` / `promote.to_match_text`
  raise `promote.ScoreMissingError` for it; this skill reports the row as
  skipped and tells the user to run `/ai-jobhunter:score` first, rather than
  promoting an unscored row.
- **A row with `work_authorization == "closed"`** — `promote.py` raises
  `promote.AuthorizationClosedError` for it; this row is never sent to
  jobsync, by design (spec §5's visa gate).
- **A title-only row** — a row whose posting text is missing, under 10
  characters, or the literal `"N/A"` the normaliser writes for such a
  posting. `promote.py` raises `promote.TitleOnlyError`. jobsync needs the
  posting text to produce a match, so storing one would spend two requests on
  a job that can never carry a score. Report it and tell the user to re-run
  `/ai-jobhunter:discover` for the full posting.

## Provisional matches

A posting of roughly 150 words or more gets a full match from jobsync. A
shorter one is still stored, but jobsync flags the match **Provisional**.
`promote.match_quality(row)` returns `"full"` or `"provisional"`, and
`promote.to_match_text` adds a line naming it when the posting is short.

Say so in the run summary. Without it, a low score on a thin posting reads as
a poor fit rather than as a posting nobody bothered to write out.

## Output

Writes to jobsync only (no local file output). Rows successfully promoted
are marked in the local queue with `queue-update` with `{"<row_key>": {"promoted": true}}`, so a later run of this skill does not re-spend a
request re-promoting them. `jobq.append_rows` cannot do this — it would drop
the changed row as a duplicate by `row_key`.

Before finishing, this skill prints: how many rows were eligible, how many
were sent versus left waiting for budget reasons, how many were skipped for
missing score or closed authorization, and exactly how many MCP requests it
spent this run.

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
# Build the payloads that fit inside the request budget
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" promote-prepare \
  --rows @/tmp/scored.json --limit 50
```

It returns `batches` (never more than 10 items each), `prepared`, `refused`
(one entry per row with a named reason), `waiting`, and `requests_needed`.
Send each batch with `add_jobs_batch`, then `save_match_results_batch` using
the `match_text` beside each payload. Then mark them promoted:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" queue-update \
  --queue .jobhunter/queue/jobs.jsonl --updates @/tmp/promoted.json
```


---
name: score
description: Score every unscored row in the local queue against the candidate profile, writing fit_score, score_reasons, work_authorization, suggested_variant and skills back into the queue. Invoked as /ai-jobhunter:score.
---

# /ai-jobhunter:score

Scores every unscored row in the local queue against
`.jobhunter/profile/master-cv.md` and `.jobhunter/profile/variants.toml`, and
writes the result back into `.jobhunter/queue/jobs.jsonl` in place. This
skill only edits the local queue; it never writes to jobsync — that is
`/ai-jobhunter:promote`'s job, using the fields this skill writes.

## Inputs

- `.jobhunter/config.toml`, read with `config.load(path)`. If missing, this
  skill stops with `config.ConfigMissingError` and tells the user to run
  `/ai-jobhunter:profile` first.
- `.jobhunter/queue/jobs.jsonl`, read with `jobq.load(path)`;
  `jobq.iter_unscored(rows)` selects the rows this run actually scores (any
  row already carrying a `fit_score` is left untouched, so re-running this
  skill never re-scores what is already scored).
- `.jobhunter/profile/master-cv.md` and `.jobhunter/profile/variants.toml`.

## Scripts this skill calls

- `scripts/jobq.py` — `jobq.load`, `jobq.iter_unscored`, `jobq.update_rows`.
- `scripts/config.py` — `config.load`.
- No MCP tool is required for scoring itself; the judgement is made by the
  model reading the JD and the profile directly.

## The scored-row field contract (pinned)

After this skill runs, a scored row carries exactly these fields in addition
to whatever `jobq`/`ats.normalize_*` already put there.
`/ai-jobhunter:promote` reads these exact names — this skill must write
these exact names, nothing renamed and nothing extra standing in for them:

| Field | Type | Notes |
|---|---|---|
| `fit_score` | int 0-100 | absent or `None` means unscored |
| `score_reasons` | dict | one entry per rubric dimension; the salary entry is **absent**, never `0`, when the posting states no salary |
| `work_authorization` | `"open"` / `"unclear"` / `"closed"` | see the gate below |
| `suggested_variant` | str | a key from the user's `variants.toml` |
| `skills` | ordered list of str | drives the skill tags `/ai-jobhunter:promote` builds; only the first 8 survive its tag cap |

## `work_authorization` — a gate, not a weighted dimension

This is a separate three-bucket judgement, scored before and independently
of `fit_score`:

- `open` — the posting states visa sponsorship, or the company states it
  hires globally.
- `unclear` — the default when the posting is silent on sponsorship (for
  example, a bare "US remote" with no statement either way).
- `closed` — US-citizens-only, a security-clearance requirement, or
  language equivalent to "must be authorized to work in the US without
  sponsorship". A `closed` row is not scored further for fit; it is
  surfaced to the user as blocked, and `/ai-jobhunter:promote` refuses to
  push it to jobsync at all.

Folding this into a single blended score would hide a strong role-fit match
behind an unresolved sponsorship question. Keeping it separate lets a
high-fit role stay visibly high-fit while still flagged.

## `fit_score` rubric — 0-100

| Dimension | Weight | Notes |
|---|---|---|
| Skill match | 40 | Overlap of JD requirements with the profile's skills and highlights. |
| Role fit | 25 | Seniority and scope. A junior req against a senior profile scores low. |
| Remote | 15 | remote > hybrid > onsite, unless the location matches a stated target in `targets.geo`. |
| Salary | 10 | **If the JD states no salary, this dimension is left empty and its weight is redistributed across the other four dimensions — it is never scored 0.** An unmeasured number must not be ranked as if it were a low one. |
| Company signal | 10 | Funded startup, known product, or a clear engineering brand, over an anonymous agency posting. |

`score_reasons` records the reasoning for each dimension that was scored, so
the number is auditable rather than a bare score nobody can check. When the
salary dimension is left empty per the rule above, `score_reasons` has no
`salary` key at all — not a `salary` key holding `0` or an empty string.

## Variant classification is judgement, not keyword matching

`suggested_variant` is chosen by reading each variant's prose description
and its 2-3 example job descriptions in `.jobhunter/profile/variants.toml`,
and judging which variant the posting best matches as a whole. Any keyword
list attached to a variant is a hint fed into that judgement — never the
decider on its own. A posting can use none of a variant's listed keywords
and still be the right match, and a posting can use several of them and
still be the wrong one; keyword lists in this domain rot within months.

## Output

Rewrites `.jobhunter/queue/jobs.jsonl` in place via
`jobq.update_rows(path, {jobq.row_key(row): fields})`, which merges the
fields above into each matching row and renames a temporary file over the
original, so an interrupted run leaves the old queue intact. Do NOT use
`jobq.append_rows` for this: it would see the scored row as a duplicate of
the unscored one by `row_key` and drop it. `update_rows` returns
`(updated, unmatched)` — report both.

The fields written to each row this run scored are those five, and no others.

Before finishing, this skill prints: how many rows it read, how many were
already scored and skipped, how many it scored this run, how many landed in
each `work_authorization` bucket, and how many MCP requests it spent (none,
for this skill — scoring makes no jobsync call).

## How to run the scripts

Every deterministic step in this skill is one command. `${CLAUDE_PLUGIN_ROOT}`
is set by Claude Code to this plugin's installed directory — never hardcode a
path, and never import the modules directly.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" <subcommand> [options]
```

Run it with `--help`, or a subcommand with `--help`, to see the options. Every
subcommand prints JSON on stdout. A refusal prints
`{"error": "<class>", "message": "..."}` on stderr and exits non-zero — report
it, do not retry it blindly.

### Commands this skill uses

```bash
# Read the rows that still need scoring
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" queue-list \
  --queue .jobhunter/queue/jobs.jsonl --unscored

# Write the scores back, keyed by row_key
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" queue-update \
  --queue .jobhunter/queue/jobs.jsonl --updates @/tmp/scores.json
```

`/tmp/scores.json` is `{"<row_key>": {"fit_score": 88, "score_reasons": {...},
"work_authorization": "unclear", "suggested_variant": "genai_agents",
"skills": [...]}}`. Each row's `row_key` comes back with it from `queue-list`,
or from `queue-key --row @row.json`. `queue-update` returns
`{"updated": N, "unmatched": [...]}` — report both.


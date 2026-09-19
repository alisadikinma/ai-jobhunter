# ai-jobhunter

Generic, public Claude Code plugin for an end-to-end job-hunting pipeline:
discovery → scoring → per-JD CV/cover-letter tailoring → outreach, with tracking
delegated to a self-hosted jobsync instance over MCP.

Nothing candidate-specific is bundled. Profile, variants, target companies and
budgets all arrive at runtime through `.jobhunter/` in the user's own project.

## Hard rules

- **Never auto-applies.** No code path submits a form. Outreach writes drafts only —
  there is no send path.
- **`profile_sources.projects` is an allow-list, never a deny-list.** Only named
  directories are read; the root is never scanned. Seven bypasses were found and
  closed during AJOB-1, plus two fail-opens where the guard reported clean without
  having inspected anything. Treat any change here as security-relevant.
- **Nothing candidate-specific ships under `skills/`.** Enforced by `tests/test_manifest.py`.
- **Every CV and cover letter is written against the specific job description.**
  There is no one fixed CV.
- **`render-docx` refuses rather than warns.** Markdown still carrying
  `[verifikasi]` or `[Assumption]` produces no file at all. `--allow-unverified`
  is the user's per-run decision, never a default and never the skill's.

## Stack

Python 3 **standard library only** — no pip, no pytest, no PyYAML. Tests are
`unittest`; config is TOML via `tomllib`.

```bash
python3 -m unittest discover -s tests -t .   # unit  (450 tests)
python3 -m compileall -q scripts tests       # static
```

## The one entrypoint

Skills are prose; prose naming a Python function is not a way to call one. Every
skill runs exactly:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" <subcommand> [options]
```

Subcommands: `config-show`, `ats-fetch`, `ats-normalize`, `queue-append`,
`queue-list`, `queue-update`, `queue-key`, `keywords-report`, `promote-prepare`,
`render-docx`.

Large payloads arrive as `--rows @path` / `--updates @path`. Every subcommand
prints one JSON document on stdout — except `keywords-report --markdown`, which
prints the report. Logging goes to stderr. A refusal is
`{"error": "<class>", "message": "..."}` on stderr, exit 1, never a traceback.

## Layout

| Path | What it holds |
| --- | --- |
| `scripts/jobhunter.py` | the CLI every skill invokes; one `argparse`, ten subcommands |
| `scripts/config.py` | TOML loader + `resolve_profile_sources`; owns the allow-list |
| `scripts/jobq.py` | local JSONL queue — `load`, `append_rows`, `row_key`, `iter_unscored`, `iter_unpromoted`, `update_rows` |
| `scripts/ats.py` | `fetch` (the only network call, GET) + `normalize_{greenhouse,lever,ashby}` |
| `scripts/keywords.py` | JD-vs-CV overlap report. **Not an ATS score** |
| `scripts/promote.py` | jobsync payload building and request budget. No network imports |
| `scripts/docx.py` | markdown → ATS-readable `.docx`. Hand-written OOXML, five parts, `zipfile` only |
| `skills/{profile,discover,score,promote,tailor,outreach}/` | the six commands |
| `templates/config.toml` | the config example; byte-identical to spec §4 and the plan's copy, guarded by a test |
| `docs/evals/` | judgement evals for the non-deterministic steps, plus 7 real JD fixtures |

## Contracts worth knowing

**Scored row** (what `score` writes and `promote` reads): `fit_score` int 0-100,
`score_reasons` dict, `work_authorization` ∈ `open`/`unclear`/`closed`,
`suggested_variant`, `skills` ordered list. Queue rows use **camelCase** —
`jobTitle`, `jobUrl`, `jobDescription`, `workplaceType`.

**Scoring is two numbers, not one.** `fit_score` 0-100 (skill 40 / role 25 /
remote 15 / salary 10 / company 10) plus a separate work-authorization gate.
Salary is left empty when unstated, never 0, and its weight is redistributed.
80-100 `strong`, 65-79 `good`, 50-64 `partial`, 0-49 `weak`.

**Precedence tiers** are exactly five, each reading one config field:
`local-primary`, `local`, `project`, `linkedin-pdf`, `site`. An unknown tier
raises `PrecedenceError` rather than resolving to zero sources.

**jobsync MCP:** 9 tools, all writes, no list/read tool, 60 requests/hour.
A batch costs 1 request per item; `add_jobs_batch` takes at most 10; promoting
one job costs 2 requests.

**Error classes** (SKILL.md prose quotes these verbatim — renaming one makes six
files lie): `config.{ConfigError, ConfigMissingError, ProjectSourceError,
PrecedenceError, BudgetTypeError, SalaryTypeError}`, `ats.{AtsError,
MissingFieldError}`, `keywords.KeywordsError`, `docx.{DocxError, UnverifiedClaimError,
EmptyDocumentError, DestinationError}`, `promote.{PromoteError,
ScoreMissingError, AuthorizationClosedError, TitleOnlyError, WorkplaceTypeError,
FieldMissingError}`.

## Debugging checklist

Every defect that mattered in AJOB-1 surfaced by **running** the code against real
data, never by reading it. Four things that were green and wrong:

- A test asserting a token that the tokenizer never produced, so `.NET` still
  collapsed to `net`.
- A guard parsing skill docs line-by-line while every real command block uses
  backslash continuation — it checked 0 of 18 flags.
- `_Rows` returned only when something was skipped, so reverting it broke every
  clean board while 244 tests stayed green.
- `os.walk` with the default `onerror=None`, which discards `OSError` and lets the
  allow-list report clean on a subtree it never inspected.

So: when you add a guard, **mutate the thing it guards and watch it fail.** When
you change a count or a claim, measure it — twice in this ticket a wrong number
was replaced with another wrong number.

## gaspol Ticket Counter

Prefix: AJOB
Last ticket: AJOB-2

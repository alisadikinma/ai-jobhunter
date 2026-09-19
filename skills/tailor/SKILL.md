---
name: tailor
description: Write a CV, cover letter and keyword-coverage report for one specific job description. Reading the JD is mandatory; master-cv.md is never sent as-is. Invoked as /ai-jobhunter:tailor <queue-row-or-url>.
---

# /ai-jobhunter:tailor

Produces one document set — a CV, a cover letter, and a keyword-coverage
report — written for **one specific job description**. It never emits a
generic document.

## Inputs

- `.jobhunter/config.toml`, read with `config-show` (see the commands below). If missing, this
  skill stops with `config.ConfigMissingError` and tells the user to run
  `/ai-jobhunter:profile` first.
- The target job's full description text — from the matching row in
  `.jobhunter/queue/jobs.jsonl`, or scraped fresh with
  `mcp__firecrawl__firecrawl_scrape` if the user points this skill at a URL
  not already in the queue.
- `.jobhunter/profile/master-cv.md` and `.jobhunter/profile/variants.toml`.

## Reading the job description is mandatory

This skill MUST read the target job description in full before writing
anything. There is no code path in this skill that produces a CV or cover
letter without first reading the specific JD it is meant for. A run that
cannot obtain the JD text (URL unreachable, row has no `jobDescription`)
stops and reports that, rather than falling back to a generic document.

## `master-cv.md` is a source of raw material, never sent as-is

`.jobhunter/profile/master-cv.md` is the compiled superset of everything the
candidate has ever claimed, ordered for nobody in particular. **It is never
sent as-is** — not as the CV, not embedded unedited into the cover letter.
Every run of this skill re-selects, reorders and rewords evidence from
`master-cv.md` specifically for the JD it just read. There is no output path
that copies `master-cv.md` through unchanged.

## Scripts this skill calls

- `scripts/keywords.py` — `keywords-report` to compute
  which JD terms the drafted CV covers and which it misses, then
  `keywords.render(report)` to produce `keyword-report.md`'s body.
- `scripts/config.py` — `config.load`.

## Selection rules

- Reorder and reword bullets from `master-cv.md` toward the language and
  requirements the JD actually states; do not invent new bullets.
- Prefer bullets carrying a quantified metric when several are otherwise
  equally relevant.
- **Never invent an employer, a date, or a metric absent from
  `master-cv.md`.** Every fact in the output must trace back to a bullet
  already present in the compiled profile. A claim `master-cv.md` carries as
  `verified: false` — inherited from `/ai-jobhunter:profile`'s extraction
  pass — is never rendered here either; that suppression rule is not
  specific to the master CV, it applies to every outward document this
  plugin writes.
- Choose the role variant (from `.jobhunter/profile/variants.toml`) whose
  prose description and example JDs best match this specific posting, the
  same judgement-over-keywords approach `/ai-jobhunter:score` uses, and let
  that variant's framing (not a hardcoded template) shape the summary and
  section ordering.

## Output — `.jobhunter/applications/<slug>/`

- `cv.md` — reordered, reworded, evidence selected for this JD.
- `cover-letter.md` — likewise written for this JD, not a template filled
  with placeholders.
- `cv.docx` and `cover-letter.docx` — built from the two markdown files by
  `render-docx`. Nobody can attach a `.md` to a Workday form and no ATS
  parses one, so the markdown is the working copy and the `.docx` is what
  gets sent.
- `keyword-report.md` — built from `keywords-report --markdown`.
  Its heading states plainly that this is a **keyword overlap report, not an
  ATS score**: no local computation can honestly predict what any ATS
  vendor's own parser would score, since they parse differently from each
  other.

`<slug>` is derived from the company and job title, kept stable across
re-runs against the same posting so a second tailor run updates the same
directory instead of scattering duplicates.

Before finishing, this skill prints: which JD it read (title, company,
source), how many bullets it selected from `master-cv.md`, how many JD terms
were covered versus missing, and which files it wrote.

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
# Keyword overlap between this job description and the CV
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" keywords-report \
  --jd /tmp/jd.txt --cv .jobhunter/applications/<slug>/cv.md \
  --markdown > .jobhunter/applications/<slug>/keyword-report.md
```

The lists are the ranked head, not everything — a real posting yields hundreds
of terms. `--top N` changes the cut; the heading always states the full count
so a truncated report never reads as complete.

```bash
# Render the tailored CV as a .docx an ATS can read
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" render-docx \
  --in .jobhunter/applications/<slug>/cv.md \
  --out .jobhunter/applications/<slug>/cv.docx
```

Run it once per document — the cover letter is a second run with
`--in cover-letter.md --out cover-letter.docx`.

The `.docx` is deliberately plain: single column, no tables, no images, no
header or footer content, Calibri throughout. Every one of those is a
construct a resume parser either drops or scrambles, and a CV that looks
beautiful and parses into empty fields has failed at its only job. Tables,
images, links and nested bullets in the markdown are flattened
automatically. A table becomes one bullet per row, every cell keeping its own
header: `| Skill | Years |` with `| Python | 8 |` reads `Skill: Python — Years:
8`, so a parser never meets a number with nothing saying what it measures.
Each change is reported on stderr as `render-docx: line N: ...` and in the
`notes` array on stdout. Report what changed — do not re-render to try to
avoid it.

### When `render-docx` refuses

If the markdown still carries `[verifikasi]` or `[Assumption]`, the command
writes **no file at all** and exits 1 with:

```json
{
  "error": "UnverifiedClaimError",
  "message": "refused to render: 1 unverified claim(s) still in the markdown. ..."
}
```

That is the correct outcome, not a bug to work around. The message names the
file, the line number and the claim itself. Show it to the user and ask them
to verify the claim and remove the marker.

`render-docx --allow-unverified` exists, and it is **the user's decision, per
run, never this skill's**. Do not pass it because a render failed, do not suggest it as
the fix, and never put it in a script or a config file. It is an opt-in
escape from a safety gate on a document that goes out under the user's name.

When it is used, the claim is rendered but the marker itself is removed from
the document — the override sends the claim, it does not print the user's
private note to themselves onto a page an employer reads. `notes` reports how
many markers were removed, so the override is never silent. Report that count.

The gate matches the marker however it is written: carrying its reason
(`[Assumption: figure from memory]`), wrapped in emphasis, spelled with html
entities, split by an invisible character, or broken across a line wrap.
Every one of those spellings once got a claim into a rendered CV while the
check reported clean, so each is now pinned by a test.

The other refusals: `EmptyDocumentError` when the markdown holds no headings,
paragraphs or bullets, and `DestinationError` when the output directory does
not exist, is not writable, is the source markdown itself, or when `--out`
does not end in `.docx` — a typo there would overwrite whatever it named.


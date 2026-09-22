---
name: tailor
description: Write a CV, cover letter and keyword-coverage report for one specific job description, only after the candidate has agreed a requirements map row by row. Reading the JD is mandatory; master-cv.md is never sent as-is. Invoked as /gaspol-jobhunter:tailor <queue-row-or-url-or-pasted-JD>.
---

# /gaspol-jobhunter:tailor

Produces one document set — a CV, a cover letter, and a keyword-coverage
report — written for **one specific job description**. It never emits a
generic document, and it never writes the CV or cover letter until the
candidate has agreed, row by row, which JD requirement is answered by which
evidence.

## Inputs

- `.jobhunter/config.toml`, read with `config-show` (see the commands below). If missing, this
  skill stops with `config.ConfigMissingError` and tells the user to run
  `/gaspol-jobhunter:profile` first.
- The target job's full description text, from one of three places:
  - the matching row in `.jobhunter/queue/jobs.jsonl`,
  - scraped fresh with `mcp__firecrawl__firecrawl_scrape` if the user points
    this skill at a URL not already in the queue, or
  - **pasted directly into the conversation.** Pasted text is written
    verbatim to `.jobhunter/applications/<slug>/jd.md` — that file is what
    `keywords-report --jd` reads later. `<slug>` comes from the company and
    job title stated in the JD; if either cannot be found in the pasted
    text, this skill asks the user for it — it never guesses a company or
    title.
- `.jobhunter/profile/master-cv.md` and `.jobhunter/profile/variants.toml`.

## Reading the job description is mandatory

This skill MUST read the target job description in full before writing
anything. There is no code path in this skill that produces a CV or cover
letter without first reading the specific JD it is meant for. A run that
cannot obtain the JD text (URL unreachable, row has no `jobDescription`,
empty paste) stops and reports that, rather than falling back to a generic
document.

## `master-cv.md` is a source of raw material, never sent as-is

`.jobhunter/profile/master-cv.md` is the compiled superset of everything the
candidate has ever claimed, ordered for nobody in particular. **It is never
sent as-is** — not as the CV, not embedded unedited into the cover letter.
Every run of this skill re-selects, reorders and rewords evidence from
`master-cv.md` specifically for the JD it just read; it does not invent new
bullets. There is no output path that copies `master-cv.md` through
unchanged.

## Location check

A JD read from the queue has already passed through `/gaspol-jobhunter:score`,
which checks geography. A **pasted** JD bypasses that check, so `tailor`
itself reads any geographic restriction stated in the JD (e.g. "within the
United States", "must reside in the same country as the office") and warns
the user when it conflicts with the candidate's stated location. This is a
warning, never a block — the user decides whether to continue.

## Portal detection

Read the application portal from the JD's URL host, right after the location
check:

- `myworkdayjobs.com` or `myworkdaysite.com` → Workday
- `taleo.net` → Taleo
- `icims.com` → iCIMS
- any other host → `other`

A **pasted** JD carries no URL. Ask the user which portal this posting uses —
never guess one from the company name or the JD text. "I don't know" is a
valid answer and resolves to `other`.

An **enterprise** portal (Workday, Taleo, or iCIMS) means `render-docx` runs
for both documents, alongside the PDF, in the Render step below — DOCX parses
most reliably in those portals, where a text PDF loses more structure. A
non-enterprise portal (Greenhouse, Lever, Ashby, email, `other`) stays
PDF-only.

## Scripts this skill calls

- `scripts/keywords.py` — `keywords-report` to compute
  which JD terms the drafted CV covers and which it misses, then
  `keywords.render(report)` to produce `keyword-report.md`'s body.
- `scripts/config.py` — `config.load`.
- `scripts/templates.py`, via `template-check` — validates `cv.md` against
  the chosen `templates/cv/<name>.md` structure and `cover-letter.md` against
  `templates/cover-letter.md`'s fixed format and word-count band.
- `scripts/pdf.py`, via `render-pdf` — renders `cv.md` and `cover-letter.md`
  to PDF once both are written.
- `scripts/docx.py`, via `render-docx` — renders both to `.docx` too, only
  when the detected portal is an enterprise one (Workday, Taleo, iCIMS).

## Requirements map

Before writing anything, this skill builds
`.jobhunter/applications/<slug>/requirements-map.md`: every required and
preferred requirement the JD states, each marked against `master-cv.md`:

```markdown
# Requirements map — <Job title>, <Company>

approved: YYYY-MM-DD        <!-- present only after the agreement gate passes -->

| # | Requirement (JD wording) | Kind | Status | Evidence (master-cv.md) | Agreed |
|---|---|---|---|---|---|
| 1 | 3+ years in process automation | required | match | "<quoted bullet>" | yes |
| 2 | Azure cloud experience | required | gap | — | yes (gap) |
```

`Kind` is `required` or `preferred`. `Status` is `match` (a `master-cv.md`
bullet evidences it directly, quoted in full), `partial` (the nearest
evidence is quoted and what is missing is stated), or `gap` (no evidence
exists). Rows are written in the order the JD states them.

## Agreement gate (blocking)

The map is walked with the user **group by group**, using AskUserQuestion —
not dumped as one long list. For each row the user can:

- accept the pairing as written,
- reject the pairing (the row goes back to `gap` or is reworded),
- add new evidence the map missed, or
- confirm a `gap` as a real gap (nothing to add).

Evidence the user adds during this walk is appended to `master-cv.md` with
source `user, <YYYY-MM-DD>`, so every claim in the compiled profile stays
traceable to where it came from, the same rule `/gaspol-jobhunter:profile`
enforces for every other source.

The same gate also settles three more things, asked alongside the row walk,
not as a separate interruption:

- **CV template.** This skill proposes one name from `templates/cv/` —
  `hybrid`, `technical`, or `leadership` — from the JD's title seniority and
  whether it leads with leadership scope, engineering depth, or a mix, and
  states the reason in one sentence. The user confirms it or switches to a
  different template name.
- **Cover-letter level.** `entry` (200-250 words), `mid` (250-400 words), or
  `executive` (400-450 words) — the user picks one.
- **An optional personal detail** — a hiring-manager name, a referral, or a
  specific reason for this company. If the user gives none, the letter's
  salutation is `"<Team> Hiring Team"` and its company-specific line uses
  only facts already in the JD text: **nothing is invented.**

**No cv.md or cover-letter.md is written until every row is agreed.**
Once the walk finishes, this skill writes `approved: <YYYY-MM-DD>` at the
top of `requirements-map.md`, together with the three lines it just settled:

```markdown
template: <hybrid|technical|leadership>
letter-level: <entry|mid|executive>
portal: <workday|taleo|icims|other>
approved: <YYYY-MM-DD>
```

A map without an `approved:` line means the gate has
not passed, and no downstream step — write, template check, keyword loop, or
render — may run.

## Write

`cv.md` is written on the approved template's section skeleton — its
canonical headings, in its order, from `templates/cv/<name>.md`
(`hybrid`, `technical`, or `leadership`, whichever the agreement gate
settled). `cover-letter.md` is written on `templates/cover-letter.md`'s
fixed format: opening (role, company, top evidence), one SCAR proof
paragraph, a fit paragraph, and a close — the same P1-P4 shape the format
file spells out in full.

`cv.md` and `cover-letter.md` are written from **approved rows only**. JD
wording is mirrored only where an approved row evidences it. A row marked
`gap` never appears in either document — not the requirement's own wording,
not a paraphrase of it. If the user rejects most pairings and the map ends
up mostly `gap`, the CV still gets written, but it carries only evidence
that does not depend on this JD's specific asks, and this skill says so
plainly in its final report rather than quietly shipping a thin document.

Existing rules still stand: never invent an employer, a date, or a metric
absent from `master-cv.md`; a claim `master-cv.md` carries as
`verified: false` is never rendered into any outward document — not
`master-cv.md`, not a tailored CV, not a cover letter. This suppression rule
is not specific to the master CV; it applies to every outward document this
plugin writes. Prefer bullets carrying a quantified metric when several are
otherwise equally relevant.

Choose the role variant (from `.jobhunter/profile/variants.toml`) whose
prose description and example JDs best match this specific posting, the
same judgement-over-keywords approach `/gaspol-jobhunter:score` uses, and let
that variant's framing (not a hardcoded template) shape the summary and
section ordering.

## Template check

Before the keyword loop or any render, both drafted files are checked with
`template-check` (Commands below). Every finding is a piece of text to fix —
not a refusal — so this skill edits `cv.md` or `cover-letter.md` and
re-runs the check until it reports `"ok": true` for both. Nothing is
rendered while a check still carries findings.

## Keyword loop

Run `keywords-report` with `--jd` pointing at `jd.md` (pasted JDs) or the JD
source file (queue/URL JDs) against the drafted `cv.md`. For each term the
report lists as missing, add it to `cv.md` **only when an approved row
already evidences it** — this loop revises wording, it never introduces new
facts. At most 2 rounds. A term with no approved evidence backing it stays
listed as a gap in the final `keyword-report.md`, never added just to raise
the coverage count.

## Render

`render-pdf` twice — once for `cv.md`, once for `cover-letter.md` — after
both are written, both pass `template-check`, and the keyword loop is done.
When the detected portal is **enterprise** (Workday, Taleo, or iCIMS),
`render-docx` runs too, for both documents, right after the PDFs — the
reason is the same one Portal detection gives: DOCX parses most reliably in
those enterprise portals. A non-enterprise portal skips `render-docx`
entirely; only the PDFs are produced.

Output directory: `.jobhunter/applications/<slug>/`, holding `jd.md` (pasted
JD only), `requirements-map.md`, `cv.md`, `cover-letter.md`, `cv.pdf`,
`cover-letter.pdf`, `keyword-report.md`, plus `cv.docx` and
`cover-letter.docx` when the portal was enterprise.

`<slug>` is derived from the company and job title, kept stable across
re-runs against the same posting so a second tailor run updates the same
directory instead of scattering duplicates.

Before finishing, this skill prints: which JD it read (title, company,
source), the location warning if any, the requirements-map counts (match /
partial / gap), the approval date, the chosen template and letter level, the
detected portal, both `template-check` results, how many bullets it selected
from `master-cv.md`, how many JD terms were covered versus missing, and
which files it wrote.

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
  --jd .jobhunter/applications/<slug>/jd.md --cv .jobhunter/applications/<slug>/cv.md \
  --markdown > .jobhunter/applications/<slug>/keyword-report.md
```

`--jd` points at `jd.md` when the JD was pasted, or at the JD source file
when it came from the queue or a scrape. The lists are the ranked head, not
everything — a real posting yields hundreds of terms. `--top N` changes the
cut; the heading always states the full count so a truncated report never
reads as complete.

```bash
# Check the drafted CV against its chosen template
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" template-check \
  --cv .jobhunter/applications/<slug>/cv.md --template technical
```

```bash
# Check the drafted cover letter against the fixed format and word-count band
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" template-check \
  --letter .jobhunter/applications/<slug>/cover-letter.md --level mid \
  --company "<Company>" --role "<Job title>"
```

`--template` is one of `hybrid`, `technical`, or `leadership` — whichever the
agreement gate settled. `--level` is `entry`, `mid`, or `executive`.
`--company` and `--role` are checked against the letter's opening paragraph
only when given. Both commands print `{"kind", "template"|"level",
"findings": [...], "ok": bool}` on stdout, exit 0 either way — a non-empty
`findings` list is content to fix, per the Template check section above, not
a refusal.

```bash
# Render the tailored CV as a PDF
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" render-pdf \
  --in .jobhunter/applications/<slug>/cv.md \
  --out .jobhunter/applications/<slug>/cv.pdf \
  --page letter
```

Run it once per document — the cover letter is a second run with
`--in cover-letter.md --out cover-letter.pdf`. `--page` is `letter`
(default) or `a4` — e.g. `--page a4` for a JD restricted to one country
whose norm is A4.

The PDF is deliberately plain: single column, real selectable text, Helvetica
throughout, `WinAnsiEncoding` only. `render-pdf` shares its markdown gate
(`docx.prepare`) with the plugin's `.docx` renderer, so tables, images, links
and nested bullets in the markdown are flattened automatically before
rendering, the same way they are for `.docx`. A table becomes one bullet per
row, every cell keeping its own header: `| Skill | Years |` with `| Python | 8 |` reads
`Skill: Python — Years: 8`, so a parser never meets a number with nothing
saying what it measures. Images and links are flattened to plain text, and a
nested bullet is flattened to one level. Every one of those is a construct a
resume parser either drops or scrambles, and a CV that looks beautiful and
parses into empty fields has failed at its only job. A character outside
`WinAnsiEncoding` — most CJK text, emoji, an arrow glyph like `→` — is
refused rather than dropped or replaced with `?`; fix the text instead
(`→` becomes `-`), never pass a flag to force it through. Each change is
reported on stderr as `render-pdf: line N: ...` and in the `notes` array on
stdout. Report what changed — do not re-render to try to avoid it.

```bash
# Enterprise portals only (Workday, Taleo, iCIMS): render the same CV as .docx
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" render-docx \
  --in .jobhunter/applications/<slug>/cv.md \
  --out .jobhunter/applications/<slug>/cv.docx
```

Run it once per document here too — the cover letter is a second run with
`--in cover-letter.md --out cover-letter.docx`. It shares the same markdown
gate as `render-pdf`, so the same flattening and unverified-claim refusal
apply.

### When `render-pdf` refuses

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

`render-pdf --allow-unverified` exists, and it is **the user's decision, per
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

The other refusals: `EmptyDocumentError` when the markdown holds no
headings, paragraphs or bullets; `DestinationError` when the output
directory does not exist, is not writable, is the source markdown itself, or
when `--out` does not end in `.pdf`; and `UnsupportedCharacterError` when
the text carries a character outside `WinAnsiEncoding`, naming the line and
the codepoint responsible.

## Output — `.jobhunter/applications/<slug>/`

- `jd.md` — the pasted job description, verbatim (pasted-JD runs only).
- `requirements-map.md` — every JD requirement matched, partially matched,
  or marked a gap against `master-cv.md`, with `approved: YYYY-MM-DD` once
  the agreement gate has passed.
- `cv.md` — reordered, reworded, evidence selected for this JD, from
  approved rows only.
- `cover-letter.md` — likewise written for this JD, not a template filled
  with placeholders.
- `cv.pdf` and `cover-letter.pdf` — built from the two markdown files by
  `render-pdf`. Nobody can attach a `.md` to a Workday form and no ATS
  parses one, so the markdown is the working copy and the `.pdf` is what
  gets sent.
- `cv.docx` and `cover-letter.docx` — built by `render-docx`, only when the
  detected portal is enterprise (Workday, Taleo, iCIMS). Absent for every
  other portal.
- `keyword-report.md` — built from `keywords-report --markdown`.
  Its heading states plainly that this is a **keyword overlap report, not an
  ATS score**: no local computation can honestly predict what any ATS
  vendor's own parser would score, since they parse differently from each
  other.

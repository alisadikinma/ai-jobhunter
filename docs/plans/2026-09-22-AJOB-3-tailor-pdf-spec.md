**Ticket:** AJOB-3

# AJOB-3 — Tailor from a PDF master CV and a pasted JD, agree the match first, ship PDF

## Design

### 1. Goal

Three gaps in the current `profile` → `tailor` path, one ticket (same subsystem):

1. A master CV held as a **PDF** in any profile tier cannot be read — only the
   `linkedin-pdf` tier is routed to `mcp__xberg__extract_file`; `local-primary` /
   `local` are read with the native Read tool, which cannot parse PDF.
2. `tailor` accepts a queue row or a URL, never a **job description pasted** into
   the conversation.
3. Tailoring is not matched tightly enough to the JD, and nothing stops the skill
   from writing before the candidate agrees what evidence answers which
   requirement. Output must be **PDF only** (`cv.pdf`, `cover-letter.pdf`).

Out of scope: auto-applying (still no send/submit path), OCR of scanned PDFs
beyond what xberg already does, non-Latin scripts in the rendered PDF, removing
`render-docx` (it stays in the CLI; `tailor` stops calling it).

### 2. `profile` — PDF in any tier

Prose rule in `skills/profile/SKILL.md` Pass 1: **any source path ending in
`.pdf`, in any tier (`primary`, `local`, `linkedin_pdf`), is extracted with
`mcp__xberg__extract_file`**; everything else keeps its current reader. No Python
change: `config.py` already accepts any path. So `primary = "data/master-cv.pdf"`
makes a curated CV PDF the highest-precedence source, flowing through the existing
four passes into `master-cv.md`. The allow-list rules for `projects` are
untouched.

### 3. `tailor` — new flow

1. **Input.** Queue row, URL, or **pasted JD text**. Pasted text is written
   verbatim to `.jobhunter/applications/<slug>/jd.md`. `<slug>` comes from the
   company and title stated in the JD; if either cannot be found, the skill asks
   the user — it never guesses. That file is what `keywords-report --jd` reads.
2. **Location check.** A pasted JD bypasses `/ai-jobhunter:score`, so `tailor`
   itself reads any geographic restriction in the JD (e.g. "within the United
   States") and warns when it conflicts with the candidate's stated location.
   Warning, not a block — the user decides.
3. **Requirements map.** Write `.jobhunter/applications/<slug>/requirements-map.md`:
   every required and preferred requirement in the JD, each marked
   - `match` — quotes the `master-cv.md` bullet that evidences it,
   - `partial` — quotes the nearest evidence and says what is missing,
   - `gap` — no evidence.
4. **Agreement gate (blocking).** The map is walked with the user group by group
   via AskUserQuestion. Per row the user can accept, reject the pairing, add new
   evidence, or confirm the gap. Evidence the user adds is appended to
   `master-cv.md` with source `user, <YYYY-MM-DD>` so it stays traceable. **No
   `cv.md` or `cover-letter.md` is written until every row is agreed.** The final
   map carries `approved: <YYYY-MM-DD>` at the top; a map without that line means
   the gate has not passed.
5. **Write** `cv.md` and `cover-letter.md` from approved rows only. JD wording is
   mirrored only where an approved row evidences it. A `gap` never appears in
   either document, and existing rules stand: no invented employer, date or
   metric; `verified: false` claims never rendered.
6. **Keyword loop.** Run `keywords-report`; for each missing term that an approved
   row evidences, revise; at most 2 rounds. Terms without evidence stay listed as
   gaps in the report, never added.
7. **Render.** `render-pdf` for `cv.md` and `cover-letter.md`. Output directory
   holds: `jd.md` (pasted path only), `requirements-map.md`, `cv.md`,
   `cover-letter.md`, `cv.pdf`, `cover-letter.pdf`, `keyword-report.md`.

Before finishing, the skill prints what it already prints plus: map counts
(match / partial / gap), the approval date, and the location warning if any.

### 4. `render-pdf`

**Shared preparation.** Extract the pre-render stage of `docx.render` into
`docx.prepare(markdown, allow_unverified=False, source=None) -> (blocks, notes)`
— flatten, unverified-marker gate, marker stripping under `--allow-unverified`,
`parse_blocks`, empty-document check. `docx.render` and `pdf.render` both call
it. One gate, not two copies that can drift (KB precedent
`pdf-header-consolidation`; gate precedent
`title-unverified-claims-never-render-to-external-d`).

**`scripts/pdf.py`**, stdlib only:
- Hand-written PDF 1.4: catalog, pages tree, one content stream per page, font
  resources, xref table with exact byte offsets, trailer, `%%EOF`.
- Standard-14 fonts `Helvetica` and `Helvetica-Bold`, not embedded,
  `WinAnsiEncoding`. Real text, single column, top-to-bottom reading order.
- Line wrapping from Helvetica / Helvetica-Bold AFM advance widths stored as
  constants.
- `--page letter` (default) or `a4`; 0.75 in margins; H1 16 pt bold, H2 12 pt
  bold, body 10.5 pt; bullets `•`; automatic page breaks.
- Info dictionary `/Producer (ai-jobhunter)` only; `/Title` from the first
  heading at run time. Nothing candidate-specific in code.
- Atomic write: temp file in the destination directory, then `os.replace`.

**CLI** — subcommand 11, same shape as `render-docx`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" render-pdf \
  --in .jobhunter/applications/<slug>/cv.md \
  --out .jobhunter/applications/<slug>/cv.pdf [--page letter|a4] [--allow-unverified]
```

stdout: one JSON document (`path`, `pages`, `blocks`, `notes`); notes also on
stderr as `render-pdf: line N: ...`.

**Refusals** — no file written, exit 1, `{"error", "message"}` on stderr:
- `UnverifiedClaimError`, `EmptyDocumentError` — raised by `docx.prepare`, same
  classes, same messages.
- `DestinationError` — as for docx, but `--out` must end in `.pdf`.
- **New** `pdf.PdfError` (base) and `pdf.UnsupportedCharacterError` — a character
  outside WinAnsi (CJK, `→`, emoji). Message names the line number and the
  character. Never silently replaced with `?`. (`·`, `–`, `—`, `é` are in WinAnsi.)

`--allow-unverified` stays the user's per-run decision, never the skill's.

### 5. Data Integration Map

| Component | Data Source | Existing? | Notes |
|-----------|-------------|-----------|-------|
| Master CV PDF | xberg → `sources/` → `master-cv.md` | Partly (`linkedin-pdf` tier) | rule widened to every tier |
| Pasted JD | conversation → `applications/<slug>/jd.md` | New | slug asked, never guessed |
| Requirements map | JD + `master-cv.md` → `requirements-map.md` | New | `approved:` line = gate passed |
| User-added evidence | agreement gate → `master-cv.md` | New | source `user, <date>` |
| Keyword loop | `keywords-report` | Yes | max 2 rounds |
| Marker gate | `docx.prepare()` | Refactor of `docx.render` | shared by both renderers |
| PDF output | `pdf.py` via `render-pdf` | New | stdlib, WinAnsi only |

### 6. Testing

Tests first (`unittest`), each guard proven by mutating what it guards and
watching it fail.

- `pdf.py`: xref offsets match actual byte positions; `%%EOF`; content-stream text
  appears in document order; no wrapped line exceeds the text width; page break
  occurs; every refusal leaves no file (including no temp file).
- Gate parity: every marker spelling pinned in the docx tests (reason-carrying,
  emphasis, html entities, invisible characters, line-wrap split, code spans)
  is refused by `render-pdf` too.
- `docx.render` produces the same `word/document.xml` and the same `notes` before
  and after the `prepare()` extraction, on the existing fixtures and the real JD
  fixtures in `docs/evals/`.
- Skill prose: `tailor` names the agreement gate, `requirements-map.md`, the
  `approved:` line, the pasted-JD path and `render-pdf`, and no longer calls
  `render-docx`; `profile` states the any-tier `.pdf` → xberg rule; every CLI flag
  quoted in skill docs (including backslash-continued blocks) exists in argparse.
- `test_manifest.py` stays green: no candidate-specific data under `skills/`;
  fixtures are fictional.
- CLAUDE.md test count and subcommand list re-measured, not estimated.

**E2E (not committed):** `data/master-cv.pdf` + the City of Hope JD through the
full flow; extract `cv.pdf` back with xberg and confirm text is complete and in
order.

### 7. Hygiene

- Add `data/` to `.gitignore` — it holds a real candidate's CV.
- CLAUDE.md: subcommand list, layout row for `scripts/pdf.py`, error classes
  (`pdf.{PdfError, UnsupportedCharacterError}`), test count.

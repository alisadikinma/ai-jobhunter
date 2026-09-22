> **For Claude:** REQUIRED SKILL: Use gaspol-execute to implement this plan.
> **CRITICAL:** This plan specifies real integrations. During execution,
> NEVER substitute placeholders for real data sources without explicit
> user approval. If a data source doesn't exist yet, STOP and ask.
> **Progress ledger — HARD PER-PHASE GATE:** `.gaspol/progress/PROGRESS-AJOB-3.md` (created by `gaspol-plan` at plan-write time). After EACH phase and **BEFORE** starting the next, STOP and do BOTH: (a) tick that phase's `## Checklist` line, (b) append a `## Log` line ending with the handoff cursor. This is **blocking**, like a test gate: no next phase until both are written. **Never batch all updates at the end** — a crash mid-run must leave a truthful state, not a stale one. Update ONLY this file — never the shared `.gaspol/progress.md`.
> **Self-contained:** this plan is the COMPLETE spec. It must be executable by an agent with **no other context**. Every file path, contract, config key, and convention it needs is written here **verbatim**.

**Ticket:** AJOB-3
**Ledger:** .gaspol/progress/PROGRESS-AJOB-3.md
**Spec:** docs/plans/2026-09-22-AJOB-3-tailor-pdf-spec.md

## Goal

Close three gaps in the `profile` → `tailor` path of the ai-jobhunter plugin:
(1) a master CV held as a PDF in **any** profile tier is extracted with
`mcp__xberg__extract_file`; (2) `tailor` accepts a job description **pasted**
into the conversation; (3) `tailor` builds a requirements map (JD requirement →
master-CV evidence or gap), walks it with the user until every row is agreed,
only then writes, runs a bounded keyword loop, and ships **PDF only**
(`cv.pdf`, `cover-letter.pdf`) through a new stdlib `render-pdf` subcommand that
shares the existing unverified-claim gate with `render-docx`.

This reverses an AJOB-2 decision ("DOCX only, no PDF", 2026-09-19): Ali decided
on 2026-09-22 that tailored output is PDF only. `render-docx` stays in the CLI;
`tailor` stops calling it.

## Architecture Context

From `CLAUDE.md` (repo root) — rules that bind every phase:

- **Python 3 standard library only.** No pip, no pytest, no PyYAML, no
  reportlab. Tests are `unittest`. Config is TOML via `tomllib`.
- **One entrypoint.** Skills are prose; every skill runs exactly
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" <subcommand> [options]`.
  Every subcommand prints one JSON document on stdout; logging to stderr; a
  refusal is `{"error": "<class>", "message": "..."}` on stderr, exit 1, never a
  traceback (`scripts/jobhunter.py::main` already converts exceptions).
- **Never auto-applies.** No submit/send path is added.
- **Nothing candidate-specific ships under `skills/`** — enforced by
  `tests/test_manifest.py::TestNoCandidateSpecificContent`. No real names,
  employers, "City of Hope", or data from `data/` in `skills/`, `tests/`,
  `scripts/` or `docs/evals/`. Fixtures are fictional.
- **`render-docx` refuses rather than warns** on `[verifikasi]` / `[Assumption]`.
  `--allow-unverified` is the user's per-run decision, never a default and
  never the skill's. `render-pdf` inherits exactly this rule.
- **Error classes are quoted verbatim in SKILL.md prose** — renaming one makes
  files lie. Existing: `docx.{DocxError, UnverifiedClaimError,
  EmptyDocumentError, DestinationError}`. New in this ticket:
  `pdf.{PdfError, UnsupportedCharacterError}`.
- **Debugging checklist:** every guard added is proven by mutating what it
  guards and watching the test fail. Every count written into docs is measured,
  never estimated.

Existing code this plan reuses (read before touching):

- `scripts/docx.py::render(markdown, path, allow_unverified=False, source=None)`
  (line ~1127). Its body, in order: `label = source or os.path.basename(path) or
  "<markdown>"` → `unverified_findings(markdown)` → raise
  `UnverifiedClaimError(unverified, label)` unless allowed → `flatten(markdown)`
  returns `(flattened, notes)` → `parse_blocks(flattened)` → residual check on
  rendered block text joined with `"\n"` and with `""` → under
  `allow_unverified`, `_strip_markers(blocks)` + drop emptied blocks + two notes
  → `EmptyDocumentError` if no blocks → build OOXML payload → `DestinationError`
  if directory missing → `_write_archive` (mkstemp in dest dir, `os.replace`,
  `_remove_quietly` on failure).
- **Block contract** (`docx.parse_blocks`): list of dicts; `kind` ∈
  `heading` / `paragraph` / `bullet`; `text` str; `level` ∈ 1/2/3 on headings
  only. Empty blocks are never emitted.
- `docx.BULLET_GLYPH = "• "`; `docx.STYLES` maps `(kind, level)` →
  `(style_id, half_points, bold)`.
- `scripts/jobhunter.py::cmd_render_docx` (line ~194): refuses `--out` not
  ending `.docx` with `docx.DestinationError`, refuses `_same_file(input, out)`,
  reads input as UTF-8, calls `docx.render`, prints each note to stderr as
  `render-docx: <note>`, `_emit`s `{out, blocks, notes, bytes}`. Parser block
  at line ~364.
- `scripts/jobhunter.py::_same_file(source, destination)` — reuse as-is.
- `tests/test_manifest.py::_documented_commands()` collects every
  `jobhunter.py <subcommand>` and its flags from skill docs (backslash
  continuation aware). `test_render_docx_and_all_three_of_its_flags_are_collected`
  asserts `render-docx` is documented by a skill — that stops being true in
  Phase G and is replaced there.
- `skills/profile/SKILL.md` Pass 1 step 1 currently says: "`firecrawl_scrape`
  for a `site` entry, `extract_file` for the `linkedin-pdf` entry, a direct read
  for `local-primary` / `local` / `project` entries". Config keys:
  `profile_sources.{sites, linkedin_pdf, local, precedence, primary, projects}`.
  `scripts/config.py` accepts any path for `primary` / `local` / `linkedin_pdf`
  — no Python change needed.
- `skills/tailor/SKILL.md` — current inputs: queue row or URL; outputs
  `cv.md`, `cover-letter.md`, `cv.docx`, `cover-letter.docx`,
  `keyword-report.md` under `.jobhunter/applications/<slug>/`.
- `docs/evals/tailoring.md` — pass@3 judgement eval for tailor; guarded by
  `tests/test_evals.py` (read it before editing the eval file).

## Tech Stack

Python 3 stdlib: `os`, `re`, `tempfile`, `unittest`, `argparse`, `json`,
`codecs` (`cp1252` as the WinAnsi encoder). PDF 1.4 written by hand. MCP tools
used by skills (prose only): `mcp__xberg__extract_file`,
`mcp__firecrawl__firecrawl_scrape`, AskUserQuestion.

**Commands (detect-stack printed zero lines — no stack markers; these come from
`CLAUDE.md`):**

- static: `python3 -m compileall -q scripts tests`
- unit: `python3 -m unittest discover -s tests -t .`

Baseline at plan time: **553 tests, OK** (measured 2026-09-22 on `7d2d291`).

## Data Integration Map

| Feature | Data Source | Hook/API | Exists? | Action |
|---------|-------------|----------|---------|--------|
| Master CV from PDF, any tier | file at `profile_sources.primary` / `local[]` / `linkedin_pdf` | `mcp__xberg__extract_file` | Yes (`linkedin-pdf` only) | Widen prose rule to every tier |
| Pasted JD | conversation text | written to `.jobhunter/applications/<slug>/jd.md` | No | Add input path in tailor prose |
| Location check | JD text + candidate location in `master-cv.md` | model judgement | No | Add prose step; warn, never block |
| Requirements map | JD + `master-cv.md` | `requirements-map.md` | No | Add prose step + format |
| Agreement gate | user via AskUserQuestion | `approved: YYYY-MM-DD` line in map | No | Add blocking prose step |
| User-added evidence | agreement gate | appended to `master-cv.md`, source `user, YYYY-MM-DD` | No | Add prose rule |
| Keyword loop | `cv.md` + JD file | `jobhunter.py keywords-report` | Yes | Use existing, max 2 rounds |
| Shared marker gate | markdown | `docx.prepare()` | No (inside `docx.render`) | Extract, reuse in both renderers |
| PDF renderer | blocks from `docx.prepare()` | `scripts/pdf.py::render` | No | Create |
| CLI | argv | `jobhunter.py render-pdf` | No | Create subcommand 11 |
| E2E | `data/master-cv.pdf` + City of Hope JD (Ali's, never committed) | full tailor flow + `mcp__xberg__extract_file` round-trip | Yes (files exist locally) | Run, not commit |

## Contracts (verbatim — executor implements exactly these)

### `docx.prepare(markdown, label, allow_unverified=False) -> (blocks, notes)`

Everything `docx.render` does from the `unverified_findings` check through the
`EmptyDocumentError` check, moved unchanged. Raises `UnverifiedClaimError`,
`EmptyDocumentError`. Touches no filesystem. `docx.render` becomes:
`label = source or os.path.basename(path) or "<markdown>"`;
`blocks, notes = prepare(markdown, label, allow_unverified)`; then payload,
directory check, `_write_archive` — unchanged.

### `scripts/pdf.py`

```python
class PdfError(Exception): ...
class UnsupportedCharacterError(PdfError): ...

PAGE_SIZES = {"letter": (612, 792), "a4": (595, 842)}   # points
MARGIN = 54                                             # 0.75 in
SIZES = {("heading", 1): (16, True), ("heading", 2): (12, True),
         ("heading", 3): (11, True), ("paragraph", None): (10.5, False),
         ("bullet", None): (10.5, False)}               # (pt, bold)
LEADING = 1.25          # line height = size * LEADING
SPACE_AFTER = {"heading": 6, "paragraph": 6, "bullet": 2}   # points
BULLET_INDENT = 14      # text indent for bullets; glyph "•" drawn at MARGIN

def encode(text) -> bytes           # cp1252; control chars < 0x20 -> space
def text_width(text, size, bold) -> float   # sum(widths[byte]) * size / 1000
def wrap(text, size, bold, max_width) -> list[str]
def layout(blocks, page) -> list[list[tuple]]   # pages -> (x, y, font, size, text)
def render(markdown, path, allow_unverified=False, source=None, page="letter")
    -> {"out", "pages", "blocks", "notes", "bytes"}
```

- **Encoding:** `str.encode("cp1252")` is the WinAnsi encoder. Before encoding,
  replace every char with `ord < 0x20` by a space. Any `UnicodeEncodeError` →
  `UnsupportedCharacterError`. `render` checks **all** blocks before writing
  anything and reports **every distinct** unsupported character, each as
  `U+XXXX '<char>' on line N` where N is the 1-based line of its first
  occurrence in the source markdown (search `markdown.splitlines()`). Never
  substitute `?`.
- **Widths:** Helvetica and Helvetica-Bold advance widths (1/1000 em) for byte
  codes 32–255 in WinAnsiEncoding, stored as two 224-entry tuples
  `HELVETICA_WIDTHS` / `HELVETICA_BOLD_WIDTHS`. Source: the Adobe Core14 AFM
  files `Helvetica.afm` / `Helvetica-Bold.afm` (freely redistributable; the same
  data ships in pdf.js `external/standard_fonts` metrics and in reportlab
  `_fontdata_widths_helvetica*.py`). Fetch one of those with WebFetch/Firecrawl
  and record the URL + fetch date in a comment above the tables. **Never type
  the table from memory.** Pinned values the tests assert (from the AFM):
  Helvetica space 278, `A` 667, `a` 556, `W` 944, `i` 222, `m` 833, `•`(0x95)
  350; Helvetica-Bold space 278, `A` 722, `a` 556, `i` 278, `m` 889. If the
  fetched file disagrees with any pinned value, STOP and ask.
- **Wrap:** greedy on single spaces; a word wider than `max_width` alone is
  hard-split by characters; never returns an empty list for non-empty text;
  never emits a line wider than `max_width` (+0.01 tolerance).
- **Layout:** top-down from `height - MARGIN`; each line advances
  `size * LEADING`; after a block add `SPACE_AFTER[kind]`; a line whose baseline
  would fall below `MARGIN` starts a new page. Bullets: glyph `•` at `x=MARGIN`,
  text and every wrapped continuation at `x=MARGIN + BULLET_INDENT`. A heading
  is never left as the last line of a page: if it and the first line of the
  next block do not both fit, the heading moves to the next page.
- **Writer (PDF 1.4):** header `%PDF-1.4\n%\xe2\xe3\xcf\xd3\n`. Objects: 1
  Catalog (`/Pages 2 0 R`), 2 Pages (`/Kids`, `/Count`), 3 Font
  `/Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding`
  as `/F1`, 4 same with `/Helvetica-Bold` as `/F2`, 5 Info
  (`/Producer (ai-jobhunter)`, `/Title (<first heading text>)` when a heading
  exists), then per page a Page object (`/MediaBox [0 0 w h]`,
  `/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >>`, `/Contents`) and its
  content stream (uncompressed, exact `/Length`). Each line is
  `BT /F1 10.5 Tf x y Td (text) Tj ET`. Literal strings escape `\`, `(`, `)`
  and write bytes ≥ 0x80 as `\ddd` octal so the content stream is ASCII. xref:
  `xref\n0 N\n0000000000 65535 f \n` then one 20-byte `%010d 00000 n \n` per
  object; trailer `<< /Size N /Root 1 0 R /Info 5 0 R >>`, `startxref`, the
  xref byte offset, `%%EOF\n`. No dates in the file → identical bytes for
  identical input.
- **render order:** `label = source or basename(path) or "<markdown>"` →
  `docx.prepare(markdown, label, allow_unverified)` → encode-check all blocks →
  layout → `DestinationError` if directory missing → mkstemp
  (`suffix=".pdf.tmp"`, `dir=directory`) → write → `os.replace`; on any failure
  remove the temp file. stderr: `pdf.render: pages=%d blocks=%d notes=%d
  bytes=%d`. Uses `docx.DestinationError` (same class name as docx).

### CLI `render-pdf`

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" render-pdf \
  --in .jobhunter/applications/<slug>/cv.md \
  --out .jobhunter/applications/<slug>/cv.pdf \
  [--page letter|a4] [--allow-unverified]
```

`--page` uses `choices=["letter", "a4"]`, default `letter`. Refuses `--out`
not ending `.pdf` (case-insensitive) and `_same_file(input, out)` with
`docx.DestinationError`. Notes printed to stderr as `render-pdf: <note>`.
stdout `_emit({"out", "pages", "blocks", "notes", "bytes"})`.

### `requirements-map.md` format (tailor writes it)

```markdown
# Requirements map — <Job title>, <Company>

approved: YYYY-MM-DD        <!-- present only after the agreement gate passes -->

| # | Requirement (JD wording) | Kind | Status | Evidence (master-cv.md) | Agreed |
|---|---|---|---|---|---|
| 1 | 3+ years in process automation | required | match | "<quoted bullet>" | yes |
| 2 | Azure cloud experience | required | gap | — | yes (gap) |
```

`Kind` ∈ `required` / `preferred`. `Status` ∈ `match` / `partial` / `gap`.
Rows in the order the JD states them.

## Phases

### Phase A: keep the real CV out of git

**Estimated time:** 5 minutes

**Files:**
- Modify: `.gitignore`
- Test: `tests/test_manifest.py`

**Steps:**
1. Write failing test for `.gitignore` listing `data/` as an ignored path (`TestGitignore.test_data_dir_is_ignored`, reads `.gitignore` lines, asserts `"data/"` present). Expected error: `AssertionError: 'data/' not found`
2. Run `python3 -m unittest tests.test_manifest -k data_dir`, confirm it fails for that reason
3. Add `data/` to `.gitignore` under the existing "runtime user data" comment
4. Mutation: remove the line, see the test fail, restore
5. Run full suite, confirm green
6. Commit: `chore(AJOB-3): ignore data/ — it holds a real candidate's CV`

Completeness: error paths — not applicable (static file). Edge cases — `data`
without slash also acceptable? No: assert the exact line `data/`, since that is
what was written. Observability — not applicable.

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] `git check-ignore data/master-cv.pdf` prints a match (run in the main checkout)
- [ ] No placeholder/TODO comments in new code

### Phase B: extract `docx.prepare()` without changing docx output

**Estimated time:** 15 minutes

**Files:**
- Modify: `scripts/docx.py`
- Test: `tests/test_docx.py`

**Steps:**
1. Write failing test for `docx.prepare("# T\n\nBody\n", "x.md")` returning `([{"kind":"heading","level":1,"text":"T"},{"kind":"paragraph","text":"Body"}], [])`. Expected error: `AttributeError: module 'docx' has no attribute 'prepare'`
2. Run it, confirm it fails for that reason
3. Before refactoring, record a parity oracle on HEAD: for every `*.md` under `tests/fixtures/` and `tests/samples/` plus 6 inline strings (plain; marker with `allow_unverified=True`; table; nested bullets; entity-escaped marker with allow; fenced code block), render with the current `docx.render` and write the SHA-256 of each `word/document.xml` and its `notes` list into a new test as literals. The test re-renders after the refactor and asserts equality. Do not compute the oracle from a copy of the old code — literals recorded before the change are the only honest oracle
4. Move the gate/flatten/parse/strip/empty-check body of `docx.render` into `prepare(markdown, label, allow_unverified=False)`; `render` calls it (Contracts section)
5. Tests for `prepare` refusals: raises `UnverifiedClaimError` on `"- a [verifikasi]\n"`; raises `EmptyDocumentError` on `""`, on `"   \n"`, and on `"[verifikasi]\n"` with `allow_unverified=True`; writes no file (assert temp dir empty)
6. Run full suite — all 553 existing tests plus the new ones green, parity hashes equal
7. Mutation: in `prepare`, skip the residual check; confirm at least one existing docx test fails; restore
8. Commit: `refactor(docx): extract prepare() so a second renderer shares one gate`

Completeness: error paths — both refusals covered. Edge cases — empty,
whitespace, marker-only. Observability — `docx.render` stderr line unchanged.

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] parity: every recorded `document.xml` SHA-256 and notes list identical to pre-refactor
- [ ] `prepare` touches no filesystem (test asserts temp dir empty after each call)
- [ ] No placeholder/TODO comments in new code

### Phase C: `pdf.py` text primitives — encode, widths, wrap

**Estimated time:** 15 minutes

**Files:**
- Create: `scripts/pdf.py`
- Create: `tests/test_pdf.py`

**Steps:**
1. Write failing test for `pdf.text_width("A", 1000, False) == 667`. Expected error: `ModuleNotFoundError: No module named 'pdf'`
2. Run it, confirm it fails for that reason
3. Fetch Helvetica / Helvetica-Bold AFM widths (Contracts § Widths) and write `HELVETICA_WIDTHS`, `HELVETICA_BOLD_WIDTHS` with source URL + fetch date comment
4. Tests pinning every value listed in Contracts § Widths; test both tuples have exactly 224 entries
5. Implement `encode`, `text_width`, `wrap`, `PdfError`, `UnsupportedCharacterError`
6. Tests for `encode`: `"é · – — •"` encodes; `"\t"` → space; `"→"`, `"中"`, `"😀"` raise `UnicodeEncodeError` (the render-level error is Phase D)
7. Tests for `wrap`: `""` → `[]`; one short word → 1 line; text exactly `max_width` → 1 line; one space more → 2 lines; a 200-char word with no spaces → hard-split, every line ≤ `max_width`; multiple spaces collapse to one; property test over 500 seeded random strings (`random.Random(0)`) that no line exceeds `max_width` and `" ".join(lines)` equals the whitespace-normalised input
8. Run full suite green; mutation: make `wrap` skip the width check on the last line, see the property test fail, restore
9. Commit: `feat(pdf): WinAnsi encoding, Helvetica metrics, line wrapping`

Completeness: error paths — unencodable char surfaces as `UnicodeEncodeError`
here (wrapped in Phase D). Edge cases — empty, exact fit, overlong word,
repeated spaces, control chars. Observability — not applicable (pure
functions).

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] width tables carry a source URL and fetch date; pinned values match
- [ ] No placeholder/TODO comments in new code

### Phase D: `pdf.py` layout, writer and `render()` refusals

**Estimated time:** 15 minutes

**Files:**
- Modify: `scripts/pdf.py`
- Modify: `tests/test_pdf.py`

**Steps:**
1. Write failing test for `pdf.render("# T\n\nBody\n", <tmp>/cv.pdf)` producing a file that starts with `%PDF-1.4` and ends with `%%EOF\n`. Expected error: `AttributeError: module 'pdf' has no attribute 'render'`
2. Run it, confirm it fails for that reason
3. Implement `layout` and the writer per Contracts § Layout / § Writer, and `render` per § render order
4. Add a test-only PDF reader helper in `tests/test_pdf.py`: parse `startxref`, the xref table, assert each offset points at `"<n> 0 obj"`, assert each stream's `/Length` equals its byte length, extract `(text) Tj` strings in order (unescaping `\\`, `\(`, `\)`, `\ddd`, decoding cp1252)
5. Tests: text order equals block order; `(`, `)`, `\` in text round-trip; `é` round-trips via `\351`; letter MediaBox `[0 0 612 792]`, a4 `[0 0 595 842]`; 300 bullets → `pages > 1` and `/Count` equals pages; heading never last line on a page (construct a case); bullet glyph at `MARGIN`, continuation at `MARGIN + 14`; `/Title` equals first heading; same input twice → identical bytes
6. Refusal tests, each asserting **no file and no `*.pdf.tmp`** left in the dir: `[verifikasi]` → `docx.UnverifiedClaimError`; empty → `docx.EmptyDocumentError`; missing dir → `docx.DestinationError`; `"a → b\n中\n"` → `pdf.UnsupportedCharacterError` whose message names `U+2192` line 1 and `U+4E2D` line 2
7. Gate parity: loop over every marker spelling already pinned in `tests/test_docx.py` (import its fixture list if it exposes one; otherwise copy the list into `test_pdf.py` with a comment naming its source test) and assert `pdf.render` refuses each exactly as `docx.render` does
8. Run full suite green. Mutations: (a) drop the encode-check → the UnsupportedCharacter test fails; (b) write directly to `path` instead of mkstemp → the no-file-on-failure test fails (force a failure after partial write via monkeypatched `os.replace`); restore both
9. Commit: `feat(pdf): hand-written PDF 1.4 renderer sharing the docx gate`

Completeness: error paths — unverified, empty, missing dir, unwritable dir
(chmod 0o500 temp dir, skip on root), unsupported char, write failure mid-way.
Edge cases — one block, 300 blocks, overlong word, special chars, both page
sizes, heading at page end. Observability — stderr summary line; refusal
messages name label, line and codepoint.

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] xref offsets and stream lengths verified by the test reader
- [ ] every refusal leaves no file and no temp file
- [ ] security: input text is escaped in PDF literal strings (no raw `(`/`)`/`\` reaches a content stream); no path outside `--out`'s directory is written
- [ ] No placeholder/TODO comments in new code

### Phase E: CLI `render-pdf`

**Estimated time:** 10 minutes

**Files:**
- Modify: `scripts/jobhunter.py`
- Modify: `tests/test_cli.py`

**Steps:**
1. Write failing test for `main(["render-pdf", "--in", md, "--out", pdf])` exiting 0 with stdout JSON keys `{"out","pages","blocks","notes","bytes"}`. Expected error: `SystemExit`/exit code 1 with `invalid choice: 'render-pdf'`
2. Run it, confirm it fails for that reason
3. Add `cmd_render_pdf` and its parser block (Contracts § CLI), mirroring `cmd_render_docx`
4. Tests: `--out cv.md` → exit 1, stderr JSON `error` = `DestinationError`, input file unchanged; `--out` same file as `--in` → `DestinationError`; `--out X.PDF` accepted; `--page a4` → MediaBox a4; `--page b5` → exit 1 usage error; missing `--in` file → exit 1 JSON, no traceback; `[verifikasi]` input → `UnverifiedClaimError`, no file; `--allow-unverified` → exit 0 and a note reporting markers removed; unsupported char → `UnsupportedCharacterError`; notes echoed to stderr prefixed `render-pdf: `
5. Run full suite green; mutation: remove the `.pdf` suffix check, see the `--out cv.md` test fail, restore
6. Commit: `feat(cli): render-pdf subcommand`

Completeness: error paths — all refusal classes via CLI. Edge cases — case of
suffix, same-file, bad page. Observability — stderr notes and summary.

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] `python3 scripts/jobhunter.py --help` lists `render-pdf`
- [ ] security: `--out` suffix and same-file checks run before any read or write
- [ ] No placeholder/TODO comments in new code

### Phase F: `profile` reads a PDF in any tier

**Estimated time:** 5 minutes

**Files:**
- Modify: `skills/profile/SKILL.md`
- Test: `tests/test_manifest.py`

**Steps:**
1. Write failing test for profile SKILL.md stating that any `.pdf` source in any tier is extracted with `mcp__xberg__extract_file` (assert the sentence fragments `any tier` and `.pdf` appear in the same paragraph as `mcp__xberg__extract_file`). Expected error: `AssertionError`
2. Run it, confirm it fails for that reason
3. Edit Pass 1 step 1 and the "Scripts and MCP tools" bullet: a source path ending in `.pdf` (case-insensitive) in **any** tier — `primary`, `local`, `linkedin_pdf` — is extracted with `mcp__xberg__extract_file`; the native Read tool cannot parse PDF. Other sources keep their reader. Add one example line: `primary = "data/master-cv.pdf"` makes a curated CV PDF the highest-precedence source
4. Run full suite green (`TestNoCandidateSpecificContent` included); mutation: revert the prose, see the test fail, restore
5. Commit: `feat(profile): extract a PDF source in any tier with xberg`

Completeness: error paths — prose says an extraction that returns no text
stops and reports the file, never proceeds with an empty source. Edge cases —
`.PDF` uppercase. Observability — Pass 1's existing summary already names each
source read.

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] allow-list prose for `projects` unchanged (diff shows no edit there)
- [ ] No placeholder/TODO comments in new code

### Phase G: `tailor` — pasted JD, map, agreement gate, keyword loop, PDF

**Estimated time:** 15 minutes

**Files:**
- Modify: `skills/tailor/SKILL.md`
- Modify: `tests/test_manifest.py`

**Steps:**
1. Write failing test for tailor SKILL.md stating the agreement gate (`test_tailor_states_agreement_gate`), asserting tailor SKILL.md contains `requirements-map.md`, `approved:`, `jd.md`, `render-pdf`, and the phrase `no cv.md or cover-letter.md is written until` (lowercased compare). Expected error: `AssertionError`
2. Run it, confirm it fails for that reason
3. Replace `test_render_docx_and_all_three_of_its_flags_are_collected` with `test_render_pdf_and_all_four_of_its_flags_are_collected` asserting `commands["render-pdf"] == {"--in", "--out", "--page", "--allow-unverified"}`; add `test_tailor_no_longer_renders_docx` asserting `render-docx` does not appear in tailor SKILL.md
4. Rewrite `skills/tailor/SKILL.md` per the spec §3 flow, in this order: Inputs (queue row, URL, **or pasted JD text** → saved verbatim to `.jobhunter/applications/<slug>/jd.md`; slug from company + title in the JD, **ask the user if either is missing, never guess**); Location check (warn, never block, because a pasted JD bypasses `/ai-jobhunter:score`); Requirements map (format verbatim from this plan's Contracts); **Agreement gate** (walk the map group by group with AskUserQuestion; per row accept / reject pairing / add evidence / confirm gap; added evidence appended to `master-cv.md` with source `user, YYYY-MM-DD`; "No cv.md or cover-letter.md is written until every row is agreed"; write `approved: YYYY-MM-DD`; a map without that line means the gate has not passed); Write (approved rows only; JD wording mirrored only where an approved row evidences it; a `gap` never appears; keep existing no-invention and `verified: false` rules and the "never sent as-is" section verbatim); Keyword loop (`keywords-report` with `--jd` pointing at `jd.md` or the JD file; add missing terms only when an approved row evidences them; at most 2 rounds); Render (`render-pdf` twice, command block from Contracts § CLI with backslash continuation); refusals section rewritten for `render-pdf` naming `UnverifiedClaimError`, `EmptyDocumentError`, `DestinationError`, `UnsupportedCharacterError`; `--allow-unverified` paragraph kept verbatim with `render-docx` → `render-pdf`; Output list: `jd.md` (pasted only), `requirements-map.md`, `cv.md`, `cover-letter.md`, `cv.pdf`, `cover-letter.pdf`, `keyword-report.md`; final print adds map counts (match / partial / gap), approval date, location warning
5. Run full suite green (`TestNoCandidateSpecificContent`, documented-flag guards, `test_every_skill_names_the_plugin_root_variable`)
6. Mutations: (a) delete the agreement-gate sentence → new test fails; (b) change `--page` to `--paper` in the doc block → documented-flag guard fails; restore both
7. Commit: `feat(tailor): pasted JD, requirements map, agreement gate, PDF output`

Completeness: error paths — JD text missing company/title (ask), empty paste
(stop and report), `render-pdf` refusal (show, never auto-pass
`--allow-unverified`). Edge cases — JD with no location restriction (no
warning), map with zero gaps, user rejecting every pairing (map all gaps →
still requires agreement; CV then carries only non-JD-specific evidence, and the
skill says so). Observability — final print.

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] documented-flag guard collects all 4 `render-pdf` flags
- [ ] no candidate-specific strings under `skills/`
- [ ] No placeholder/TODO comments in new code

### Phase H: tailoring evals for the new judgement

**Estimated time:** 10 minutes

**Files:**
- Modify: `docs/evals/tailoring.md`
- Test: `tests/test_evals.py` (read first; extend only if it enumerates cases)

**Steps:**
1. Write failing test for the tailoring eval cases (in `tests/test_evals.py`), asserting `docs/evals/tailoring.md` has cases titled `pasted JD`, `agreement gate`, `gap never rendered`. Expected error: `AssertionError`
2. Run it, confirm it fails for that reason
3. Add three pass@3 cases using existing fictional/real-posting fixtures (not Ali's data): (a) pasted JD → `jd.md` written verbatim, slug asked when company missing; (b) agreement gate → no `cv.md` exists before `approved:` line; (c) gap never rendered → every `gap` row's requirement term absent from `cv.md` and `cover-letter.md` unless an approved row evidences it
4. Update "How to run" so outputs listed are the PDF set
5. Run full suite green; mutation: rename one case heading, see the test fail, restore
6. Commit: `docs(evals): tailoring cases for pasted JD, agreement gate, gaps`

Completeness: error paths — case (a) covers missing company. Edge cases —
covered by case list. Observability — pass@3 reporting unit unchanged.

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] eval cases reference only committed fixtures
- [ ] No placeholder/TODO comments in new code

### Phase I: docs sync and real end-to-end run

**Estimated time:** 15 minutes (+ interactive gate time with Ali)

**Files:**
- Modify: `CLAUDE.md`, `README.md` (if it lists subcommands or outputs)
- Not committed: everything under `.jobhunter/` and `data/`

**Steps:**
1. Write failing test for CLAUDE.md's subcommand list naming `render-pdf` (extend the existing manifest/CLAUDE.md guard if one exists; otherwise assert `render-pdf` in CLAUDE.md's "Subcommands:" line). Expected error: `AssertionError`
2. Run it, confirm it fails for that reason
3. Update CLAUDE.md: subcommand list (11), layout row `scripts/pdf.py` — "markdown → text PDF 1.4. Hand-written, Helvetica/WinAnsi, stdlib only", error classes add `pdf.{PdfError, UnsupportedCharacterError}`, test count **measured** from the suite run
4. E2E in the **main checkout's** `.jobhunter/` (gitignored), with Ali present: run `/ai-jobhunter:profile` with `primary = "data/master-cv.pdf"` → `master-cv.md`; run `/ai-jobhunter:tailor` with the City of Hope JD pasted → location warning shown (US-only vs Batam), map written, agreement gate walked with Ali, then `cv.pdf` + `cover-letter.pdf`
5. Extract `cv.pdf` back with `mcp__xberg__extract_file`; confirm every heading and bullet text present, in order; record result in the ledger
6. Run full suite green; commit docs: `docs(AJOB-3): CLAUDE.md for render-pdf and the tailor gate`

Completeness: error paths — if xberg round-trip loses text or order, STOP and
open a debug step (gaspol-debug) before merge. Edge cases — CV longer than one
page (expect 2 pages). Observability — ledger records page count, block count,
map counts.

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] CLAUDE.md test count equals the measured count
- [ ] xberg round-trip of the real `cv.pdf` returns complete text in order
- [ ] `git status` in main shows nothing under `data/` or `.jobhunter/`
- [ ] No placeholder/TODO comments in new code

## Out of scope

- Removing `render-docx` or its tests. Non-Latin scripts / embedded fonts in PDF.
  OCR beyond xberg defaults. Any send/submit path. Writing the tailored JD into
  the queue (`queue-append`).

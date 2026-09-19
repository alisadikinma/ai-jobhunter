> **For Claude:** REQUIRED SKILL: Use gaspol-execute to implement this plan.
> **CRITICAL:** This plan specifies real integrations. During execution,
> NEVER substitute placeholders for real data sources without explicit
> user approval. If a data source doesn't exist yet, STOP and ask.
> **Progress ledger — HARD PER-PHASE GATE:** `.gaspol/progress/PROGRESS-AJOB-2.md`. After EACH phase and **BEFORE** starting the next, STOP and do BOTH: (a) tick that phase's `## Checklist` line, (b) append a `## Log` line ending with the handoff cursor. This is **blocking**, like a test gate: no next phase until both are written. **Never batch all updates at the end** — a crash mid-run must leave a truthful state, not a stale one. Update ONLY this file — never the shared `.gaspol/progress.md`.
> **Self-contained:** this plan is the COMPLETE spec. It must be executable by an agent with **no other context** — a fresh post-`/compact` session, or an external executor in a separate process that cannot see this chat. Every file path, contract, config key, and convention it needs is written here **verbatim**, not merely referenced.

**Ticket:** AJOB-2
**Ledger:** .gaspol/progress/PROGRESS-AJOB-2.md
**Spec:** docs/plans/2026-09-19-AJOB-2-ats-docx-rendering-spec.md

## Goal

`tailor` stops at markdown. Nobody can attach a `.md` to a Workday form and no ATS can
parse one. This plan adds `scripts/docx.py` and a `render-docx` subcommand that turn a
tailored CV or cover letter into a `.docx` an ATS actually reads — single column, no
tables, no images, no header content — and that **refuses to write anything at all**
when the markdown still carries a claim the candidate has not verified.

## Architecture Context

From `CLAUDE.md`:

- **Python 3 standard library only.** No pip, no pytest, no PyYAML. Tests are `unittest`;
  config is TOML via `tomllib`. A dependency is out of scope by project constraint.
- **One entrypoint.** Every skill runs
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" <subcommand> [options]`.
  Existing subcommands: `config-show`, `ats-fetch`, `ats-normalize`, `queue-append`,
  `queue-list`, `queue-update`, `queue-key`, `keywords-report`, `promote-prepare`.
  This plan adds a tenth.
- **CLI output contract.** Every subcommand prints one JSON document on stdout — except
  `keywords-report --markdown`. Logging goes to stderr. A refusal is
  `{"error": "<class>", "message": "..."}` on stderr, exit 1, never a traceback.
  `scripts/jobhunter.py::main` already wraps every exception into that shape, and
  `_JsonArgumentParser` does the same for argparse failures.
- **Nothing candidate-specific ships under `skills/`**, enforced by `tests/test_manifest.py`.
- **Hard product rules:** never auto-applies, never sends outreach — drafts only.

Existing modules to reuse rather than reinvent: `scripts/keywords.py` already owns the
markdown-ish tokenizer and the "this is not an ATS score" honesty framing;
`scripts/ats.py::_clean_description` already strips HTML to text.

## Tech Stack

Python 3 stdlib. `zipfile` and plain string templates for OOXML — **not**
`xml.etree.ElementTree`, because the document body is a long flat sequence of `<w:p>`
elements and building it as a tree costs more than it buys. `re` for the markdown
subset. `unittest` for tests. `zipfile` + the existing `mcp__xberg__extract_file` path
for round-trip verification in Phase F.

**detect-stack: no stack markers for this project — verification is plan-declared only.**
The two commands every phase below uses are therefore written out here verbatim:

```bash
python3 -m compileall -q scripts tests          # static
python3 -m unittest discover -s tests -t .      # unit
```

## Data Integration Map

| Feature | Data Source | Module/API | Exists? | Action |
|---|---|---|---|---|
| CV / cover-letter markdown | `tailor` writes `.jobhunter/applications/<slug>/cv.md` | filesystem | Yes | Read directly |
| Markdown block parsing | — | `scripts/docx.py::parse_blocks` | **No** | Create |
| Unverified-claim markers | vault convention `[verifikasi]` / `[Assumption]` | `scripts/docx.py::ats_lint` | Yes (convention) | Read; drive the refusal |
| ATS flattening | — | `scripts/docx.py::flatten` | **No** | Create |
| OOXML writer | — | `scripts/docx.py::render` | **No** | Create |
| CLI wiring | `scripts/jobhunter.py` | `cmd_render_docx` | Yes (the file) | Add a subcommand |
| Skill wiring | `skills/tailor/SKILL.md` | prose + command block | Yes | Extend |
| HTML-to-text | `scripts/ats.py::_clean_description` | import | Yes | Reuse, do not reimplement |

## Contracts pinned here, verbatim

### Block contract (`parse_blocks` output)

A list of dicts. Every block has `kind` and `text`; `level` appears only on headings.

```python
{"kind": "heading", "level": 1, "text": "Ali Sadikin"}
{"kind": "heading", "level": 2, "text": "Experience"}
{"kind": "paragraph", "text": "AI Product Lead"}
{"kind": "bullet",    "text": "Led a team of 12"}
```

`kind` is exactly one of `heading`, `paragraph`, `bullet`. `level` is 1, 2 or 3.
Nothing else is ever emitted — Phase C guarantees it by flattening first.

### Lint finding contract (`ats_lint` output)

```python
{"line": 14, "text": "- increased revenue 40% [verifikasi]", "reason": "unverified-claim"}
```

`reason` is exactly one of: `unverified-claim`, `table`, `image`, `deep-nesting`,
`html`. Only `unverified-claim` refuses; the rest are what Phase C flattens.

### Paragraph style ids (fixed, not configurable — spec §5)

| Block | `w:pStyle` | Font | Size (half-points) | Bold |
|---|---|---|---|---|
| heading level 1 | `Heading1` | Calibri | 32 | yes |
| heading level 2 | `Heading2` | Calibri | 26 | yes |
| heading level 3 | `Heading3` | Calibri | 24 | yes |
| paragraph | `Normal` | Calibri | 22 | no |
| bullet | `ListParagraph` | Calibri | 22 | no |

Page: single column, 2cm margins (`1134` twentieths of a point on all four sides).

### The five OOXML parts, verbatim

Measured working on 2026-09-19 — a 1,749-byte file that a document extractor read back
with heading structure intact, em-dash and non-ASCII preserved, no markdown syntax leaked.

```
[Content_Types].xml
_rels/.rels
word/document.xml
word/_rels/document.xml.rels
word/styles.xml
```

`[Content_Types].xml`:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>
```

`_rels/.rels`:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>
```

`word/_rels/document.xml.rels`:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>
```

`word/document.xml` — `{body}` is the concatenated `<w:p>` elements:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}<w:sectPr><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr></w:body></w:document>
```

One paragraph, where `{style}` is a style id from the table above:

```xml
<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>
```

`xml:space="preserve"` is mandatory — without it Word collapses leading and trailing
spaces and two bullets can merge visually.

XML escaping, in this order: `&` → `&amp;`, then `<` → `&lt;`, then `>` → `&gt;`.
Escaping `&` last would double-escape the entities the first two produced.

## Amendments, 2026-09-19 (post-implementation, owner-approved)

Nine points where the pinned text above no longer matches the code. Every
one was found by RUNNING the code — on a real CV, through a real document
extractor, or by an adversarial review — and each is approved. They are
recorded here rather than silently left to drift, because this document is
the contract.

1. **Table rows are bullets, and every cell keeps its header.** Emitted as
   bare lines, consecutive rows are one run of text and `parse_blocks` joins
   them into a single paragraph by markdown's own rules: a three-row skills
   table rendered as one run-on sentence. Labelling only the first cell then
   left an ATS reading unlabelled numbers.
2. **Bullets may be indented, and an indented line continues the bullet
   above.** A CV wraps its bullets; without this, every wrapped bullet
   rendered as a bullet plus a stray un-bulleted paragraph.
3. **Bullets carry a literal `•` glyph.** Real list formatting needs a sixth
   part, `word/numbering.xml`, which is outside the pinned five and is a
   routine source of resume-parser garbage. The glyph is plain text.
4. **ZIP timestamps are fixed** to 1980-01-01, so the same markdown renders
   to the same bytes and the committed eval sample can be regenerated and
   diffed rather than trusted.
5. **`escape` first deletes XML-illegal control characters.** One stray byte
   makes the document unopenable rather than merely ugly.
6. **`word/styles.xml` carries `<w:ind w:left="360"/>` on `ListParagraph`**
   and a `docDefaults` block — what produces the bullet indent.
7. **`--out` is refused when it equals `--in` or does not end in `.docx`.**
   Compared with `os.path.samefile`, because macOS's default APFS is
   case-insensitive and a string compare let `--out CV.MD` overwrite
   `cv.md` — the tailored markdown, destroyed with no backup.

8. **Underscore emphasis is stripped too, and emphasis is stripped OUTSIDE
   code spans only.** `__bold__` and `_italic_` are written at least as often
   as the asterisk forms, and a marker wrapped in them defeated the gate.
   Confining the strip to non-code regions is what keeps `` `__init__` `` and
   `` `cat a | sed -e *` `` literal; a BARE `__init__` still becomes `init`,
   which is what markdown renders it as.
9. **The gate's projection NFKC-normalises and removes every character the
   XML writer deletes.** Every character `escape` deletes is already gone
   from the projection `_remove_invisible` produces, pinned by a test: a
   character the writer removes after the last check can otherwise
   reassemble a marker the gate cleared, which is exactly what
   `[veri\x01fikasi]` did. Invisibility is Unicode's
   `Default_Ignorable_Code_Point`, covered by the categories that contain it
   plus the four Hangul fillers — defining it as `Cc`/`Cf` alone let all
   sixteen variation selectors ship a readable marker.

A further amendment to the gate itself is recorded in the spec: the marker is
matched with its reason attached, matched on the line as it will finally
read, and removed from the document under `--allow-unverified`.

## Phases

### Phase A: markdown → blocks

**Estimated time:** 12 minutes

**Files:**
- Create: `scripts/docx.py`
- Test: `tests/test_docx.py`

**Steps:**
1. Write failing test for `docx.parse_blocks("# Ali\n\nHello\n")` returning `[{"kind": "heading", "level": 1, "text": "Ali"}, {"kind": "paragraph", "text": "Hello"}]`. Expected error: `ModuleNotFoundError: No module named 'docx'`
2. Run `python3 -m unittest discover -s tests -t .`, confirm it fails for that reason
3. Implement `parse_blocks(markdown)` per the Block contract above: `#`/`##`/`###` → heading with level; `-` or `*` at the start of a line, leading whitespace allowed → bullet; an indented line under a bullet continues that bullet; a blank-line-separated run of text → paragraph. Inline `**bold**`, `*italic*` and `` `code` `` markers are stripped from the text (Word carries the style, not the asterisks)
4. Add tests for the enumerated edge cases: empty string, whitespace-only, a heading with no text (`##` alone), `####` (level 4 — treated as a paragraph, not a heading, because the style table stops at 3), a bullet with no text, CRLF line endings, a line that is only `---`, two blank lines between paragraphs, 500 blocks, and text containing `&`, `<`, `>`
5. Run tests, confirm all pass
6. Commit: "feat(docx): parse the supported markdown subset into blocks"

**Completeness ladder:**
- Happy path: a real tailored CV's markdown becomes an ordered block list.
- Error paths: none can be raised here — `parse_blocks` never refuses. Unrecognised syntax becomes a `paragraph` rather than an exception, because refusing is Phase B's job and flattening is Phase C's. **This is the one phase with no error path, stated rather than left blank.**
- Edge cases: the ten in step 4.
- Observability: none needed — the return value IS the observation, and it is pure.

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] `parse_blocks` emits only `heading`/`paragraph`/`bullet`, proven by a test that asserts the set of `kind` values over a real fixture
- [ ] `####` yields a paragraph, not a level-4 heading
- [ ] No placeholder/TODO comments in new code
- [ ] detect-stack: no stack markers for this project — verification is plan-declared only

---

### Phase B: the unverified-claim gate

**Estimated time:** 12 minutes

**Files:**
- Modify: `scripts/docx.py`
- Test: `tests/test_docx.py`

**Why this phase is the point of the ticket.** `README.md` promises that a claim the
candidate flagged as unchecked never reaches an outward document. Before this phase
**nothing in the code enforced it** — the promise rested on model prose, while the other
three README guarantees are properties of the code. Rendering is the last moment before
a file exists, so this is where the asymmetry closes.

**Steps:**
1. Write failing test for `docx.ats_lint("- revenue up 40% [verifikasi]\n")` returning one finding with `reason == "unverified-claim"` and `line == 1`. Expected error: `AttributeError: module 'docx' has no attribute 'ats_lint'`
2. Run tests, confirm it fails for that reason
3. Implement `ats_lint(markdown)` returning findings per the Lint finding contract. Detect `[verifikasi]` and `[Assumption]` **case-insensitively**, anywhere on the line. Also detect and report (without refusing) `table`, `image`, `deep-nesting`, `html`
4. Implement `UnverifiedClaimError(Exception)` carrying `.findings`, with a message naming the file, the line number and the offending text, e.g. `cv.md:14 — "increased revenue 40% [verifikasi]"`
5. Add tests for the enumerated edge cases: marker in a heading, marker inside a fenced code block (**still refuses** — a CV has no reason to carry code fences, and a marker there is far more likely a real claim than a deliberate literal), `[VERIFIKASI]` uppercase, `[ Assumption ]` with inner spaces (**not** a match — the convention is exact, and loosening it invites false positives), two markers on one line (one finding, not two), a marker on the last line with no trailing newline, and markdown with no markers at all (empty finding list)
6. Run tests, confirm all pass
7. Commit: "feat(docx): refuse to render a claim the candidate never verified"

**Completeness ladder:**
- Happy path: clean markdown lints to an empty finding list.
- Error paths: `UnverifiedClaimError` when a marker is present and `--allow-unverified` was not passed. Unreadable input is the CLI's problem (Phase E), not this pure function's.
- Edge cases: the seven in step 5.
- Observability: every finding carries the line number and the line's own text, so the 3am reader sees the claim, not just a count.

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] A markdown file carrying `[verifikasi]` produces a finding whose `line` matches the real 1-based line number, proven against a multi-line fixture
- [ ] `[ Assumption ]` with inner spaces produces no finding
- [ ] Mutation check: delete the `[Assumption]` half of the pattern and confirm a test fails — a guard that guards only half of what it claims is this repository's documented recurring defect
- [ ] No placeholder/TODO comments in new code
- [ ] detect-stack: no stack markers for this project — verification is plan-declared only

---

### Phase C: ATS flattening

**Estimated time:** 14 minutes

**Files:**
- Modify: `scripts/docx.py`
- Test: `tests/test_docx.py`

**Steps:**
1. Write failing test for `docx.flatten("| Skill | Years |\n|---|---|\n| Python | 8 |\n")` returning markdown with no `|` characters and a line reading `- Skill: Python — Years: 8`. Expected error: `AttributeError: module 'docx' has no attribute 'flatten'`
2. Run tests, confirm it fails for that reason
3. Implement `flatten(markdown)` returning `(flattened_markdown, notes)` where `notes` is a list of strings for stderr. Transformations, all of them from spec §4 gate 2:
   - **table** → one BULLET per body row, every cell keeping its own header, `"- <header1>: <cell1> — <header2>: <cell2>"`, the separator row dropped
   - **image** `![alt](src)` → removed entirely; note records the `src`
   - **link** `[text](url)` → `text (url)`, because ATS frequently keep neither the anchor nor the href
   - **nesting deeper than one level** → flattened to one level
   - **inline HTML** → stripped via `ats._clean_description`, imported rather than reimplemented
4. Add tests for the enumerated edge cases: a table with one column, a table with a missing cell (pad with empty string, never drop the row), a table with no header separator (treated as paragraphs, not a table), an image with no alt text, a link whose text equals its url (emit the text once, not `url (url)`), a reference-style link `[text][ref]` (left as-is — out of scope, noted), three-level nesting, an empty table, and markdown containing a literal `|` inside a normal sentence (must NOT be treated as a table)
5. Run tests, confirm all pass
6. Commit: "feat(docx): flatten what an ATS parses badly, refuse nothing"

**Completeness ladder:**
- Happy path: markdown carrying a skills table becomes markdown a parser reads linearly.
- Error paths: none — `flatten` fixes rather than refuses, which is the whole distinction from Phase B. A construct it cannot fix is passed through and noted.
- Edge cases: the nine in step 4. The literal-pipe case is the one most likely to regress.
- Observability: `notes` names every transformation applied, printed to stderr by Phase E so the operator sees what changed without diffing.

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] `flatten` output, fed to `parse_blocks`, yields only `heading`/`paragraph`/`bullet` — the Phase A invariant holds on real flattened input
- [ ] A sentence containing a literal `|` survives unflattened
- [ ] `ats._clean_description` is imported, not reimplemented (assert by grepping the module for a second HTML stripper)
- [ ] No placeholder/TODO comments in new code
- [ ] detect-stack: no stack markers for this project — verification is plan-declared only

---

### Phase D: the OOXML writer

**Estimated time:** 15 minutes

**Files:**
- Modify: `scripts/docx.py`
- Test: `tests/test_docx.py`

**Steps:**
1. Write failing test for `docx.render("# Ali\n", path)` producing a file whose `zipfile.ZipFile(path).namelist()` equals the five parts listed in "The five OOXML parts" above. Expected error: `AttributeError: module 'docx' has no attribute 'render'`
2. Run tests, confirm it fails for that reason
3. Implement `render(markdown, path)`: run `ats_lint` → raise `UnverifiedClaimError` on any `unverified-claim` finding (unless `allow_unverified=True`), then `flatten`, then `parse_blocks`, then emit the five parts with `zipfile.ZIP_DEFLATED`. Use the style table and the escaping order pinned above
4. Write to a temp file in the destination directory and `os.replace` it into place, so a failure never leaves a half-written `.docx` — the same atomic-write pattern `scripts/jobq.py::update_rows` already uses
5. Add tests for the enumerated edge cases: empty markdown (**refuse** — `EmptyDocumentError`; an empty CV is never the intent), whitespace-only markdown (same), a single heading and nothing else, 500 blocks, text containing `&`/`<`/`>` (assert the escaping order by round-tripping `a & b < c`), non-ASCII (`—`, `é`, `日本語`), a destination directory that does not exist, and a destination that is not writable
6. Round-trip test: write a `.docx`, reopen it with `zipfile`, assert `testzip() is None` and that `word/document.xml` parses under `xml.etree.ElementTree` — a well-formedness check the writer cannot fake
7. Run tests, confirm all pass
8. Commit: "feat(docx): write the OOXML parts, atomically"

**Completeness ladder:**
- Happy path: a tailored CV's markdown becomes a valid `.docx` on disk.
- Error paths: `UnverifiedClaimError`, `EmptyDocumentError`, unwritable destination, missing destination directory. Each is a named class, never a bare `OSError` reaching the CLI as a crash wearing a refusal's clothes.
- Edge cases: the eight in step 5.
- Observability: on success, one stderr line `docx.render: blocks=<n> notes=<n> bytes=<n>` — the three numbers that tell a 3am reader whether the document is plausibly complete.

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] Generated `.docx` is a valid ZIP (`testzip() is None`) and `word/document.xml` is well-formed XML
- [ ] `a & b < c` round-trips exactly — proves the escaping order
- [ ] A failed render leaves no file at the destination path
- [ ] Empty and whitespace-only markdown both raise `EmptyDocumentError`
- [ ] No placeholder/TODO comments in new code
- [ ] detect-stack: no stack markers for this project — verification is plan-declared only

---

### Phase E: CLI subcommand and skill wiring

**Estimated time:** 12 minutes

**Files:**
- Modify: `scripts/jobhunter.py`, `skills/tailor/SKILL.md`, `CLAUDE.md`
- Test: `tests/test_cli.py`, `tests/test_manifest.py`

**Steps:**
1. Write failing test for `main(["render-docx", "--in", md_path, "--out", docx_path])` exiting 0 and printing JSON carrying `{"out": ..., "blocks": <int>, "notes": [...]}`. Expected error: `SystemExit: 1` with `{"error": "UsageError", "message": "argument command: invalid choice: 'render-docx'"}`
2. Run tests, confirm it fails for that reason
3. Add `cmd_render_docx` and its subparser: `--in` (required), `--out` (required), `--allow-unverified` (`store_true`, help text stating it is an opt-in escape from a safety gate and never a config default)
4. Emit `notes` on stdout as part of the JSON **and** on stderr as human lines — stdout is the parsed channel, stderr is the one a person reads
5. Extend `skills/tailor/SKILL.md`: the command block, what a refusal looks like, and the rule that `--allow-unverified` is Ali's decision per run, never the skill's
6. Update `CLAUDE.md`: add `render-docx` to the subcommand list and `scripts/docx.py` to the Layout table
7. Add tests: `render-docx` on markdown containing `[verifikasi]` returns exit 1 with `{"error": "UnverifiedClaimError"}` and **writes no file** (assert `os.path.exists(out) is False`); the same input with `--allow-unverified` exits 0 and writes the file; a missing `--in` is a `UsageError`
8. Run tests, confirm all pass
9. Commit: "feat(cli): render-docx, wired into tailor"

**Completeness ladder:**
- Happy path: `tailor` ends by producing `cv.docx` beside `cv.md`.
- Error paths: unverified claim (exit 1, no file), missing/unreadable `--in`, unwritable `--out`, empty document, missing required flag. All arrive as `{"error", "message"}` on stderr per the CLI contract.
- Edge cases: `--out` equal to `--in`; `--out` in a directory that does not exist; `--in` that is a directory; relative vs absolute paths.
- Observability: the JSON carries `blocks` and `notes` so the skill can report what changed without re-reading the file.

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] `tests/test_manifest.py` collects `render-docx` and all three of its flags — run `_documented_commands()` and assert they appear, since that guard was twice found vacuous in AJOB-1
- [ ] Mutation check: document `--alow-unverified` in `skills/tailor/SKILL.md`, confirm the manifest test FAILS, revert
- [ ] A refused render leaves no file on disk, asserted not assumed
- [ ] `CLAUDE.md` lists `render-docx` and `scripts/docx.py`
- [ ] No placeholder/TODO comments in new code
- [ ] detect-stack: no stack markers for this project — verification is plan-declared only

---

### Phase F: does it actually open?

**Estimated time:** 10 minutes, plus the owner's manual check

**Files:**
- Create: `docs/evals/docx-rendering.md`
- Modify: `.gaspol/progress/PROGRESS-AJOB-2.md`

**Why this phase exists as its own phase.** Every check in Phases A–E is a program
reading a file a program wrote. That proves well-formedness, not openability. Spec §10
records this as the one thing that cannot be verified from inside the session, and this
phase refuses to let it be quietly assumed.

**Steps:**
1. Write failing test for the presence of `docs/evals/docx-rendering.md` and its declaring at least one case per target application. Expected error: `AssertionError: missing docs/evals/docx-rendering.md`
2. Run tests, confirm it fails for that reason
3. Write `docs/evals/docx-rendering.md` with one case each for **Microsoft Word**, **Google Docs** and **LibreOffice**: open the generated file, confirm headings render as headings, bullets as bullets, and that no markdown syntax is visible. Each case names the exact file to open and what a pass looks like
4. Generate a sample `.docx` from a real tailored CV into `docs/evals/samples/` and commit it, so the manual check has a fixed artifact rather than one the checker must first produce
5. Run tests, confirm all pass
6. **Hand the manual check to the owner.** Do NOT tick it. Record in the ledger under `## Utang terbuka`: `Word / Google Docs / LibreOffice open-check: NOT RUN — needs Ali, cannot be verified from the session`
7. Commit: "test(docx): eval cases for the one thing a program cannot check"

**Completeness ladder:**
- Happy path: a human opens the sample in Word and sees a CV.
- Error paths: the file does not open, or opens with visible markdown. Both are recorded as eval failures, not worked around in code.
- Edge cases: three applications, since a file Word accepts and Google Docs rejects still blocks a real application.
- Tests: the deterministic half — that the eval document and the sample exist — is a unit test. The judgement half is a human's.
- Observability: the sample file is committed, so a future failure can be reproduced against the exact bytes that were checked.

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] `docs/evals/docx-rendering.md` exists and names all three applications
- [ ] A sample `.docx` is committed under `docs/evals/samples/`
- [ ] The manual open-check is recorded as **NOT RUN** in the ledger, not ticked
- [ ] No placeholder/TODO comments in new code
- [ ] detect-stack: no stack markers for this project — verification is plan-declared only

## Out of scope

PDF output (owner's decision — exported from Word by hand), per-company templates,
photos and logos, configurable fonts or sizes, and reference-style markdown links.

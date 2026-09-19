**Ticket:** AJOB-2

# ATS-friendly DOCX rendering

## Design

### 1. What this is, and what it is not

`tailor` stops at markdown. A human cannot attach a `.md` to a Workday form, and an
ATS cannot parse one. This ticket adds the render step: markdown in, `.docx` out,
with the layout discipline that actually determines whether a parser reads the
document.

**Not in scope, each for a stated reason:**

- **PDF.** Measured on 2026-09-19: Python's standard library has no PDF writer;
  `pandoc` fails without `pdflatex`; macOS `cupsfilter` produces a monospace dump of
  the raw markdown with `#` and `-` surviving as literal characters — not a CV. The
  owner chose DOCX-only, with PDF exported from Word by hand. Word's own PDF export
  is also the best-parsed PDF an ATS is likely to receive, and a human is already in
  the loop because this plugin never auto-applies.
- **Per-company templates.** Nobody asked; every added style option is another way to
  produce a CV that fails parsing.
- **Photos and logos.** An ATS reads text. An image is content the parser cannot see.

### 2. Why layout, not file format

Light research, 2026-09-19. The load-bearing finding is that **format matters far
less than layout**:

- Greenhouse, Lever and Workday parse text-based PDF and DOCX equally well.
- Taleo and Workday show a measurable DOCX edge.
- The figure most often cited for "DOCX wins" (97.4% vs 71.2% field extraction)
  compares **single-column DOCX against two-column PDF**. That measures layout, not
  format — it does not isolate the variable, and this spec does not rest on it.
- What actually breaks parsing: scanned images, tables, multi-column layouts, and
  content placed in headers or footers.

Sources: <https://atsverification.com/blog/pdf-vs-word-for-ats/>,
<https://www.resumemate.io/blog/pdf-vs-docx-for-resumes-in-2025-what-recruiters-ats-really-prefer/>,
<https://www.shashiworks.com/ats-workday-greenhouse-taleo.html>,
<https://resumeoptimizerpro.com/blog/greenhouse-ats-resume-guide> (all fetched 2026-09-19).

So the value of this ticket is the four things the renderer refuses to emit, not the
extension on the filename.

### 3. Architecture

One new module, one new subcommand, zero dependencies.

```
scripts/docx.py
  ats_lint(markdown)      -> [{"line": int, "text": str, "reason": str}, ...]
  flatten(markdown)       -> ATS-safe markdown
  render(markdown, path)  -> writes the .docx

jobhunter.py render-docx --in cv.md --out cv.docx [--allow-unverified]
```

`tailor` runs it at the end of its own flow. The markdown stays on disk and remains
the source of truth — it is what gets diffed between applications.

**Feasibility is proven, not assumed.** A stdlib OOXML writer was built and run on
2026-09-19: 1,749 bytes, valid ZIP, five parts
(`[Content_Types].xml`, `_rels/.rels`, `word/document.xml`,
`word/_rels/document.xml.rels`, `word/styles.xml`). Extraction returned the heading
structure intact, the em-dash and non-ASCII characters preserved, and no markdown
syntax leaked. For comparison, `pandoc` needed 10,685 bytes for less content.

### 4. Three gates, in order, before any XML is written

**Gate 1 — unverified claims. Refuses; writes nothing.**

**Amended 2026-09-19, after AJOB-2 review.** The marker is matched with its
reason attached too — `[Assumption: figure from memory]`, `[verifikasi nanti]`
— because that is the likelier thing to be written than the bare form. It is
matched on the line as it will finally READ, after inline emphasis is
stripped and html entities decoded: `[**verifikasi**]` and
`&#91;verifikasi&#93;` each got a claim into a rendered CV while the gate
reported clean. Under `--allow-unverified` the marker itself is removed from
the document — the override sends the claim, not the candidate's private
note to themselves.

Vault notes carry `[verifikasi]` and `[Assumption]` to mark a claim the author has not
yet checked. Rendering one into a CV converts a private "needs checking" into a public
statement to an employer, which the candidate then has to defend in an interview.

`README.md` already promises this will not happen. Before this ticket, **nothing in the
code enforced it** — the promise rested entirely on model prose, while the other three
guarantees (no auto-apply, no send path, allow-list) are properties of the code. This
gate closes that asymmetry at the last point before a file exists:

```
UnverifiedClaimError: cv.md:14 — "increased revenue 40% [verifikasi]"
No document was written. Remove the claim or verify it, then run again.
```

`--allow-unverified` exists for the case where the marker is a false positive, and
says so in its help text. It is opt-in per run, never a config default.

**Gate 2 — ATS flattening. Fixes; does not refuse.**

| Input | Becomes |
|---|---|
| markdown table | one bullet per row, every cell keeping its own header: `- Skill: Python — Years: 8` |
| image | dropped; the filename is reported on stderr |
| link | `text (url)` — ATS frequently lose the hyperlink and keep neither |
| nesting deeper than one level | flattened to one level |

The renderer fixes what a machine can fix and only refuses what needs a human
judgement. That split is the whole distinction between gates 1 and 2.

**Gate 3 — write.** Single column. No tables. No header or footer content. No text
boxes. Those four are the measured parser-breakers from §2, so they are a contract,
not a style preference.

### 5. Supported markdown subset

`#`–`###`, paragraphs, bullets, bold, italic, links. Everything else is flattened or
dropped with a line on stderr. Style is fixed — Calibri 11pt, single column, 2cm
margins — and deliberately not configurable, per §1.

### 6. Output layout

```
.jobhunter/applications/<slug>/
  cv.md               source, kept
  cv.docx             new
  cover-letter.md
  cover-letter.docx   new
  keyword-report.md   existing
```

### 7. Data Integration Map

| Feature | Data source | Exists? | Action |
|---|---|---|---|
| CV / cover-letter markdown | `tailor` | Yes | Use directly |
| OOXML writer | — | **No** | Create `scripts/docx.py` |
| `[verifikasi]` markers | vault convention | Yes | Read; drive gate 1 |
| paragraph styles | — | **No** | In-module constants, not config |

### 8. Precedent

**Applied — `pdf-header-consolidation`:** CV and cover letter share **one** renderer.
They differ only in which paragraph styles they use. The precedent's own finding was
six duplicated copies of one header helper across thirteen builders; two documents is
where that starts.

**Diverged — `picture-based-pptx-model-for-deliverables`:** that decision chose visual
fidelity over editability by rendering pages as images. For a sales deck, correct. For
an ATS CV it is total failure, because the parser reads text and an image has none.
The two decisions do not conflict; they optimise for different readers, and this is
recorded so the next reader does not treat the earlier note as general guidance.

### 9. Error handling

| Condition | Behaviour |
|---|---|
| `[verifikasi]` / `[Assumption]` present | `UnverifiedClaimError`, exit 1, no file written |
| `--in` missing or unreadable | named refusal as JSON on stderr, exit 1 |
| `--out` path not writable | named refusal; no partial file left behind |
| markdown empty or whitespace-only | refuse — an empty CV is never the intent |
| unsupported construct | flatten, report on stderr, continue |

All refusals follow the existing CLI contract: `{"error": "<class>", "message": "..."}`
on stderr, exit 1, never a traceback.

### 10. Open item — the one thing that cannot be verified from here

**Does Microsoft Word actually open the file?** The probe was read back with a document
extractor, and an extractor is not Word. Phase A must include the owner opening a
generated `.docx` in Word once, by hand, and confirming that headings render as
headings. This spec does not claim that has been checked, and the plan must not tick a
box that says it has.

Secondary, for the same reason: LibreOffice and Google Docs are untested. A file that
opens in Word but not in Google Docs would still block a real application.

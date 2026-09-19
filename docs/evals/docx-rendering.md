# Eval: `render-docx`

Governs the one property of this ticket no program in this repository can
check for itself: whether the `.docx` actually opens, and looks like a CV,
in the applications a real employer uses.

Every automated check in `tests/test_docx.py` is a program reading a file the
same program wrote. That proves the archive is a valid ZIP and that
`word/document.xml` is well-formed XML. It does not prove that Microsoft Word
opens the file, that Google Docs does not silently drop the styles, or that
no markdown syntax is visible on the page. Spec §10 records this as the one
thing that cannot be verified from inside a session, and this file refuses to
let it be quietly assumed.

## How to run this eval

The artefact is fixed and committed: `docs/evals/samples/tailored-cv-sample.docx`,
rendered from `tests/fixtures/tailored_cv.md`. Open that exact file — do not
generate a fresh one first. Rendering is byte-reproducible (the archive's
timestamps are fixed), so `tests/test_evals.py` fails if the committed sample
ever stops matching what the current code produces.

**Reporting unit: pass/fail per application, one run each.** There is no
`pass@k` here — opening a file is deterministic, and a judgement about what a
page looks like does not improve by being repeated. Three applications,
because a file Word accepts and Google Docs mangles still blocks a real
application.

A failure is recorded here and fixed in `scripts/docx.py`. It is never worked
around by hand-editing the sample: the sample is what the code produces, or
it is worthless as evidence.

## What every case checks

The same four properties, in three applications:

1. The file opens without a repair prompt, a warning, or an error.
2. Headings render as headings — "Rin Halvorsen" larger and bold, section
   headings ("Summary", "Experience", "Education", "Skills") visibly
   distinct from body text.
3. Bullets render as a bulleted list, each one its own line, indented, with
   a visible `•`. Wrapped bullets stay inside their bullet — no stray
   un-bulleted line beneath one.
4. No markdown syntax is visible anywhere on the page: no `#`, no `**`, no
   backticks, no `|`, no `](`.

---

### Case 1 — Microsoft Word

**File to open:** `docs/evals/samples/tailored-cv-sample.docx`

Word is the strictest reader of the three and the one that shows a repair
prompt when a part is malformed. It is also what most employers open a CV in,
so a failure here blocks the application outright.

**Pass:** the file opens with no "Word found unreadable content" prompt and no
repair dialog; the four properties above all hold; the page is a single
column with roughly 2cm margins and no header or footer content.

**Fail:** any repair prompt, any visible markdown character, a heading that
renders at body size, or bullets rendered as plain indented paragraphs with
no glyph.

---

### Case 2 — Google Docs

**File to open:** `docs/evals/samples/tailored-cv-sample.docx` — upload to
Google Drive, then open with Google Docs.

Google Docs is the most likely of the three to drop a style it does not
recognise, and it is what an employer using Workspace will convert the file
with. A CV that survives Word and collapses to uniform body text here still
reads as careless to whoever opens it.

**Pass:** the upload converts without an error; the four properties above all
hold; the heading levels remain visibly distinct from each other, not merely
from the body.

**Fail:** a conversion error, every paragraph rendering at the same size, or
bullets losing their indent.

---

### Case 3 — LibreOffice

**File to open:** `docs/evals/samples/tailored-cv-sample.docx`

LibreOffice validates OOXML more literally than Word does and will surface a
structurally wrong part that Word silently repairs. It stands in here for the
open-source parsers several ATS vendors build on.

**Pass:** the file opens with no import warning; the four properties above all
hold.

**Fail:** an import warning or error dialog, or any of the four properties
failing.

---

## What this eval deliberately does not check

Whether any specific ATS vendor's parser extracts the right fields. No
local check can honestly predict that — vendors parse differently from each
other, which is the same reason `keywords-report` states plainly that it is a
keyword overlap report and not an ATS score. What this file checks is that
the document is well-formed, plain, and readable by the three applications a
human will actually open it in.

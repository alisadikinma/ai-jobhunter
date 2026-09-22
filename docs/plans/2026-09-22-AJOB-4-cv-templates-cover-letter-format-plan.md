> **For Claude:** REQUIRED SKILL: Use gaspol-execute to implement this plan.
> **CRITICAL:** This plan specifies real integrations. During execution,
> NEVER substitute placeholders for real data sources without explicit
> user approval. If a data source doesn't exist yet, STOP and ask.
> **Progress ledger — HARD PER-PHASE GATE:** `.gaspol/progress/PROGRESS-AJOB-4.md` (created by `gaspol-plan` at plan-write time). After EACH phase and **BEFORE** starting the next, STOP and do BOTH: (a) tick that phase's `## Checklist` line, (b) append a `## Log` line ending with the handoff cursor. This is **blocking**, like a test gate: no next phase until both are written. **Never batch all updates at the end** — a crash mid-run must leave a truthful state, not a stale one. Update ONLY this file — never the shared `.gaspol/progress.md`.
> **Self-contained:** this plan is the COMPLETE spec. It must be executable by an agent with **no other context**. Every file path, contract, config key, and convention it needs is written here **verbatim**.

**Ticket:** AJOB-4
**Ledger:** .gaspol/progress/PROGRESS-AJOB-4.md
**Spec:** docs/plans/2026-09-22-AJOB-4-cv-templates-cover-letter-format-spec.md

## Goal

Give `/gaspol-jobhunter:tailor` three ATS-safe CV structures (`hybrid`,
`technical`, `leadership`) under `templates/cv/`, one research-backed
cover-letter format (`templates/cover-letter.md`), and a deterministic
`template-check` subcommand that keeps every CV and letter on that structure for
any JD. `tailor` proposes a template per JD, asks the letter level and an
optional personal detail in its agreement gate, detects enterprise portals
(Workday / Taleo / iCIMS) and then renders `.docx` alongside the PDF. First, fix
a leak found while planning: a multi-line HTML comment in markdown is rendered
into the PDF/DOCX as text.

## Architecture Context

From `CLAUDE.md` (repo root) — rules that bind every phase:

- **Python 3 standard library only.** No pip. Tests are `unittest`.
- **One entrypoint:** every skill runs
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" <subcommand> [options]`.
  One JSON document on stdout; logs on stderr; a refusal is
  `{"error": "<class>", "message": "..."}` on stderr, exit 1, never a traceback
  (`scripts/jobhunter.py::main` converts exceptions already).
- **Nothing candidate-specific ships** — no real person, employer, JD or
  location in `skills/`, `scripts/`, `tests/`, `docs/evals/`, `templates/`.
  Guards: `tests/test_manifest.py::TestNoCandidateSpecificContent` (skills/) and
  `TestNoCandidateSpecificContentBeyondSkills` with
  `_EXTRA_SCAN_ROOTS = ("tests", "scripts", os.path.join("docs", "evals"))` at
  line ~40. That guard asserts each root exists and that it read ≥1 file.
  Fixtures use the fictional name "Rin Halvorsen".
- **Unverified markers:** `render-pdf`/`render-docx` refuse markdown with
  `[verifikasi]` / `[Assumption]`; `--allow-unverified` is the user's per-run
  decision, never the skill's.
- **Error classes are quoted verbatim in SKILL.md prose.** New here:
  `templates.TemplateError`.
- **Debugging checklist:** every guard is proven by mutating what it guards and
  watching its test fail. Every count in docs is measured.
- **`tailor` agreement gate (AJOB-3):** `requirements-map.md` is walked with the
  user; no `cv.md` exists until it carries `approved: YYYY-MM-DD`; a `gap` row
  never reaches a CV or letter. This plan adds lines to that gate.

Existing code this plan reuses:

- `scripts/docx.py` — `prepare(markdown, label, allow_unverified=False) ->
  (blocks, notes)` (flatten → gate → parse → empty check); `flatten(markdown)`
  returns `(text, notes)`; the html-stripping regex at line ~474:
  `r"<!--.*?-->|</?[A-Za-z][A-Za-z0-9]*(?:\s[^<>]*?)?\s*/?>"` with `re.S` is
  applied **per line**, so a comment spanning lines survives. Measured
  2026-09-22: `prepare("<!-- template: x\nsections:\n- A | B\n-->\n# Name\n\nline\n")`
  returns blocks `'<!-- template: x sections:'`, bullet `'A | B'`, `'-->'`.
  Notes use the form `"line %d: inline html stripped (%s)"` (line ~907).
- `scripts/docx.py::render` and `scripts/pdf.py::render` both go through
  `docx.prepare`, so one fix covers both renderers.
- `scripts/jobhunter.py` — argparse with subcommands; `cmd_render_pdf` /
  `cmd_render_docx` show the shape (`_emit(dict)` for stdout, errors raised as
  exceptions). Add `template-check` after `render-pdf`.
- `tests/test_manifest.py` — `_documented_commands()` collects every
  `jobhunter.py <subcommand>` + flags from skill docs (backslash-continuation
  aware, placeholders like `[--page letter|a4]` handled — check how);
  `test_every_documented_flag_exists_on_its_subcommand`;
  `TestClaudeMdNamesEverySubcommand` (CLAUDE.md "Subcommands:" line must equal
  the CLI list); `test_tailor_*` prose tests.
- `skills/tailor/SKILL.md` — sections today: Inputs, Reading the JD is mandatory,
  master-cv never sent as-is, Location check, Scripts this skill calls,
  Requirements map, Agreement gate (blocking), Write, Keyword loop, Render, How
  to run the scripts, When `render-pdf` refuses, Output.
- `docs/evals/tailoring.md` — pass@3 cases 1–9; `tests/test_evals.py` checks
  case headings.
- Research (committed): `docs/research/2026-09-22-cover-letter-callback-notebooklm-raw.md`,
  `docs/research/2026-09-22-ats-cv-templates-notebooklm-raw.md`.

## Tech Stack

Python 3 stdlib (`os`, `re`, `json`, `argparse`, `unittest`, `tempfile`).
Markdown template files. No new dependencies.

**Commands** (detect-stack prints zero lines for this repo; from `CLAUDE.md`):

- static: `python3 -m compileall -q scripts tests`
- unit: `python3 -m unittest discover -s tests -t .`

Baseline: **632 tests, OK** on `9696912` (2026-09-22).

## Data Integration Map

| Feature | Data Source | Hook/API | Exists? | Action |
|---------|-------------|----------|---------|--------|
| Multi-line comment strip | markdown | `docx.flatten` / `docx.prepare` | Yes (single-line only) | Fix |
| CV templates | `templates/cv/{hybrid,technical,leadership}.md` | `templates.load_cv_template(name)` | No | Create |
| Cover-letter format | `templates/cover-letter.md` | `templates.letter_levels()` + file | No | Create |
| CV check | cv markdown + template | `templates.check_cv(markdown, name)` | No | Create |
| Letter check | letter markdown + level | `templates.check_letter(markdown, level, company, role)` | No | Create |
| CLI | argv | `jobhunter.py template-check` | No | Create subcommand 12 |
| Portal detection | JD URL host or user answer | `tailor` prose | No | Add prose |
| Gate additions | AskUserQuestion → `requirements-map.md` header | `tailor` prose | No | Add prose |
| PDF / DOCX | `cv.md`, `cover-letter.md` | `render-pdf`, `render-docx` | Yes | Use existing |
| Research summary | two raw NotebookLM files | `docs/research/2026-09-22-cover-letter-callback.md` | No | Write |

## Contracts (verbatim)

### Template file format — `templates/cv/<name>.md`

First block of every template file is exactly one HTML comment, machine-read:

```markdown
<!-- gaspol-jobhunter cv-template
name: technical
for: engineering / AI / software individual contributors
sections:
- Professional Summary | Summary
- Technical Skills | Skills
- Work Experience | Professional Experience | Experience
- Projects (optional)
- Education
- Certifications (optional)
- Awards (optional)
-->
```

Each `sections:` line: canonical heading, then `|`-separated aliases; a trailing
`(optional)` marks the section optional (after the canonical name or the last
alias). After the comment: `# <Full name>`, a contact line
`<City, Country> · <email> · <phone> · <linkedin url>`, then one `## <canonical
heading>` per section in order, each with `<angle-bracket>` guidance lines and,
for experience, one example entry skeleton:

```markdown
### <Job title> — <Employer>

<Mon YYYY> – <Mon YYYY | Present> · <City, Country>

- <Action verb> <what> <scope>, <metric> <impact>
```

Plus, at the end, a short `## ` -free guidance paragraph is NOT allowed (it
would be a paragraph outside any section). Put guidance inside sections as
`<...>` lines only.

Section lists (from spec §3):

| name | sections |
|---|---|
| `hybrid` | Professional Summary \| Summary · Core Skills \| Skills \| Core Competencies · Work Experience \| Professional Experience \| Experience · Education · Certifications (optional) · Awards (optional) |
| `technical` | as in the example above |
| `leadership` | Executive Summary \| Professional Summary \| Summary · Work Experience \| Professional Experience \| Experience · Board Positions \| Advisory Roles (optional) · Education · Certifications (optional) · Awards (optional) · Additional Information \| Skills & Interests (optional) |

### `templates/cover-letter.md`

Same comment convention, `gaspol-jobhunter cover-letter`, carrying
`levels:` lines `entry 200-250`, `mid 250-400`, `executive 400-450` and
`sign-offs: Sincerely, | Best regards, | Kind regards,`. Body after the comment:

```markdown
# <Full name>

<City, Country> · <email> · <phone>

Dear <Hiring manager name, or "<Team> Hiring Team">,

<P1 Opening, 1-3 sentences: exact role title and company name, plus the single strongest approved evidence for the JD's top requirement. Never open with "I am writing to".>

<P2 Proof, 3-5 sentences: one SCAR story (situation, challenge, action, result) built from one approved requirements-map row, the JD's top requirement, with its metric.>

<P3 Fit, 3-4 sentences: two or three further approved rows in the JD's own wording, and one company-specific line taken only from the JD text or a detail the user gave.>

<P4 Close, 1-3 sentences: the value offered and a direct call to action. Never "hope to hear from you".>

Sincerely,

<Full name>
```

### `scripts/templates.py`

```python
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates")
class TemplateError(Exception): ...
def list_cv_templates() -> list[str]          # sorted names from templates/cv/*.md
def load_cv_template(name) -> dict            # {"name","for","sections":[{"name","aliases":[...],"optional":bool}]}
def letter_levels() -> dict                   # {"entry":(200,250),"mid":(250,400),"executive":(400,450)} parsed from the file
def check_cv(markdown, name) -> list[dict]    # findings [{"rule","line","message"}]
def check_letter(markdown, level, company=None, role=None) -> list[dict]
```

Unknown name/level, a template file without the comment block, a malformed
`sections:` line → `TemplateError` naming the file and line.

**CV rules** (rule ids exactly): `no-name` (no `# ` H1), `no-contact` (no
non-empty non-heading line directly after H1, blank lines skipped),
`unknown-section` (an `## ` heading not matching any canonical/alias,
case-insensitive, whitespace-collapsed), `order` (mapped sections not in template
order), `duplicate-section`, `missing-section` (required section absent),
`pronoun` (a bullet line `- `/`* ` matching `\bI\b(?!/)` case-sensitive or
`\b(me|my|we|our)\b` case-insensitive). Line numbers are 1-based in the input.

**Letter rules:** `no-salutation` (no line starting `Dear `), `generic-salutation`
(`To Whom It May Concern` or `Dear Sir or Madam`, case-insensitive, anywhere),
`no-sign-off` (none of the sign-offs on its own line after the salutation),
`paragraphs` (body — blank-line-separated non-heading blocks strictly between
salutation and sign-off — is not exactly 4), `word-count` (body words outside the
level band, inclusive both ends; a word = a whitespace-separated token containing
at least one letter or digit), `opening-company` / `opening-role` (P1 lacks
`company` / `role`, case-insensitive; only checked when given), `weak-opening`
(a body sentence starts with `I am writing` — per sentence since plan-verifier round 1, per spec §6), `weak-close` (`hope to hear from
you`, case-insensitive). Message for `word-count` states the count and the band.

### CLI `template-check`

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" template-check \
  --cv .jobhunter/applications/<slug>/cv.md --template technical

python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" template-check \
  --letter .jobhunter/applications/<slug>/cover-letter.md --level mid \
  --company "<Company>" --role "<Job title>"
```

stdout: `{"kind": "cv"|"letter", "template"|"level": <value>, "findings": [...],
"ok": <len(findings)==0>}`, exit 0 either way. Refusals (exit 1, JSON on stderr,
class `TemplateError`): both or neither of `--cv`/`--letter`; `--cv` without
`--template`; `--letter` without `--level`; unknown template/level; input file
missing (message names the path). `--template` / `--level` are validated
against the files, not a hard-coded `choices=` list.

## Phases

### Phase A: strip multi-line HTML comments before rendering

**Estimated time:** 10 minutes

**Files:**
- Modify: `scripts/docx.py`
- Test: `tests/test_docx.py`, `tests/test_pdf.py`

**Steps:**
1. Write failing test for `docx.prepare("<!-- a\nb\n-->\n# Name\n\nline\n", "t.md")` returning only the heading and the paragraph, with a note `"lines 1-3: html comment stripped"`. Expected error: `AssertionError` (blocks contain `'<!-- a b'`)
2. Run it, confirm it fails for that reason
3. In `docx.flatten`, before the per-line pass, remove every `<!--` … `-->` span that crosses a newline (outside fenced/indented code — reuse however flatten already detects code so a comment inside a code block stays verbatim), keeping line count stable by replacing the span with the same number of empty lines so later line numbers do not shift; emit one note per span `lines A-B: html comment stripped`
4. Tests: comment at start, middle, end; two comments; unterminated `<!--` (no `-->`) → left as-is, no crash, note `line N: unterminated html comment left in place`; comment inside a fenced code block → kept; single-line comment behaviour unchanged (existing tests); a later note's line number is unchanged by the strip; `pdf.render` output text does not contain `sections:` for a template-like input
5. Re-run `PARITY_ORACLE` (`tests/test_docx.py`) — must stay green; if an oracle input contains a multi-line comment and its hash changes, STOP and report (the change would be a behaviour change on a committed fixture)
6. Mutation: remove the new strip → the step-1 test fails; restore
7. Commit: `fix(docx): strip multi-line html comments instead of rendering them`

Completeness: error paths — unterminated comment. Edge cases — start/middle/end,
two spans, inside code, CRLF input. Observability — note with line range.

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] PARITY_ORACLE unchanged
- [ ] No placeholder/TODO comments in new code

### Phase B: CV template files and their loader

**Estimated time:** 15 minutes

**Files:**
- Create: `templates/cv/hybrid.md`, `templates/cv/technical.md`, `templates/cv/leadership.md`, `scripts/templates.py`, `tests/test_templates.py`
- Modify: `tests/test_manifest.py` (add `"templates"` to `_EXTRA_SCAN_ROOTS`)

**Steps:**
1. Write failing test for `templates.load_cv_template("technical")["sections"][0] == {"name": "Professional Summary", "aliases": ["Summary"], "optional": False}`. Expected error: `ModuleNotFoundError: No module named 'templates'`
2. Run it, confirm it fails for that reason
3. Write the three template files per Contracts (sections exactly as the table). Guidance lines carry the universal rules: contact line plain text under the name; `Mon YYYY – Mon YYYY`, `Present` for current; bullets start with an action verb, carry a metric where the evidence has one, no first-person pronouns; 1 page under ~10 years, 2 pages above; work authorization only if the user supplies it. Leadership bullets emphasise scope, team size, P&L/budget, business outcome; technical bullets emphasise architecture, scale, performance, stack; hybrid puts grouped skills before experience
4. Implement `TEMPLATES_DIR`, `TemplateError`, `list_cv_templates`, `load_cv_template` (parse the comment block)
5. Tests: all three load; `list_cv_templates() == ["hybrid", "leadership", "technical"]`; optional flags right (e.g. leadership `Board Positions` aliases `["Advisory Roles"]`, optional True); unknown name → `TemplateError`; a temp file without the comment block → `TemplateError` naming it; a malformed `sections:` line (empty name) → `TemplateError` with line; each template renders through `pdf.render` with zero refusals and its rendered text contains no `cv-template` / `sections:` (depends on Phase A); each template's own `## ` headings equal its section list in order (so the file and its definition cannot drift)
6. Add `"templates"` to `_EXTRA_SCAN_ROOTS`; mutation: put the surname "Sadikin" into `templates/cv/hybrid.md` → the beyond-skills guard fails; restore. Mutation 2: reorder two `## ` headings in `technical.md` → the file-vs-definition test fails; restore
7. Commit: `feat(templates): three ATS CV structures and their loader`

Completeness: error paths — unknown, missing comment, malformed line.
Edge cases — alias lists of 0/1/3 items, `(optional)` after an alias.
Observability — errors name file and line.

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] every template renders through `render-pdf` with no leaked comment text
- [ ] no candidate-specific strings under `templates/` (guard extended and mutated)
- [ ] No placeholder/TODO comments in new code

### Phase C: `check_cv`

**Estimated time:** 15 minutes

**Files:**
- Modify: `scripts/templates.py`
- Test: `tests/test_templates.py`

**Steps:**
1. Write failing test for `templates.check_cv(<a valid technical CV>, "technical") == []`. Expected error: `AttributeError: module 'templates' has no attribute 'check_cv'`
2. Run it, confirm it fails for that reason
3. Implement per Contracts § CV rules
4. Tests, one per rule id, each asserting rule id AND line: valid CV per template (3); alias heading accepted (`## Experience`); heading case/whitespace variants accepted; `unknown-section`; `order` (Education before Work Experience); `duplicate-section`; `missing-section` (no Education); optional sections omitted → no finding; `pronoun` for `I led`, `my team`, `We built`, `our`; NOT flagged: `AI`, `IoT`, `I/O`, `Mine` (word boundary), pronoun in a non-bullet paragraph; `no-name`; `no-contact` (H1 followed directly by `##`); empty markdown → `no-name`; CRLF input; findings sorted by line
5. Also run `check_cv` over the three template files themselves with their own name: only findings allowed are none (templates must pass their own check)
6. Mutation: disable the order rule → order test fails; mutate pronoun regex to drop `(?!/)` → `I/O` test fails; restore
7. Commit: `feat(templates): check_cv keeps a CV on its template`

Completeness: error paths — unknown template delegates to `TemplateError`.
Edge cases — listed. Observability — each finding has rule, line, message.

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] every rule id has a failing-input test and a passing-input test
- [ ] No placeholder/TODO comments in new code

### Phase D: cover-letter format and `check_letter`

**Estimated time:** 15 minutes

**Files:**
- Create: `templates/cover-letter.md`
- Modify: `scripts/templates.py`
- Test: `tests/test_templates.py`

**Steps:**
1. Write failing test for `templates.letter_levels() == {"entry": (200, 250), "mid": (250, 400), "executive": (400, 450)}`. Expected error: `AttributeError: module 'templates' has no attribute 'letter_levels'`
2. Run it, confirm it fails for that reason
3. Write `templates/cover-letter.md` per Contracts; implement `letter_levels` and `check_letter`
4. Tests: a generated valid letter per level (build bodies of exact word counts in the test with a helper) → `[]`; word count at 200/250 (entry pass), 199 and 251 (fail), same for mid and executive edges; `paragraphs` with 3 and 5; `no-salutation`; `generic-salutation` both phrases; `no-sign-off`; each sign-off accepted; optional H2 subject line before the salutation ignored; `opening-company`/`opening-role` only when given; `weak-opening`; `weak-close`; unknown level → `TemplateError`; the template file itself parses and renders through `pdf.render`
5. Mutation: make the band exclusive at the top → the 250-entry test fails; restore
6. Commit: `feat(templates): research-backed cover-letter format and check_letter`

Completeness: error paths — unknown level, template without levels line.
Edge cases — edges ±1, missing sign-off, subject line, CRLF. Observability —
word-count message states count and band.

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] band edges tested inclusive on both ends for all three levels
- [ ] No placeholder/TODO comments in new code

### Phase E: CLI `template-check`

**Estimated time:** 10 minutes

**Files:**
- Modify: `scripts/jobhunter.py`
- Test: `tests/test_cli.py`

**Steps:**
1. Write failing test for `main(["template-check", "--cv", p, "--template", "technical"])` exiting 0 with JSON `{"kind": "cv", "template": "technical", "findings": [], "ok": true}`. Expected error: exit 1 with `invalid choice: 'template-check'`
2. Run it, confirm it fails for that reason
3. Add `cmd_template_check` + parser per Contracts § CLI, after `render-pdf`
4. Tests: CV with findings → exit 0, `ok: false`, findings list; letter path with `--level`/`--company`/`--role`; each refusal (both flags, neither, `--cv` without `--template`, `--letter` without `--level`, unknown template, unknown level, missing file) → exit 1, stderr JSON `error` = `TemplateError`, no traceback; `--help` lists the subcommand
5. Mutation: drop the "both flags" check → its test fails; restore
6. Commit: `feat(cli): template-check subcommand`

Completeness: error paths — all refusals. Edge cases — both/neither. Observability
— JSON findings with line numbers.

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] `python3 scripts/jobhunter.py --help` lists `template-check`
- [ ] security: input paths are only read, never written; no path is executed
- [ ] No placeholder/TODO comments in new code

### Phase F: `tailor` — portal, template, letter level, check, DOCX

**Estimated time:** 15 minutes

**Files:**
- Modify: `skills/tailor/SKILL.md`
- Test: `tests/test_manifest.py`

**Steps:**
1. Write failing test for tailor SKILL.md naming the new flow (`test_tailor_states_templates_and_letter_format`): asserts (whitespace-collapsed, lowercased) `templates/cv/`, `templates/cover-letter.md`, `template-check`, `myworkdayjobs.com`, `taleo.net`, `icims.com`, `never guess`, `letter-level:`, `template:`, `portal:`, `nothing is invented`, `render-docx`. Expected error: `AssertionError`
2. Run it, confirm it fails for that reason
3. Edit tailor SKILL.md: (a) new `## Portal detection` after Location check — hosts `myworkdayjobs.com` / `myworkdaysite.com` → Workday, `taleo.net` → Taleo, `icims.com` → iCIMS; pasted JD without URL → ask, never guess; enterprise → DOCX too, with the reason (DOCX parses most reliably in those portals); (b) Agreement gate gains: proposed template from `templates/cv/` + one-sentence reason (confirm/switch), letter level `entry`/`mid`/`executive` with the word bands, optional personal detail (hiring-manager name, referral, specific reason for the company) — none given → "<Team> Hiring Team" and JD facts only, nothing is invented; header lines `template: <name>`, `letter-level: <level>`, `portal: <workday|taleo|icims|other>` written with `approved:`; (c) Write: `cv.md` on the approved template's sections in order, `cover-letter.md` on `templates/cover-letter.md` (P1–P4 rules restated briefly); (d) new `## Template check` before Keyword loop: both commands (Contracts § CLI, backslash-continued), fix text and re-run until `"ok": true`, never render with findings; (e) Render: PDF always, plus `render-docx` for both when portal is enterprise (command block with `--in`/`--out`), output list adds `cv.docx`/`cover-letter.docx` in that case; (f) final print adds template, level, portal, check results. Remove the AJOB-3 test `test_tailor_no_longer_renders_docx` and replace with `test_tailor_renders_docx_only_for_enterprise_portals` asserting `render-docx` appears only in the portal/render sections together with the word `enterprise`
4. Run full suite: flag guard must collect `template-check` flags `{"--cv","--template","--letter","--level","--company","--role"}` — add an explicit collection test like `test_render_pdf_and_all_four_of_its_flags_are_collected`
5. Mutations: delete the "never guess" sentence → prose test fails; change `--level` to `--lvl` in the doc → flag guard fails; restore
6. Commit: `feat(tailor): template choice, letter format, portal-aware DOCX`

Completeness: error paths — `template-check` refusal shown to user, never
bypassed; portal unknown → ask. Edge cases — JD with URL on an unknown host →
`portal: other`, PDF only. Observability — final print.

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] flag guard collects all six `template-check` flags
- [ ] no candidate-specific strings under `skills/`
- [ ] No placeholder/TODO comments in new code

### Phase G: research summary and evals

**Estimated time:** 10 minutes

**Files:**
- Create: `docs/research/2026-09-22-cover-letter-callback.md`
- Modify: `docs/evals/tailoring.md`, `tests/test_evals.py`

**Steps:**
1. Write failing test for the tailoring eval carrying cases titled `template choice` and `cover-letter format` (in `tests/test_evals.py`, same pattern as `TestTailoringNewJudgementCases`). Expected error: `AssertionError`
2. Run it, confirm it fails for that reason
3. Write the curated research summary from the two raw files: each format rule → the source(s) that support it → evidence strength (field experiment / large observational / survey / advice), including the disagreements (metrics: Zety 4% vs guides; motivation 63% vs 9%; keywords ATS 70% vs humans 2%) and the arXiv tapering result. Cite source URLs from the raw files' source lists; invent nothing
4. Add eval cases 10 (template choice: a leadership JD → `leadership` proposed with reason; an engineering JD → `technical`; the user can switch) and 11 (cover-letter format: `template-check --letter` returns `ok: true`, P1 names role and company, one SCAR story from one approved row, no gap row, no invented personal detail) using committed fixtures only
5. Mutation: rename case 11 heading → test fails; restore
6. Commit: `docs(AJOB-4): research summary and tailoring evals for templates`

Completeness: error paths — n/a (docs), reason: no code path. Edge cases — covered
by eval cases. Observability — n/a, reason: static documents.

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] every rule in `templates/cover-letter.md` traces to a cited source in the summary
- [ ] No placeholder/TODO comments in new code

### Phase H: docs sync, version, real run

**Estimated time:** 15 minutes (+ gate time with the user)

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `.claude-plugin/plugin.json` (0.2.0 → 0.3.0), `tests/test_manifest.py` (version pin)
- Not committed: `.jobhunter/`, `data/`

**Steps:**
1. Write failing test for plugin version `0.3.0` (update the pin in `tests/test_manifest.py`). Expected error: `AssertionError: '0.2.0' != '0.3.0'`
2. Run it, confirm it fails for that reason
3. Bump version; CLAUDE.md: Subcommands line adds `template-check` (guarded by `TestClaudeMdNamesEverySubcommand`), layout rows `scripts/templates.py` and `templates/cv/`, `templates/cover-letter.md`, error class `templates.TemplateError`, hard-rule line for templates, test count measured; README tailor row mentions templates and the letter format
4. Real run in the main checkout's `.jobhunter/` with the user: pick a real JD the user provides (or the existing application directory's `jd.md`), run tailor end to end — template proposed and confirmed, level chosen, check returns `ok: true` for both, PDFs (and DOCX if enterprise portal) rendered, xberg round-trip of `cv.pdf` complete and in order. Record in ledger
5. Full suite; commit docs: `docs(AJOB-4): CLAUDE.md, README and 0.3.0 for templates`

Completeness: error paths — if the real run surfaces a check false positive,
STOP and open a debug step. Edge cases — n/a beyond the real run. Observability
— ledger records template, level, portal, findings count, pages.

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] CLAUDE.md test count equals the measured count
- [ ] real run: both `template-check` calls `ok: true`; xberg round-trip complete
- [ ] No placeholder/TODO comments in new code

## Out of scope

Visual template styles; new renderers; fetching hiring-manager names from the
web; marketplace publish and install (done after merge, on the user's word).

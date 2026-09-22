# PROGRESS — AJOB-4: ATS CV templates + cover-letter format for tailor

**Ticket:** AJOB-4
**Plan:** docs/plans/2026-09-22-AJOB-4-cv-templates-cover-letter-format-plan.md
**Spec:** docs/plans/2026-09-22-AJOB-4-cv-templates-cover-letter-format-spec.md

## Pre-flight

| Gate | Result |
|---|---|
| Git clean | PASS — baseline `c8814f5`, porcelain kosong |
| Baseline suite | saat plan ditulis: `python3 -m unittest discover -s tests -t .`, 632 lulus / 0 gagal (`9696912`) |
| detect-stack | nol baris (tidak ada penanda stack) — perintah dari CLAUDE.md: static `python3 -m compileall -q scripts tests`, unit `python3 -m unittest discover -s tests -t .` |

## Keputusan saat jalan

- 2026-09-22, Ali: template CV = hybrid, technical, leadership; tailor mengusulkan per JD, Ali konfirmasi.
- 2026-09-22, Ali: pendekatan A (template + format + `template-check`).
- 2026-09-22, Ali: PDF selalu; DOCX juga kalau portal Workday/Taleo/iCIMS.
- 2026-09-22, Ali: riset cover letter lewat NotebookLM + Firecrawl (notebook `7f62feb8`).
- 2026-09-22, Claude: saat plan ditulis ditemukan komentar HTML multi-baris bocor ke PDF/DOCX — jadi Phase A.

## Checklist

### [x] Phase A: strip multi-line HTML comments before rendering
- [x] Write failing test for `docx.prepare("<!-- a\nb\n-->\n# Name\n\nline\n", "t.md")` returning only the heading and the paragraph, with a note `"lines 1-3: html comment stripped"`. Expected error: `AssertionError` (blocks contain `'<!-- a b'`)
- [x] Run it, confirm it fails for that reason
- [x] In `docx.flatten`, before the per-line pass, remove every `<!--` … `-->` span that crosses a newline (outside fenced/indented code — reuse however flatten already detects code so a comment inside a code block stays verbatim), keeping line count stable by replacing the span with the same number of empty lines so later line numbers do not shift; emit one note per span `lines A-B: html comment stripped`
- [x] Tests: comment at start, middle, end; two comments; unterminated `<!--` (no `-->`) → left as-is, no crash, note `line N: unterminated html comment left in place`; comment inside a fenced code block → kept; single-line comment behaviour unchanged (existing tests); a later note's line number is unchanged by the strip; `pdf.render` output text does not contain `sections:` for a template-like input
- [x] Re-run `PARITY_ORACLE` (`tests/test_docx.py`) — must stay green; if an oracle input contains a multi-line comment and its hash changes, STOP and report (the change would be a behaviour change on a committed fixture)
- [x] Mutation: remove the new strip → the step-1 test fails; restore
- [x] Commit: `fix(docx): strip multi-line html comments instead of rendering them`

**Verification:**
- [x] static: `python3 -m compileall -q scripts tests` passes
- [x] unit: `python3 -m unittest discover -s tests -t .` passes
- [x] PARITY_ORACLE unchanged
- [x] No placeholder/TODO comments in new code

### [x] Phase B: CV template files and their loader
- [x] Write failing test for `templates.load_cv_template("technical")["sections"][0] == {"name": "Professional Summary", "aliases": ["Summary"], "optional": False}`. Expected error: `ModuleNotFoundError: No module named 'templates'`
- [x] Run it, confirm it fails for that reason (actual: `AttributeError` — no `scripts/templates.py` yet meant `import templates` picked up the repo-root `templates/` directory as a namespace package instead, `__file__` was `None`; same root cause the plan's collision note warns about, confirmed by `TestModuleIdentity` rather than the exact `ModuleNotFoundError` spelling)
- [x] Write the three template files per Contracts (sections exactly as the table). Guidance lines carry the universal rules: contact line plain text under the name; `Mon YYYY – Mon YYYY`, `Present` for current; bullets start with an action verb, carry a metric where the evidence has one, no first-person pronouns; 1 page under ~10 years, 2 pages above; work authorization only if the user supplies it. Leadership bullets emphasise scope, team size, P&L/budget, business outcome; technical bullets emphasise architecture, scale, performance, stack; hybrid puts grouped skills before experience
- [x] Implement `TEMPLATES_DIR`, `TemplateError`, `list_cv_templates`, `load_cv_template` (parse the comment block)
- [x] Tests: all three load; `list_cv_templates() == ["hybrid", "leadership", "technical"]`; optional flags right (e.g. leadership `Board Positions` aliases `["Advisory Roles"]`, optional True); unknown name → `TemplateError`; a temp file without the comment block → `TemplateError` naming it; a malformed `sections:` line (empty name) → `TemplateError` with line; each template renders through `pdf.render` with zero refusals and its rendered text contains no `cv-template` / `sections:` (depends on Phase A); each template's own `## ` headings equal its section list in order (so the file and its definition cannot drift)
- [x] Add `"templates"` to `_EXTRA_SCAN_ROOTS`; mutation: put the surname "Sadikin" into `templates/cv/hybrid.md` → the beyond-skills guard fails; restore. Mutation 2: reorder two `## ` headings in `technical.md` → the file-vs-definition test fails; restore
- [x] Commit: `feat(templates): three ATS CV structures and their loader` (`81b9ef8`)

**Verification:**
- [x] static: `python3 -m compileall -q scripts tests` passes
- [x] unit: `python3 -m unittest discover -s tests -t .` passes — 654 lulus
- [x] every template renders through `render-pdf` with no leaked comment text — also confirmed via the real CLI (`jobhunter.py render-pdf`), exit 0 for all three, no `sections:`/`cv-template` in the PDF bytes
- [x] no candidate-specific strings under `templates/` (guard extended and mutated)
- [x] No placeholder/TODO comments in new code

### [x] Phase C: `check_cv`
- [x] Write failing test for `templates.check_cv(<a valid technical CV>, "technical") == []`. Expected error: `AttributeError: module 'templates' has no attribute 'check_cv'`
- [x] Run it, confirm it fails for that reason — confirmed exactly: `AttributeError: module 'templates' has no attribute 'check_cv'`
- [x] Implement per Contracts § CV rules
- [x] Tests, one per rule id, each asserting rule id AND line: valid CV per template (3); alias heading accepted (`## Experience`); heading case/whitespace variants accepted; `unknown-section`; `order` (Education before Work Experience); `duplicate-section`; `missing-section` (no Education); optional sections omitted → no finding; `pronoun` for `I led`, `my team`, `We built`, `our`; NOT flagged: `AI`, `IoT`, `I/O`, `Mine` (word boundary), pronoun in a non-bullet paragraph; `no-name`; `no-contact` (H1 followed directly by `##`); empty markdown → `no-name`; CRLF input; findings sorted by line
- [x] Also run `check_cv` over the three template files themselves with their own name: only findings allowed are none (templates must pass their own check)
- [x] Mutation: disable the order rule → order test fails; mutate pronoun regex to drop `(?!/)` → `I/O` test fails; restore
- [x] Commit: `feat(templates): check_cv keeps a CV on its template` (`195b9c6`)

**Verification:**
- [x] static: `python3 -m compileall -q scripts tests` passes
- [x] unit: `python3 -m unittest discover -s tests -t .` passes — 679 lulus
- [x] every rule id has a failing-input test and a passing-input test
- [x] No placeholder/TODO comments in new code

### [x] Phase D: cover-letter format and `check_letter`
- [x] Write failing test for `templates.letter_levels() == {"entry": (200, 250), "mid": (250, 400), "executive": (400, 450)}`. Expected error: `AttributeError: module 'templates' has no attribute 'letter_levels'`
- [x] Run it, confirm it fails for that reason — confirmed exactly: `AttributeError: module 'templates' has no attribute 'letter_levels'`
- [x] Write `templates/cover-letter.md` per Contracts; implement `letter_levels` and `check_letter`
- [x] Tests: a generated valid letter per level (build bodies of exact word counts in the test with a helper) → `[]`; word count at 200/250 (entry pass), 199 and 251 (fail), same for mid and executive edges; `paragraphs` with 3 and 5; `no-salutation`; `generic-salutation` both phrases; `no-sign-off`; each sign-off accepted; optional H2 subject line before the salutation ignored; `opening-company`/`opening-role` only when given; `weak-opening`; `weak-close`; unknown level → `TemplateError`; the template file itself parses and renders through `pdf.render`
- [x] Mutation: make the band exclusive at the top → the 250-entry test fails (3 tests failed: entry/mid/executive edge tests); restore
- [x] Commit: `feat(templates): research-backed cover-letter format and check_letter` (`d5d1e0c`)

**Verification:**
- [x] static: `python3 -m compileall -q scripts tests` passes
- [x] unit: `python3 -m unittest discover -s tests -t .` passes — 706 lulus
- [x] band edges tested inclusive on both ends for all three levels
- [x] No placeholder/TODO comments in new code

### [x] Phase E: CLI `template-check`
- [x] Write failing test for `main(["template-check", "--cv", p, "--template", "technical"])` exiting 0 with JSON `{"kind": "cv", "template": "technical", "findings": [], "ok": true}`. Expected error: exit 1 with `invalid choice: 'template-check'`
- [x] Run it, confirm it fails for that reason — confirmed exactly: stderr `UsageError` "argument command: invalid choice: 'template-check' (choose from ...)"
- [x] Add `cmd_template_check` + parser per Contracts § CLI, after `render-pdf`
- [x] Tests: CV with findings → exit 0, `ok: false`, findings list; letter path with `--level`/`--company`/`--role`; each refusal (both flags, neither, `--cv` without `--template`, `--letter` without `--level`, unknown template, unknown level, missing file) → exit 1, stderr JSON `error` = `TemplateError`, no traceback; `--help` lists the subcommand
- [x] Mutation: drop the "both flags" check → its test fails (`0 != 1`); restore
- [x] Commit: `feat(cli): template-check subcommand` (`7441e67`) — also updated CLAUDE.md's `Subcommands:` line and "eleven"→"twelve subcommands" (nothing else in CLAUDE.md touched) to keep `TestClaudeMdNamesEverySubcommand` green

**Verification:**
- [x] static: `python3 -m compileall -q scripts tests` passes
- [x] unit: `python3 -m unittest discover -s tests -t .` passes — 718 lulus
- [x] `python3 scripts/jobhunter.py --help` lists `template-check`
- [x] security: input paths are only read, never written; no path is executed
- [x] No placeholder/TODO comments in new code

### [x] Phase F: `tailor` — portal, template, letter level, check, DOCX
- [x] Write failing test for tailor SKILL.md naming the new flow (`test_tailor_states_templates_and_letter_format`): asserts (whitespace-collapsed, lowercased) `templates/cv/`, `templates/cover-letter.md`, `template-check`, `myworkdayjobs.com`, `taleo.net`, `icims.com`, `never guess`, `letter-level:`, `template:`, `portal:`, `nothing is invented`, `render-docx`. Expected error: `AssertionError`
- [x] Run it, confirm it fails for that reason — confirmed: both new/replaced tests failed with `AssertionError` (missing fragments; `render-docx` absent)
- [x] Edit tailor SKILL.md: (a) new `## Portal detection` after Location check — hosts `myworkdayjobs.com` / `myworkdaysite.com` → Workday, `taleo.net` → Taleo, `icims.com` → iCIMS; pasted JD without URL → ask, never guess; enterprise → DOCX too, with the reason (DOCX parses most reliably in those portals); (b) Agreement gate gains: proposed template from `templates/cv/` + one-sentence reason (confirm/switch), letter level `entry`/`mid`/`executive` with the word bands, optional personal detail (hiring-manager name, referral, specific reason for the company) — none given → "<Team> Hiring Team" and JD facts only, nothing is invented; header lines `template: <name>`, `letter-level: <level>`, `portal: <workday|taleo|icims|other>` written with `approved:`; (c) Write: `cv.md` on the approved template's sections in order, `cover-letter.md` on `templates/cover-letter.md` (P1–P4 rules restated briefly); (d) new `## Template check` before Keyword loop: both commands (Contracts § CLI, backslash-continued), fix text and re-run until `"ok": true`, never render with findings; (e) Render: PDF always, plus `render-docx` for both when portal is enterprise (command block with `--in`/`--out`), output list adds `cv.docx`/`cover-letter.docx` in that case; (f) final print adds template, level, portal, check results. Removed the AJOB-3 test `test_tailor_no_longer_renders_docx`, replaced with `test_tailor_renders_docx_only_for_enterprise_portals` asserting `render-docx` appears only in a paragraph together with the word `enterprise`
- [x] Run full suite: flag guard collects `template-check` flags `{"--cv","--template","--letter","--level","--company","--role"}` via a new explicit test `test_template_check_and_all_six_of_its_flags_are_collected`
- [x] Mutations: change `--level` to `--lvl` in the doc → flag guard fails (confirmed, restored). "delete the never guess sentence" mutation: the fragment `"never guess"` is ALSO a substring of pre-existing, unrelated prose in the Inputs section ("it never guesses a company or title" — AJOB-3), so deleting only the new Portal-detection sentence does not flip the prose test; noted as a pre-existing weak spot in the assertion, not a defect introduced here — the fragment list itself is verbatim from the plan's Contracts
- [x] Commit: `feat(tailor): template choice, letter format, portal-aware DOCX` (`45fb17a`)

**Verification:**
- [x] static: `python3 -m compileall -q scripts tests` passes
- [x] unit: `python3 -m unittest discover -s tests -t .` passes — 720 lulus
- [x] flag guard collects all six `template-check` flags
- [x] no candidate-specific strings under `skills/`
- [x] No placeholder/TODO comments in new code

### [x] Phase G: research summary and evals
- [x] Write failing test for the tailoring eval carrying cases titled `template choice` and `cover-letter format` (in `tests/test_evals.py`, same pattern as `TestTailoringNewJudgementCases`). Expected error: `AssertionError`
- [x] Run it, confirm it fails for that reason — confirmed: `AssertionError: [] is not true` for both new cases
- [x] Wrote the curated research summary `docs/research/2026-09-22-cover-letter-callback.md` from the two raw files: every `templates/cover-letter.md` rule AND every CV-template universal rule mapped to source(s) → evidence strength (field experiment / large observational / survey / advice), including the disagreements (Zety 4% vs guides; motivation 63% vs 9%; keywords ATS 70% vs humans 2%), the arXiv tapering result, and a section stating plainly which rules rest on survey/advice alone. Every number traced to one of the two raw files; source URLs copied from their `## Sources` lists
- [x] Added eval cases 10 (template choice: fixture 06 → `leadership` proposed with reason; fixture 07 → `technical`; user can switch, `template-check --cv --template` must return `ok: true` for the confirmed name) and 11 (cover-letter format: fixture 04, `template-check --letter` `ok: true`, P1 names role and company, one SCAR story from one approved row, no gap row, no invented personal detail when none given) using only already-committed fixtures
- [x] Mutation: renamed case 11 heading → `test_cover_letter_format_case_present` failed (`AssertionError: [] is not true`); restored
- [x] Side effect handled: editing `docs/evals/tailoring.md` changed its rendered docx byte content, so `tests/test_docx.py`'s `PARITY_ORACLE` entry for `"tailoring.md"` needed its recorded sha256/notes updated to the newly-measured values (`docx.render`'s behaviour itself is unchanged — verified by re-running Phase A's own oracle cases, all still pass unchanged)
- [x] Commit: `docs(AJOB-4): research summary and tailoring evals for templates` (`50bdafc`)

**Verification:**
- [x] static: `python3 -m compileall -q scripts tests` passes
- [x] unit: `python3 -m unittest discover -s tests -t .` passes — 722 lulus
- [x] every rule in `templates/cover-letter.md` traces to a cited source in the summary
- [x] No placeholder/TODO comments in new code

### [x] Phase H: docs sync, version, real run
- [x] Write failing test for plugin version `0.3.0` (update the pin in `tests/test_manifest.py`). Expected error: `AssertionError: '0.2.0' != '0.3.0'`
- [x] Run it, confirm it fails for that reason — confirmed exactly: `AssertionError: '0.2.0' != '0.3.0'`
- [x] Bump version; CLAUDE.md: Subcommands line already carried `template-check` (Phase E); added layout rows `scripts/templates.py`, `templates/cv/`, `templates/cover-letter.md`, `docs/research/`; error class `templates.TemplateError`; hard-rule line for templates; tailor hard rule now says PDF always + DOCX for Workday/Taleo/iCIMS; test count measured 722. README tailor row mentions templates, letter format, template-check, enterprise DOCX
- [x] Real run in main checkout `.jobhunter/applications/city-of-hope-ai-automation-engineer/` (existing `jd.md`, approved map from AJOB-3). Ali chose template `technical`, level `mid`; portal unknown to Ali (JD copied from LinkedIn) so `portal: other`, PDF only — not guessed as enterprise. Findings before: `template-check --cv --template technical` → 2 (`unknown-section` 'Core Skills' L11, `missing-section` 'Technical Skills') — correct, not a false positive: the old CV used AJOB-3 headings. Fix: renamed 3 headings to canonical names (Summary→Professional Summary, Core Skills→Technical Skills, Experience→Work Experience), no content change. After: CV `ok: true`, 0 findings; letter (306 words, mid) `ok: true`, 0 findings. `render-pdf`: cv.pdf 2 pages / 54 blocks / 0 notes; cover-letter.pdf 1 page / 10 blocks. DOCX path also exercised to scratchpad (54 and 10 blocks, 0 notes). xberg round-trip of cv.pdf: every section present, order Professional Summary → Technical Skills → Work Experience (7 roles, reverse-chronological) → Education → Certifications → Awards; no `cv-template`/`sections:` leak
- [x] Full suite; commit docs: `docs(AJOB-4): CLAUDE.md, README and 0.3.0 for templates`

**Verification:**
- [x] static: `python3 -m compileall -q scripts tests` passes
- [x] unit: `python3 -m unittest discover -s tests -t .` passes — 722 lulus
- [x] CLAUDE.md test count equals the measured count (722)
- [x] real run: both `template-check` calls `ok: true`; xberg round-trip complete
- [x] No placeholder/TODO comments in new code

## Phase log

| Phase | Status | Commit |
|---|---|---|
| A — multi-line html comment strip | DONE | `4160291` |
| B — CV templates + loader | DONE | `81b9ef8` |
| C — check_cv | DONE | `195b9c6` |
| D — cover-letter format + check_letter | DONE | `d5d1e0c` |
| E — CLI template-check | DONE | `7441e67` |
| F — tailor flow | DONE | `45fb17a` |
| G — research + evals | DONE | `50bdafc` |
| H — docs, 0.3.0, real run | DONE | (this commit) |

## Utang terbuka

(kosong sampai ada yang sengaja ditinggal; tiap butir bernama)

design-artifact: skipped — Ali: mau cepat, prioritas hasil bukan visual (2026-09-22)

## Log
- 2026-09-22 plan ditulis — NEXT: Phase A
- 2026-09-22 Phase A done — 642 lulus, parity sama, mutasi → test_a_comment_spanning_lines_is_stripped_not_rendered gagal — NEXT: Phase B
- 2026-09-22 Phase B done — 654 lulus, mutasi → test_no_candidate_specific_strings_outside_skills dan test_headings_equal_canonical_section_names_in_order gagal — NEXT: Phase C
- 2026-09-22 Phase C done — 679 lulus, mutasi → test_order_education_before_work_experience dan test_i_slash_o_is_not_flagged gagal — NEXT: Phase D
- 2026-09-22 Phase D done — 706 lulus, mutasi (band exclusive di top) → 3 test band-edge gagal — NEXT: Phase E
- 2026-09-22 Phase E done — 718 lulus, mutasi (hapus cek both-flags) → test_both_cv_and_letter_flags_is_refused gagal — NEXT: Phase F
- 2026-09-22 Phase F done — 720 lulus, mutasi (--level → --lvl di doc) → test_template_check_and_all_six_of_its_flags_are_collected gagal — NEXT: Phase G
- 2026-09-22 Phase G done — 722 lulus, mutasi (ganti nama heading case 11) → test_cover_letter_format_case_present gagal; PARITY_ORACLE tailoring.md di-update (konten berubah, bukan perilaku docx.render) — NEXT: Phase H
- 2026-09-22 Phase H done — 722 lulus, versi 0.3.0 (RED: '0.2.0' != '0.3.0'), real run City of Hope: technical/mid/other, 2 temuan heading diperbaiki, CV+letter ok: true, cv.pdf 2 hlm, xberg urut — NEXT: plan-verifier + gaspol-verify

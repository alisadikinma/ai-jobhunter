# PROGRESS — AJOB-3: tailor from PDF master CV + pasted JD, agreement gate, PDF output

**Ticket:** AJOB-3
**Plan:** docs/plans/2026-09-22-AJOB-3-tailor-pdf-plan.md
**Spec:** docs/plans/2026-09-22-AJOB-3-tailor-pdf-spec.md

## Pre-flight

| Gate | Result |
|---|---|
| Git clean | PASS — baseline `4a8a14c`, porcelain kosong |
| Baseline suite | PASS pre-flight 2026-09-22 (553 lulus). Saat plan ditulis: `python3 -m unittest discover -s tests -t .`, 553 lulus / 0 gagal (`7d2d291`) |
| detect-stack | nol baris (tidak ada penanda stack) — perintah dari CLAUDE.md: static `python3 -m compileall -q scripts tests`, unit `python3 -m unittest discover -s tests -t .` |

## Keputusan saat jalan

- 2026-09-22, Ali (gate E2E): lanjut walau JD membatasi lokasi; semua baris peta disetujui satu per satu (match / partial / gap), satu bukti ditambahkan user. Rincian ada di `.jobhunter/` (gitignored), sengaja tidak dicatat di repo.
- 2026-09-22, Claude: `Kind` di peta hanya `required`/`preferred` (kontrak) — tugas & skill → `required`, software → `preferred`.
- 2026-09-22, Claude: bug ditemukan saat E2E — PDF (dan DOCX sejak AJOB-2) keluar mode 0600 karena `mkstemp`; diperbaiki dengan `docx.output_mode()` (TDD, 4 test, mutasi ditangkap).

- 2026-09-22, Ali: **output tailor PDF saja** (`cv.pdf`, `cover-letter.pdf`). Membalik keputusan AJOB-2 "DOCX saja, tanpa PDF". `render-docx` tetap ada di CLI.
- 2026-09-22, Ali: PDF dibuat dengan `render-pdf` stdlib buatan sendiri, bukan konversi LibreOffice, bukan langkah manual.
- 2026-09-22, Ali: peta syarat JD vs master CV **dibahas dulu bersama Ali**; CV baru ditulis setelah semua baris disepakati.
- 2026-09-22, Ali: batasan lokasi JD hanya **peringatan**, tidak memblokir.

## Checklist

### [x] Phase A: keep the real CV out of git
- [x] Write failing test for `.gitignore` listing `data/` as an ignored path (`TestGitignore.test_data_dir_is_ignored`, reads `.gitignore` lines, asserts `"data/"` present). Expected error: `AssertionError: 'data/' not found`
- [x] Run `python3 -m unittest tests.test_manifest -k data_dir`, confirm it fails for that reason
- [x] Add `data/` to `.gitignore` under the existing "runtime user data" comment
- [x] Mutation: remove the line, see the test fail, restore
- [x] Run full suite, confirm green
- [x] Commit: `chore(AJOB-3): ignore data/ — it holds a real candidate's CV`

**Verification:**
- [x] static: `python3 -m compileall -q scripts tests` passes
- [x] unit: `python3 -m unittest discover -s tests -t .` passes
- [x] `git check-ignore data/master-cv.pdf` prints a match — di worktree `.gitignore:6:data/`; di main berlaku setelah merge
- [x] No placeholder/TODO comments in new code

### [x] Phase B: extract `docx.prepare()` without changing docx output
- [x] Write failing test for `docx.prepare("# T\n\nBody\n", "x.md")` returning `([{"kind":"heading","level":1,"text":"T"},{"kind":"paragraph","text":"Body"}], [])`. Expected error: `AttributeError: module 'docx' has no attribute 'prepare'`
- [x] Run it, confirm it fails for that reason
- [x] Before refactoring, record a parity oracle on HEAD: for every `*.md` under `tests/fixtures/` and `tests/samples/` plus 6 inline strings (plain; marker with `allow_unverified=True`; table; nested bullets; entity-escaped marker with allow; fenced code block), render with the current `docx.render` and write the SHA-256 of each `word/document.xml` and its `notes` list into a new test as literals. The test re-renders after the refactor and asserts equality. Do not compute the oracle from a copy of the old code — literals recorded before the change are the only honest oracle — no `tests/samples/` directory exists, so the oracle covers `tests/fixtures/` (`messy_cv.md`, `tailored_cv.md`) plus the 6 inline strings only
- [x] Move the gate/flatten/parse/strip/empty-check body of `docx.render` into `prepare(markdown, label, allow_unverified=False)`; `render` calls it (Contracts section)
- [x] Tests for `prepare` refusals: raises `UnverifiedClaimError` on `"- a [verifikasi]\n"`; raises `EmptyDocumentError` on `""`, on `"   \n"`, and on `"[verifikasi]\n"` with `allow_unverified=True`; writes no file (assert temp dir empty)
- [x] Run full suite — all 553 existing tests plus the new ones green, parity hashes equal — 554 pre-Phase-B (Phase A added one) + 8 new = 562, all green
- [x] Mutation: in `prepare`, skip the residual check; confirm at least one existing docx test fails; restore — 8 existing tests failed (e.g. `test_a_line_breaking_character_is_caught_when_the_blocks_rejoin`, `test_the_second_gate_holds_when_the_first_one_is_blinded`), restored, suite green again
- [x] Commit: `refactor(docx): extract prepare() so a second renderer shares one gate`

**Verification:**
- [x] static: `python3 -m compileall -q scripts tests` passes
- [x] unit: `python3 -m unittest discover -s tests -t .` passes
- [x] parity: every recorded `document.xml` SHA-256 and notes list identical to pre-refactor
- [x] `prepare` touches no filesystem (test asserts temp dir empty after each call)
- [x] No placeholder/TODO comments in new code

### [x] Phase C: `pdf.py` text primitives — encode, widths, wrap
- [x] Write failing test for `pdf.text_width("A", 1000, False) == 667`. Expected error: `ModuleNotFoundError: No module named 'pdf'`
- [x] Run it, confirm it fails for that reason
- [x] Fetch Helvetica / Helvetica-Bold AFM widths (Contracts § Widths) and write `HELVETICA_WIDTHS`, `HELVETICA_BOLD_WIDTHS` with source URL + fetch date comment — fetched `Helvetica.afm` / `Helvetica-Bold.afm` from `github.com/foliojs/pdfkit` (raw, 2026-09-22) plus `aglfn.txt` from `github.com/adobe-type-tools/agl-aglfn` to map WinAnsi byte → AFM glyph name by codepoint, not by memory
- [x] Tests pinning every value listed in Contracts § Widths; test both tuples have exactly 224 entries — all pinned values matched the fetch exactly, no HARD STOP
- [x] Implement `encode`, `text_width`, `wrap`, `PdfError`, `UnsupportedCharacterError`
- [x] Tests for `encode`: `"é · – — •"` encodes; `"\t"` → space; `"→"`, `"中"`, `"😀"` raise `UnicodeEncodeError` (the render-level error is Phase D)
- [x] Tests for `wrap`: `""` → `[]`; one short word → 1 line; text exactly `max_width` → 1 line; one space more → 2 lines; a 200-char word with no spaces → hard-split, every line ≤ `max_width`; multiple spaces collapse to one; property test over 500 seeded random strings (`random.Random(0)`) that no line exceeds `max_width` and `" ".join(lines)` equals the whitespace-normalised input
- [x] Run full suite green; mutation: make `wrap` skip the width check on the last line, see the property test fail, restore — 579 lulus pra-mutasi; mutasi bikin `test_one_point_more_forces_a_second_line` dan property test gagal (baris melebihi `max_width`), dipulihkan
- [x] Commit: `feat(pdf): WinAnsi encoding, Helvetica metrics, line wrapping` — `097c935`

**Verification:**
- [x] static: `python3 -m compileall -q scripts tests` passes
- [x] unit: `python3 -m unittest discover -s tests -t .` passes
- [x] width tables carry a source URL and fetch date; pinned values match
- [x] No placeholder/TODO comments in new code

### [x] Phase D: `pdf.py` layout, writer and `render()` refusals
- [x] Write failing test for `pdf.render("# T\n\nBody\n", <tmp>/cv.pdf)` producing a file that starts with `%PDF-1.4` and ends with `%%EOF\n`. Expected error: `AttributeError: module 'pdf' has no attribute 'render'`
- [x] Run it, confirm it fails for that reason
- [x] Implement `layout` and the writer per Contracts § Layout / § Writer, and `render` per § render order
- [x] Add a test-only PDF reader helper in `tests/test_pdf.py`: parse `startxref`, the xref table, assert each offset points at `"<n> 0 obj"`, assert each stream's `/Length` equals its byte length, extract `(text) Tj` strings in order (unescaping `\\`, `\(`, `\)`, `\ddd`, decoding cp1252)
- [x] Tests: text order equals block order; `(`, `)`, `\` in text round-trip; `é` round-trips via `\351`; letter MediaBox `[0 0 612 792]`, a4 `[0 0 595 842]`; 300 bullets → `pages > 1` and `/Count` equals pages; heading never last line on a page (construct a case); bullet glyph at `MARGIN`, continuation at `MARGIN + 14`; `/Title` equals first heading; same input twice → identical bytes
- [x] Refusal tests, each asserting **no file and no `*.pdf.tmp`** left in the dir: `[verifikasi]` → `docx.UnverifiedClaimError`; empty → `docx.EmptyDocumentError`; missing dir → `docx.DestinationError`; `"a → b\n中\n"` → `pdf.UnsupportedCharacterError` whose message names `U+2192` line 1 and `U+4E2D` line 2
- [x] Gate parity: loop over every marker spelling already pinned in `tests/test_docx.py` (import its fixture list if it exposes one; otherwise copy the list into `test_pdf.py` with a comment naming its source test) and assert `pdf.render` refuses each exactly as `docx.render` does — copied `test_the_override_strips_every_spelling_the_gate_catches`'s `spellings` dict (test_docx.py ~line 1258) into `TestGateParityWithDocx.SPELLINGS`, since it is a local variable there, not exported
- [x] Run full suite green. Mutations: (a) drop the encode-check → the UnsupportedCharacter test fails; (b) write directly to `path` instead of mkstemp → the no-file-on-failure test fails (force a failure after partial write via monkeypatched `os.replace`); restore both — both confirmed and restored
- [x] Commit: `feat(pdf): hand-written PDF 1.4 renderer sharing the docx gate` — `35445ec`

**Verification:**
- [x] static: `python3 -m compileall -q scripts tests` passes
- [x] unit: `python3 -m unittest discover -s tests -t .` passes
- [x] xref offsets and stream lengths verified by the test reader
- [x] every refusal leaves no file and no temp file
- [x] security: input text is escaped in PDF literal strings (no raw `(`/`)`/`\` reaches a content stream); no path outside `--out`'s directory is written
- [x] No placeholder/TODO comments in new code

### [x] Phase E: CLI `render-pdf`
- [x] Write failing test for `main(["render-pdf", "--in", md, "--out", pdf])` exiting 0 with stdout JSON keys `{"out","pages","blocks","notes","bytes"}`. Expected error: `SystemExit`/exit code 1 with `invalid choice: 'render-pdf'`
- [x] Run it, confirm it fails for that reason
- [x] Add `cmd_render_pdf` and its parser block (Contracts § CLI), mirroring `cmd_render_docx`
- [x] Tests: `--out cv.md` → exit 1, stderr JSON `error` = `DestinationError`, input file unchanged; `--out` same file as `--in` → `DestinationError`; `--out X.PDF` accepted; `--page a4` → MediaBox a4; `--page b5` → exit 1 usage error; missing `--in` file → exit 1 JSON, no traceback; `[verifikasi]` input → `UnverifiedClaimError`, no file; `--allow-unverified` → exit 0 and a note reporting markers removed; unsupported char → `UnsupportedCharacterError`; notes echoed to stderr prefixed `render-pdf: `
- [x] Run full suite green; mutation: remove the `.pdf` suffix check, see the `--out cv.md` test fail, restore
- [x] Commit: `feat(cli): render-pdf subcommand`

**Verification:**
- [x] static: `python3 -m compileall -q scripts tests` passes
- [x] unit: `python3 -m unittest discover -s tests -t .` passes
- [x] `python3 scripts/jobhunter.py --help` lists `render-pdf`
- [x] security: `--out` suffix and same-file checks run before any read or write
- [x] No placeholder/TODO comments in new code

### [x] Phase F: `profile` reads a PDF in any tier
- [x] Write failing test for profile SKILL.md stating that any `.pdf` source in any tier is extracted with `mcp__xberg__extract_file` (assert the sentence fragments `any tier` and `.pdf` appear in the same paragraph as `mcp__xberg__extract_file`). Expected error: `AssertionError`
- [x] Run it, confirm it fails for that reason
- [x] Edit Pass 1 step 1 and the "Scripts and MCP tools" bullet: a source path ending in `.pdf` (case-insensitive) in **any** tier — `primary`, `local`, `linkedin_pdf` — is extracted with `mcp__xberg__extract_file`; the native Read tool cannot parse PDF. Other sources keep their reader. Add one example line: `primary = "data/master-cv.pdf"` makes a curated CV PDF the highest-precedence source
- [x] Run full suite green (`TestNoCandidateSpecificContent` included); mutation: revert the prose, see the test fail, restore
- [x] Commit: `feat(profile): extract a PDF source in any tier with xberg`

**Verification:**
- [x] static: `python3 -m compileall -q scripts tests` passes
- [x] unit: `python3 -m unittest discover -s tests -t .` passes
- [x] allow-list prose for `projects` unchanged (diff shows no edit there)
- [x] No placeholder/TODO comments in new code

### [x] Phase G: `tailor` — pasted JD, map, agreement gate, keyword loop, PDF
- [x] Write failing test for tailor SKILL.md stating the agreement gate (`test_tailor_states_agreement_gate`), asserting tailor SKILL.md contains `requirements-map.md`, `approved:`, `jd.md`, `render-pdf`, and the phrase `no cv.md or cover-letter.md is written until` (lowercased compare). Expected error: `AssertionError`
- [x] Run it, confirm it fails for that reason
- [x] Replace `test_render_docx_and_all_three_of_its_flags_are_collected` with `test_render_pdf_and_all_four_of_its_flags_are_collected` asserting `commands["render-pdf"] == {"--in", "--out", "--page", "--allow-unverified"}`; add `test_tailor_no_longer_renders_docx` asserting `render-docx` does not appear in tailor SKILL.md
- [x] Rewrite `skills/tailor/SKILL.md` per the spec §3 flow, in this order: Inputs (queue row, URL, **or pasted JD text** → saved verbatim to `.jobhunter/applications/<slug>/jd.md`; slug from company + title in the JD, **ask the user if either is missing, never guess**); Location check (warn, never block, because a pasted JD bypasses `/ai-jobhunter:score`); Requirements map (format verbatim from this plan's Contracts); **Agreement gate** (walk the map group by group with AskUserQuestion; per row accept / reject pairing / add evidence / confirm gap; added evidence appended to `master-cv.md` with source `user, YYYY-MM-DD`; "No cv.md or cover-letter.md is written until every row is agreed"; write `approved: YYYY-MM-DD`; a map without that line means the gate has not passed); Write (approved rows only; JD wording mirrored only where an approved row evidences it; a `gap` never appears; keep existing no-invention and `verified: false` rules and the "never sent as-is" section verbatim); Keyword loop (`keywords-report` with `--jd` pointing at `jd.md` or the JD file; add missing terms only when an approved row evidences them; at most 2 rounds); Render (`render-pdf` twice, command block from Contracts § CLI with backslash continuation); refusals section rewritten for `render-pdf` naming `UnverifiedClaimError`, `EmptyDocumentError`, `DestinationError`, `UnsupportedCharacterError`; `--allow-unverified` paragraph kept verbatim with `render-docx` → `render-pdf`; Output list: `jd.md` (pasted only), `requirements-map.md`, `cv.md`, `cover-letter.md`, `cv.pdf`, `cover-letter.pdf`, `keyword-report.md`; final print adds map counts (match / partial / gap), approval date, location warning
- [x] Run full suite green (`TestNoCandidateSpecificContent`, documented-flag guards, `test_every_skill_names_the_plugin_root_variable`)
- [x] Mutations: (a) delete the agreement-gate sentence → new test fails; (b) change `--page` to `--paper` in the doc block → documented-flag guard fails; restore both
- [x] Commit: `feat(tailor): pasted JD, requirements map, agreement gate, PDF output`

**Verification:**
- [x] static: `python3 -m compileall -q scripts tests` passes
- [x] unit: `python3 -m unittest discover -s tests -t .` passes
- [x] documented-flag guard collects all 4 `render-pdf` flags — `{"--in", "--out", "--page", "--allow-unverified"}` (`--page` from the fenced block, `--allow-unverified` from the inline `render-pdf --allow-unverified` mention, same pattern render-docx used)
- [x] no candidate-specific strings under `skills/`
- [x] No placeholder/TODO comments in new code

### [x] Phase H: tailoring evals for the new judgement
- [x] Write failing test for the tailoring eval cases (in `tests/test_evals.py`), asserting `docs/evals/tailoring.md` has cases titled `pasted JD`, `agreement gate`, `gap never rendered`. Expected error: `AssertionError`
- [x] Run it, confirm it fails for that reason
- [x] Add three pass@3 cases using existing fictional/real-posting fixtures (not Ali's data): (a) pasted JD → `jd.md` written verbatim, slug asked when company missing; (b) agreement gate → no `cv.md` exists before `approved:` line; (c) gap never rendered → every `gap` row's requirement term absent from `cv.md` and `cover-letter.md` unless an approved row evidences it
- [x] Update "How to run" so outputs listed are the PDF set
- [x] Run full suite green; mutation: rename one case heading, see the test fail, restore
- [x] Commit: `docs(evals): tailoring cases for pasted JD, agreement gate, gaps`

**Verification:**
- [x] static: `python3 -m compileall -q scripts tests` passes
- [x] unit: `python3 -m unittest discover -s tests -t .` passes
- [x] eval cases reference only committed fixtures — Case 7 reuses `04-stripe-staff-product-manager-ai.json`, Case 8 reuses `06-stripe-engineering-manager-agentic-commerce.json`, Case 9 reuses `03-stripe-staff-ml-engineer-phd.json`, all already committed under `docs/evals/fixtures/`
- [x] No placeholder/TODO comments in new code

### [x] Phase I: docs sync and real end-to-end run
- [x] Write failing test for CLAUDE.md's subcommand list naming `render-pdf` (extend the existing manifest/CLAUDE.md guard if one exists; otherwise assert `render-pdf` in CLAUDE.md's "Subcommands:" line). Expected error: `AssertionError`
- [x] Run it, confirm it fails for that reason
- [x] Update CLAUDE.md: subcommand list (11), layout row `scripts/pdf.py` — "markdown → text PDF 1.4. Hand-written, Helvetica/WinAnsi, stdlib only", error classes add `pdf.{PdfError, UnsupportedCharacterError}`, test count **measured** from the suite run
- [x] E2E in the **main checkout's** `.jobhunter/` (gitignored), with Ali present: run `/ai-jobhunter:profile` with `primary = "data/master-cv.pdf"` → `master-cv.md`; run `/ai-jobhunter:tailor` with the City of Hope JD pasted → location warning shown (US-only vs Batam), map written, agreement gate walked with Ali, then `cv.pdf` + `cover-letter.pdf`
- [x] Extract `cv.pdf` back with `mcp__xberg__extract_file`; confirm every heading and bullet text present, in order; record result in the ledger
- [x] Run full suite green; commit docs: `docs(AJOB-3): CLAUDE.md for render-pdf and the tailor gate`

**Verification:**
- [x] static: `python3 -m compileall -q scripts tests` passes
- [x] unit: `python3 -m unittest discover -s tests -t .` passes
- [x] CLAUDE.md test count equals the measured count
- [x] xberg round-trip of the real `cv.pdf` returns complete text in order
- [x] `git status` in main shows nothing under `.jobhunter/`; `data/` still shows as untracked in main until merge brings the `.gitignore` line — never added
- [x] No placeholder/TODO comments in new code

## Phase log

| Phase | Status | Commit |
|---|---|---|
| A — ignore data/ | DONE | `724f41c` |
| B — docx.prepare() | DONE | `ad82ff0` |
| C — pdf primitives | DONE | `097c935` |
| D — pdf renderer | DONE | `35445ec` |
| E — CLI render-pdf | DONE | `480798d` |
| F — profile PDF any tier | DONE | `5a55ed3` |
| G — tailor flow | DONE | `b68328f` |
| H — tailoring evals | DONE | `3afd5fe` |
| I — docs sync | DONE | `2c8b3f2` |
| I — E2E + fix permission 0600 | DONE | `3071678` |
| Fix — verifier round 1 | DONE | `02254c4` |

## Plan-verifier round 1

| Finding | Fix commit | Test | Mutation result |
|---|---|---|---|
| 1. `HELVETICA_WIDTHS`/`HELVETICA_BOLD_WIDTHS` had 0 for `²`/`³`/`¹` (AGLFN has no entry for those codepoints); `encode` didn't treat 0x7F (DEL) as a control char | `ff87e3e` | `TestWidthTablesArePinned.test_superscript_digit_widths_pinned`, `test_every_encodable_cp1252_byte_has_a_positive_width`, `TestEncode.test_del_becomes_a_space` | width table reverted to 0 → 4 subTest gagal; `encode` 0x7F handling direvert → test gagal |
| 2. Unsupported-char line number fell back to a hardcoded `1` for a character `flatten` produces (e.g. `&rarr;` decoded from an entity) | `112cf03` | `TestUnsupportedCharacterLineNumberAfterFlatten` (2 test) | direvert ke fallback `1` → kedua test gagal |
| 3. tailor SKILL.md lost the "prefer a quantified metric" selection rule and the renderer-flattening explanation (tables/images/links/nested bullets) during the render-pdf rewrite | `97df651` | `TestNamedHardRulesInProse.test_tailor_states_the_quantified_metric_preference_and_table_flattening` | kalimat quantified-metric dihapus → test gagal |
| 4. Real candidate name "Ali Sadikin" (space between given name and surname) leaked into tests/ and scripts/ comments; `_CANDIDATE_SPECIFIC_RE` only matched the unbroken word "alisadikin" | `0abf786` | `TestNoCandidateSpecificContentBeyondSkills.test_no_candidate_specific_strings_outside_skills` | nama dikembalikan ke satu file test → guard gagal |
| 5a. `PARITY_ORACLE` didn't cover `docs/evals/` content | `0d44469` | `TestRenderOutputIsUnchangedByThePrepareExtraction.test_every_recorded_case_still_renders_byte_identical` | `docx.BULLET_GLYPH` diubah → 9 kasus baru gagal |
| 5b. `test_pdf.py` had no gate-parity coverage for the 8 line-breaking split spellings `test_docx.py` pins | `0d44469` | `TestGateParityWithDocx.test_pdf_refuses_every_line_breaking_split_spelling_docx_refuses` | residual check (`"".join(rendered)` half) dihapus dari `docx.prepare` → 8 kasus gagal |
| 5c. No test for an unwritable destination directory on `pdf.render` | `0d44469` | `TestUnwritableDestinationDirectory.test_render_refuses_when_the_destination_directory_is_unwritable` | try/except `OSError` di sekitar `mkstemp` dihapus → `PermissionError` mentah lolos, test gagal |

## Utang terbuka

- `pdf._line_for_char` cabang `return None` ("line ?") hanya diuji lewat mock; belum ada input nyata yang mencapainya.
- Layout PDF: baris terakhir bullet bisa sendirian di halaman berikutnya (E2E: "SV." pindah ke hal. 2). Kosmetik; teks & urutan tetap utuh di xberg. Belum ada widow/orphan control untuk bullet.

design-artifact: skipped — Ali: mau cepat, prioritas hasil bukan visual (2026-09-22)

## Plan-verifier round 2

| Finding | Fix | Test | Mutation |
|---|---|---|---|
| #7 flatten assertion `"table"` matched "stable" | `62547fd` | `test_tailor_states_the_quantified_metric_preference_and_table_flattening` | flatten paragraph deleted → FAILED |
| advisory: beyond-skills guard fail-open on missing root | `62547fd` | `test_no_candidate_specific_strings_outside_skills` | root `docs/evalz` → FAILED "scan root missing" |
| advisory: `_line_for_char` final `return None` uncovered by a real input | not fixed | — | no real input reaches it (verifier); recorded as debt |

Round 2 verdict before this fix: BLOCKING on #7 only; all other round-1 items CLOSED.

## Log
- 2026-09-22 plan ditulis — NEXT: Phase A
- 2026-09-22 Phase A done — suite 554 lulus, mutasi (hapus baris) → test gagal — NEXT: Phase B
- 2026-09-22 Phase B done — 562 lulus, parity 8 input sama, mutasi → test_a_line_breaking_character_is_caught_when_the_blocks_rejoin gagal — NEXT: Phase C
- 2026-09-22 Phase C done — 579 lulus, AFM dari github.com/foliojs/pdfkit (raw, 2026-09-22), mutasi → test_one_point_more_forces_a_second_line + property test gagal — NEXT: Phase D
- 2026-09-22 Phase D done — 597 lulus, mutasi (a) hapus encode-check → UnsupportedCharacter test gagal (jadi UnicodeEncodeError mentah), mutasi (b) tulis langsung ke --out tanpa mkstemp → no-file-on-failure test gagal (DestinationError tak pernah terlempar) — NEXT: Phase E
- 2026-09-22 Phase E done — 612 lulus, mutasi → test_an_out_that_is_not_a_pdf_is_refused gagal — NEXT: Phase F
- 2026-09-22 Phase F done — 613 lulus, mutasi (revert prosa) → test_profile_states_pdf_in_any_tier_uses_xberg gagal — NEXT: Phase G
- 2026-09-22 Phase G done — 615 lulus, mutasi (a) hapus kalimat agreement-gate → test_tailor_states_agreement_gate gagal, mutasi (b) --page → --paper di blok perintah → test_every_documented_flag_exists_on_its_subcommand gagal — NEXT: Phase H
- 2026-09-22 Phase H done — 618 lulus, mutasi (ganti judul "agreement gate" → "approval gate") → test_agreement_gate_case_present gagal — NEXT: Phase I
- 2026-09-22 Phase I bagian docs done — 619 lulus, guard Subcommands CLAUDE.md dimutasi → gagal — NEXT: Phase I E2E bersama Ali (profile dari data/master-cv.pdf, tailor JD City of Hope)
- 2026-09-22 Phase I done — E2E: profile dari data/master-cv.pdf → master-cv.md; tailor City of Hope: peta 28 baris (match 14 / partial 7 / gap 7), gate disetujui Ali, keyword loop 1 putaran (covered 93→105), cv.pdf 2 hal 54 blok, cover-letter.pdf 1 hal 10 blok, round-trip xberg utuh & berurutan; fix mode 0600 `3071678` — mutasi (hapus `os.chmod` di pdf.py) → `TestOutputPermissions.test_a_new_pdf_gets_the_mode_open_would_give_it` dan `test_a_re_render_keeps_the_existing_files_mode` gagal (2), mutasi (hapus `os.chmod` di docx.py) → `test_docx_follows_the_same_rule` gagal (1); 623 lulus — NEXT: gaspol-verify + plan-verifier
- 2026-09-22 verifier round 1 fixes done — 632 lulus, 8 mutasi semua tertangkap — NEXT: plan-verifier round 2
- 2026-09-22 verifier round 2 — 1 BLOCKING (#7) diperbaiki `62547fd` + advisory scan-root; 632 lulus, 2 mutasi tertangkap — NEXT: gaspol-finish (merge keputusan Ali)
- 2026-09-22 versi 0.2.0; merge ke master + push + install diminta Ali — NEXT: DONE

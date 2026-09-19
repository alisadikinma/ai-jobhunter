# PROGRESS — AJOB-2: ATS-friendly DOCX rendering

**Ticket:** AJOB-2
**Plan:** docs/plans/2026-09-19-AJOB-2-ats-docx-rendering-plan.md
**Spec:** docs/plans/2026-09-19-AJOB-2-ats-docx-rendering-spec.md

## Pre-flight

| Gate | Result |
|---|---|
| Git clean | PASS — baseline `263d58d`, 0 berkas belum ter-commit |
| Baseline suite | PASS — `python3 -m unittest discover -s tests -t .`, 262 lulus / 0 gagal |
| detect-stack | nol baris (tidak ada penanda stack) — perintah dari plan: static `python3 -m compileall -q scripts tests`, unit `python3 -m unittest discover -s tests -t .` |
| Feasibility | PASS — penulis OOXML stdlib dibuktikan 2026-09-19: 1.749 byte, zip valid, terekstrak dengan struktur heading utuh |

## Keputusan saat jalan

- 2026-09-19, Ali: **DOCX saja, tanpa PDF.** Diukur: stdlib tak punya PDF writer, pandoc gagal tanpa `pdflatex`, cupsfilter cuma cetak sumber markdown. PDF jadi langkah manual Ali dari Word.
- 2026-09-19, Ali: renderer **menolak dan tidak menulis file** kalau ketemu `[verifikasi]` / `[Assumption]`, bukan sekadar memperingatkan.
- 2026-09-19, Ali: tabel dan gambar **diratakan jadi teks**, bukan ditolak — mesin bisa beres sendiri, tak perlu Ali bolak-balik.
- 2026-09-19, Ali: subcommand CLI `render-docx` yang dipanggil `tailor`, bukan skill ketujuh.
- 2026-09-19, Claude: gaya **tidak bisa dikonfigurasi** (Calibri 11pt, satu kolom, margin 2cm). Setiap opsi gaya adalah cara baru menghasilkan CV yang gagal parsing.

## Checklist

### [x] Phase A: markdown → blocks
- [x] Write failing test for `docx.parse_blocks("# Ali\n\nHello\n")` returning `[{"kind": "heading", "level": 1, "text": "Ali"}, {"kind": "paragraph", "text": "Hello"}]`. Expected error: `ModuleNotFoundError: No module named 'docx'`
- [x] Run `python3 -m unittest discover -s tests -t .`, confirm it fails for that reason
- [x] Implement `parse_blocks(markdown)` per the Block contract above: `#`/`##`/`###` → heading with level; `-` or `*` at column 0 → bullet; a blank-line-separated run of text → paragraph. Inline `**bold**`, `*italic*` and `` `code` `` markers are stripped from the text (Word carries the style, not the asterisks)
- [x] Add tests for the enumerated edge cases: empty string, whitespace-only, a heading with no text (`##` alone), `####` (level 4 — treated as a paragraph, not a heading, because the style table stops at 3), a bullet with no text, CRLF line endings, a line that is only `---`, two blank lines between paragraphs, 500 blocks, and text containing `&`, `<`, `>`
- [x] Run tests, confirm all pass
- [x] Commit: "feat(docx): parse the supported markdown subset into blocks"
- [x] `python3 -m compileall -q scripts tests` passes
- [x] `python3 -m unittest discover -s tests -t .` passes
- [x] `parse_blocks` emits only `heading`/`paragraph`/`bullet`, proven by a test that asserts the set of `kind` values over a real fixture
- [x] `####` yields a paragraph, not a level-4 heading
- [x] No placeholder/TODO comments in new code
- [x] detect-stack: no stack markers for this project — verification is plan-declared only

### [x] Phase B: the unverified-claim gate
- [x] Write failing test for `docx.ats_lint("- revenue up 40% [verifikasi]\n")` returning one finding with `reason == "unverified-claim"` and `line == 1`. Expected error: `AttributeError: module 'docx' has no attribute 'ats_lint'`
- [x] Run tests, confirm it fails for that reason
- [x] Implement `ats_lint(markdown)` returning findings per the Lint finding contract. Detect `[verifikasi]` and `[Assumption]` **case-insensitively**, anywhere on the line. Also detect and report (without refusing) `table`, `image`, `deep-nesting`, `html`
- [x] Implement `UnverifiedClaimError(Exception)` carrying `.findings`, with a message naming the file, the line number and the offending text, e.g. `cv.md:14 — "increased revenue 40% [verifikasi]"`
- [x] Add tests for the enumerated edge cases: marker in a heading, marker inside a fenced code block (**still refuses** — a CV has no reason to carry code fences, and a marker there is far more likely a real claim than a deliberate literal), `[VERIFIKASI]` uppercase, `[ Assumption ]` with inner spaces (**not** a match — the convention is exact, and loosening it invites false positives), two markers on one line (one finding, not two), a marker on the last line with no trailing newline, and markdown with no markers at all (empty finding list)
- [x] Run tests, confirm all pass
- [x] Commit: "feat(docx): refuse to render a claim the candidate never verified"
- [x] `python3 -m compileall -q scripts tests` passes
- [x] `python3 -m unittest discover -s tests -t .` passes
- [x] A markdown file carrying `[verifikasi]` produces a finding whose `line` matches the real 1-based line number, proven against a multi-line fixture
- [x] `[ Assumption ]` with inner spaces produces no finding
- [x] Mutation check: delete the `[Assumption]` half of the pattern and confirm a test fails — a guard that guards only half of what it claims is this repository's documented recurring defect
- [x] No placeholder/TODO comments in new code
- [x] detect-stack: no stack markers for this project — verification is plan-declared only

### [x] Phase C: ATS flattening
- [x] Write failing test for `docx.flatten("| Skill | Years |\n|---|---|\n| Python | 8 |\n")` returning markdown with no `|` characters and a line reading `Skill: Python — 8`. Expected error: `AttributeError: module 'docx' has no attribute 'flatten'`
- [x] Run tests, confirm it fails for that reason
- [x] Implement `flatten(markdown)` returning `(flattened_markdown, notes)` where `notes` is a list of strings for stderr. Transformations, all of them from spec §4 gate 2:
- [x] - **table** → one line per body row, `"<header1>: <cell1> — <cell2>"`, the separator row dropped
- [x] - **image** `![alt](src)` → removed entirely; note records the `src`
- [x] - **link** `[text](url)` → `text (url)`, because ATS frequently keep neither the anchor nor the href
- [x] - **nesting deeper than one level** → flattened to one level
- [x] - **inline HTML** → stripped via `ats._clean_description`, imported rather than reimplemented
- [x] Add tests for the enumerated edge cases: a table with one column, a table with a missing cell (pad with empty string, never drop the row), a table with no header separator (treated as paragraphs, not a table), an image with no alt text, a link whose text equals its url (emit the text once, not `url (url)`), a reference-style link `[text][ref]` (left as-is — out of scope, noted), three-level nesting, an empty table, and markdown containing a literal `|` inside a normal sentence (must NOT be treated as a table)
- [x] Run tests, confirm all pass
- [x] Commit: "feat(docx): flatten what an ATS parses badly, refuse nothing"
- [x] `python3 -m compileall -q scripts tests` passes
- [x] `python3 -m unittest discover -s tests -t .` passes
- [x] `flatten` output, fed to `parse_blocks`, yields only `heading`/`paragraph`/`bullet` — the Phase A invariant holds on real flattened input
- [x] A sentence containing a literal `|` survives unflattened
- [x] `ats._clean_description` is imported, not reimplemented (assert by grepping the module for a second HTML stripper)
- [x] No placeholder/TODO comments in new code
- [x] detect-stack: no stack markers for this project — verification is plan-declared only

### [ ] Phase D: the OOXML writer
- [ ] Write failing test for `docx.render("# Ali\n", path)` producing a file whose `zipfile.ZipFile(path).namelist()` equals the five parts listed in "The five OOXML parts" above. Expected error: `AttributeError: module 'docx' has no attribute 'render'`
- [ ] Run tests, confirm it fails for that reason
- [ ] Implement `render(markdown, path)`: run `ats_lint` → raise `UnverifiedClaimError` on any `unverified-claim` finding (unless `allow_unverified=True`), then `flatten`, then `parse_blocks`, then emit the five parts with `zipfile.ZIP_DEFLATED`. Use the style table and the escaping order pinned above
- [ ] Write to a temp file in the destination directory and `os.replace` it into place, so a failure never leaves a half-written `.docx` — the same atomic-write pattern `scripts/jobq.py::update_rows` already uses
- [ ] Add tests for the enumerated edge cases: empty markdown (**refuse** — `EmptyDocumentError`; an empty CV is never the intent), whitespace-only markdown (same), a single heading and nothing else, 500 blocks, text containing `&`/`<`/`>` (assert the escaping order by round-tripping `a & b < c`), non-ASCII (`—`, `é`, `日本語`), a destination directory that does not exist, and a destination that is not writable
- [ ] Round-trip test: write a `.docx`, reopen it with `zipfile`, assert `testzip() is None` and that `word/document.xml` parses under `xml.etree.ElementTree` — a well-formedness check the writer cannot fake
- [ ] Run tests, confirm all pass
- [ ] Commit: "feat(docx): write the OOXML parts, atomically"
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] Generated `.docx` is a valid ZIP (`testzip() is None`) and `word/document.xml` is well-formed XML
- [ ] `a & b < c` round-trips exactly — proves the escaping order
- [ ] A failed render leaves no file at the destination path
- [ ] Empty and whitespace-only markdown both raise `EmptyDocumentError`
- [ ] No placeholder/TODO comments in new code
- [ ] detect-stack: no stack markers for this project — verification is plan-declared only

### [ ] Phase E: CLI subcommand and skill wiring
- [ ] Write failing test for `main(["render-docx", "--in", md_path, "--out", docx_path])` exiting 0 and printing JSON carrying `{"out": ..., "blocks": <int>, "notes": [...]}`. Expected error: `SystemExit: 1` with `{"error": "UsageError", "message": "argument command: invalid choice: 'render-docx'"}`
- [ ] Run tests, confirm it fails for that reason
- [ ] Add `cmd_render_docx` and its subparser: `--in` (required), `--out` (required), `--allow-unverified` (`store_true`, help text stating it is an opt-in escape from a safety gate and never a config default)
- [ ] Emit `notes` on stdout as part of the JSON **and** on stderr as human lines — stdout is the parsed channel, stderr is the one a person reads
- [ ] Extend `skills/tailor/SKILL.md`: the command block, what a refusal looks like, and the rule that `--allow-unverified` is Ali's decision per run, never the skill's
- [ ] Update `CLAUDE.md`: add `render-docx` to the subcommand list and `scripts/docx.py` to the Layout table
- [ ] Add tests: `render-docx` on markdown containing `[verifikasi]` returns exit 1 with `{"error": "UnverifiedClaimError"}` and **writes no file** (assert `os.path.exists(out) is False`); the same input with `--allow-unverified` exits 0 and writes the file; a missing `--in` is a `UsageError`
- [ ] Run tests, confirm all pass
- [ ] Commit: "feat(cli): render-docx, wired into tailor"
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] `tests/test_manifest.py` collects `render-docx` and all three of its flags — run `_documented_commands()` and assert they appear, since that guard was twice found vacuous in AJOB-1
- [ ] Mutation check: document `--alow-unverified` in `skills/tailor/SKILL.md`, confirm the manifest test FAILS, revert
- [ ] A refused render leaves no file on disk, asserted not assumed
- [ ] `CLAUDE.md` lists `render-docx` and `scripts/docx.py`
- [ ] No placeholder/TODO comments in new code
- [ ] detect-stack: no stack markers for this project — verification is plan-declared only

### [ ] Phase F: does it actually open?
- [ ] Write failing test for the presence of `docs/evals/docx-rendering.md` and its declaring at least one case per target application. Expected error: `AssertionError: missing docs/evals/docx-rendering.md`
- [ ] Run tests, confirm it fails for that reason
- [ ] Write `docs/evals/docx-rendering.md` with one case each for **Microsoft Word**, **Google Docs** and **LibreOffice**: open the generated file, confirm headings render as headings, bullets as bullets, and that no markdown syntax is visible. Each case names the exact file to open and what a pass looks like
- [ ] Generate a sample `.docx` from a real tailored CV into `docs/evals/samples/` and commit it, so the manual check has a fixed artifact rather than one the checker must first produce
- [ ] Run tests, confirm all pass
- [ ] **Hand the manual check to the owner.** Do NOT tick it. Record in the ledger under `## Utang terbuka`: `Word / Google Docs / LibreOffice open-check: NOT RUN — needs Ali, cannot be verified from the session`
- [ ] Commit: "test(docx): eval cases for the one thing a program cannot check"
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] `docs/evals/docx-rendering.md` exists and names all three applications
- [ ] A sample `.docx` is committed under `docs/evals/samples/`
- [ ] The manual open-check is recorded as **NOT RUN** in the ledger, not ticked
- [ ] No placeholder/TODO comments in new code
- [ ] detect-stack: no stack markers for this project — verification is plan-declared only

## Phase log

| Phase | Status | Commit |
|---|---|---|
| A — parse blok markdown | TODO | — |
| B — gerbang klaim tak terverifikasi | TODO | — |
| C — perataan ATS | TODO | — |
| D — penulis OOXML | TODO | — |
| E — subcommand CLI + wiring skill | TODO | — |
| F — apakah benar-benar bisa dibuka | TODO | — |

## Utang terbuka

- Word / Google Docs / LibreOffice open-check: **NOT RUN** — butuh Ali, tidak bisa diverifikasi dari dalam sesi. Phase F menulis kasus eval-nya; centangnya bukan milik Claude.

## Log
- 2026-09-19 plan ditulis — NEXT: Phase A
- 2026-09-19 Phase A selesai — `scripts/docx.py::parse_blocks` + 26 test baru, 288 lulus / 0 gagal. Cacat ditemukan saat dijalankan pada CV nyata: bullet yang terbungkus ke baris berikut pecah jadi paragraf liar; baris berindentasi sekarang menyambung bullet di atasnya. Commit `feat(docx): parse the supported markdown subset into blocks`. — NEXT: Phase B
- 2026-09-19 Phase B selesai — `ats_lint` + `unverified_findings` + `UnverifiedClaimError`, 318 lulus / 0 gagal. Mutation check: buang separuh `[Assumption]` → 1 test gagal; buang `re.I` → 3 gagal; buang syarat baris pemisah tabel → MASIH HIJAU pada percobaan pertama karena test pipa-literal cuma satu baris, dan satu baris tak pernah bisa jadi tabel. Ditambal 3 kasus multi-baris, mutasi yang sama sekarang gagal ketiganya. Commit `feat(docx): refuse to render a claim the candidate never verified`. — NEXT: Phase C
- 2026-09-19 Phase C selesai — `flatten` + `find_tables` + `strip_html`, 355 lulus / 0 gagal. Dua cacat baru muncul saat dijalankan pada CV berantakan nyata: (1) `ats._TAG_RE` = `<[^>]+>` memakan tengah kalimat "p95 < 200ms dan > 1k rps" — kurung sudut di luar tag asli sekarang disembunyikan dulu di balik sentinel, `ats._clean_description` tetap yang menghapus tag; (2) tabel satu kolom tidak terdeteksi karena pola pemisah menuntut minimal dua sel. Mutation check: buang proteksi non-tag / buang pad "N/A" / buang padding baris pendek — ketiganya gagal test. Commit `feat(docx): flatten what an ATS parses badly, refuse nothing`. — NEXT: Phase D

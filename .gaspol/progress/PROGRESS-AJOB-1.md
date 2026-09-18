# PROGRESS — AJOB-1: ai-jobhunter end-to-end pipeline plugin

**Ticket:** AJOB-1
**Plan:** docs/plans/2026-09-19-AJOB-1-ai-jobhunter-pipeline-plan.md
**Spec:** docs/plans/2026-09-19-AJOB-1-ai-jobhunter-pipeline-spec.md

## Pre-flight

| Gate | Result |
|---|---|
| Git clean | PASS — repo initialised 2026-09-19, baseline `2b5ae37` (spec + plan + ledger committed) |
| Baseline suite | N/A — no code and no tests exist yet; Phase A's failing test is the first run |
| detect-stack | zero lines (no stack markers; project was empty). Plan-declared: static `python3 -m compileall -q scripts tests`, unit `python3 -m unittest discover -s tests -t . -v` |
| Python | 3.14.7 present; pytest NOT installed, ruff NOT installed — stdlib `unittest` used deliberately |
| jobsync | running at http://localhost:3737, `/api/mcp` returns 401 without a token (correct); MCP token NOT yet generated |

## Keputusan saat jalan

- 2026-09-19 — ATS endpoints diverifikasi hidup (Greenhouse/stripe 667 lowongan, Lever/leverdemo 11, Ashby/ramp 148). Nol pendaftaran, nol kunci API. Diputuskan Ali + Claude; endpoint dan peta field masuk ke plan Fase C.
- 2026-09-19 — `fetch` wajib streaming ke berkas: satu board Greenhouse 5,1 MB. Diputuskan Claude setelah mengukur, bukan memperkirakan.
- 2026-09-19 — Master CV disusun dari banyak sumber lewat 4 langkah (ingest/extract/reconcile/render) dengan asal-usul per butir. Urutan kuasa: identity card > catatan pribadi lain > project > LinkedIn PDF > situs pribadi > situs produk. Diputuskan Ali.
- 2026-09-19 — `_normalize_url` DIPERBAIKI: buang hanya parameter pelacak (`utm_*`, `ref`, `gclid`, dst.), pertahankan parameter identitas, urutkan sisanya. Diputuskan Claude setelah mengukur. Versi pertama membuang seluruh query dan meruntuhkan 667 lowongan Stripe jadi 1 kunci — rencana asli ("dua URL beda hanya di query = sama") yang keliru, bukan kesalahan implementer.
- 2026-09-19 — Kontrak field baris ter-skor DIKUNCI di plan (`fit_score`, `score_reasons`, `work_authorization`, `suggested_variant`, `skills`). Diputuskan Claude setelah implementer Fase E melaporkan nama field skill belum ditentukan — supaya Fase F tidak menulis nama lain.
- 2026-09-19 — Ketidakcocokan tanda hubung (`end-to-end` lawan `end to end`) SENGAJA dilaporkan sebagai missing, bukan covered. Diputuskan Claude. Salah-lapor "belum tertutup" cuma bikin manusia melirik; salah-lapor "sudah tertutup" bikin dia melewatkan celah nyata sebelum mengirim lamaran.
- 2026-09-19 — Simpulan `workplaceType` Greenhouse DIPERBAIKI: baca hanya dari kata yang menyatakan pengaturan kerja; nama tempat saja berarti field absen. Diputuskan Claude setelah mengukur board asli — 560 dari 667 lokasi cuma nama tempat dan NOL menyebut hybrid/onsite, tapi aturan lama melabeli 329 sebagai `Onsite`. Sebaliknya koma tidak lagi memveto kata yang sudah dinyatakan: `Remote` naik 31 → 107.
- 2026-09-19 — Kosakata tingkat precedence DISATUKAN jadi lima: local-primary, local, project, linkedin-pdf, site. `product-site` dihapus (tidak punya field; urutan situs diatur lewat urutan `sites`). Tingkat tak dikenal sekarang `PrecedenceError`, bukan nol entri diam-diam — satu salah ketik tidak boleh membuang satu kelas sumber sementara CV terlihat lengkap. Diputuskan Claude; cacat asalnya di spec, ditemukan implementer Fase B.
- 2026-09-19 — Catatan project dipakai lewat DAFTAR PUTIH di config, bukan penyaringan. Diputuskan Ali. Alasan terukur: cuma 9 dari 76 berkas punya penanda `sensitivity:`, jadi mode "semua kecuali internal" akan meloloskan 67 berkas tak bertanda yang memuat harga dan status negosiasi klien.

## Checklist

### [x] Phase A: local queue — append, dedupe, read
- [x] Write failing test for `jobq.append_rows` writing one JSONL line per row to a temp queue path. RED seen: `ModuleNotFoundError: No module named 'jobq'`
- [x] Run `python3 -m unittest discover -s tests -t . -v`, confirm it fails for that reason
- [x] Implement `scripts/jobq.py` with `load`, `append_rows`, `row_key`, `iter_unscored`
- [x] Add tests for empty file, missing file, no jobUrl, URL query-string difference, duplicate, malformed line, 1000 rows, trailing whitespace
- [x] Run tests, confirm all pass — 14 tests, OK
- [x] Commit: "feat(queue): local JSONL work queue with URL-and-identity dedupe" — `f910b60`, fix in follow-up commit

**Verification:**
- [x] `python3 -m compileall -q scripts tests` passes — exit 0
- [x] `python3 -m unittest discover -s tests -t . -v` passes — 14 tests, OK
- [x] A malformed line is counted and skipped, and does not abort the read
- [x] Re-appending an identical row writes nothing and reports one skipped duplicate
- [x] URL dedupe keeps identifying params: 667 real Stripe postings → 667 keys; 148 Ashby → 148
- [x] No placeholder/TODO comments in new code

### [x] Phase B: config + profile paths
- [x] Write failing test for `config.load` reading `.jobhunter/config.toml`. RED seen: `ModuleNotFoundError: No module named 'config'`
- [x] Run tests, confirm it fails for that reason
- [x] Implement `scripts/config.py` with `tomllib` and explicit budget defaults
- [x] Add tests for missing file, malformed TOML, unknown key, min_salary_usd absent vs 0, relative path resolution
- [x] Implement `resolve_profile_sources(cfg)` — ordered (tier, path) list; project dirs ALLOW-LISTED, root never scanned
- [x] Add allow-list tests: dir on disk but not allowed is never returned; allowed-but-missing raises; `..` or absolute path rejected; empty allowed returns none; exact match, no globs
- [x] Write `templates/config.toml` (verbatim from spec §4, diffed to confirm)
- [x] Run tests, confirm all pass — 36 tests (14 Phase A + 22 Phase B), OK
- [x] Commit: "feat(config): TOML config loader with explicit budget defaults" — `9dbd9b8`

**Verification:**
- [x] `python3 -m compileall -q scripts tests` passes — exit 0
- [x] `python3 -m unittest discover -s tests -t . -v` passes — 36 tests, OK
- [x] `min_salary_usd = 0` and an absent key both resolve to "unset", not to a zero floor — both normalise to Python `None`, the only unambiguous sentinel (see `scripts/config.py` module docstring)
- [x] A missing config raises an error naming the skill that creates it — `ConfigMissingError` message contains `/ai-jobhunter:profile`
- [x] A project directory present on disk but absent from `allowed` is never returned — tested directly, plus a "root never scanned" test with 4 real directories on disk and only 1 allow-listed
- [x] An `allowed` entry containing `..` or an absolute path is rejected — `ProjectSourceError`, also covers bare path separators
- [x] No placeholder/TODO comments in new code — verified by grep

### [x] Phase C: ATS fetchers (Greenhouse, Lever, Ashby)
- [ ] Write failing test for `ats.normalize_greenhouse(fixture)`. Expected error: `ModuleNotFoundError: No module named 'ats'`
- [ ] Run tests, confirm it fails for that reason
- [ ] Record three fixtures to disk (trimmed from the verified live endpoints in the plan) so no test touches the network
- [ ] Implement `scripts/ats.py` with streaming `fetch(board, slug, dest)` separated from pure `normalize_<board>(path)` — boards reach 5 MB
- [ ] Add tests for empty list, no location, HTML description, sub-10-char description, non-JSON body, 404 with `Document not found`, timeout, Ashby `isListed: false`, unmappable Greenhouse location
- [ ] Run tests, confirm all pass
- [ ] Commit: "feat(ats): Greenhouse/Lever/Ashby fetch and normalisation"

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t . -v` passes
- [ ] No test performs network I/O (grep the test dir for `urlopen` returns nothing)
- [ ] A description under 10 characters normalises to `"N/A"`, satisfying the jobsync minimum
- [ ] An unmappable Greenhouse location leaves `workplaceType` absent rather than guessing
- [ ] An Ashby row with `isListed: false` is dropped
- [ ] No placeholder/TODO comments in new code

### [x] Phase D: keyword coverage report
- [ ] Write failing test for `keywords.coverage(jd_text, cv_text)`. Expected error: `ModuleNotFoundError: No module named 'keywords'`
- [ ] Run tests, confirm it fails for that reason
- [ ] Implement extraction, stopword removal and comparison
- [ ] Add tests for empty JD, empty CV, substring false positives, hyphenation, casing, repeats, non-ASCII
- [ ] Implement `render(report)` whose heading states keyword overlap, not ATS score
- [ ] Run tests, confirm all pass
- [ ] Commit: "feat(keywords): JD-vs-CV coverage report"

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t . -v` passes
- [ ] `java` in the CV does not mark `javascript` covered, nor the reverse
- [ ] The rendered heading says keyword overlap and does not claim an ATS score
- [ ] No placeholder/TODO comments in new code

### [x] Phase E: promote — payload building and request budget
- [ ] Write failing test for `promote.to_add_job(row)` producing `upsert: True` and a canonical `workplaceType`. Expected error: `ModuleNotFoundError: No module named 'promote'`
- [ ] Run tests, confirm it fails for that reason
- [ ] Implement `to_add_job`, `to_match_text`, `build_tags`, `chunk`, `plan_budget`
- [ ] Add tests for missing description, `On-site` and `REMOTE`, every recommendation boundary (80/79/65/64/50/49/0/100), 11 skill tags, batches of 10 and 11, budget 0, short matchText
- [ ] Run tests, confirm all pass
- [ ] Commit: "feat(promote): jobsync payload mapping with tag cap and request budget"

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t . -v` passes
- [ ] Every generated `matchText` begins with a `SCORES:` line matching `^SCORES: match=\d{1,3} recommendation=(strong|good|partial|weak)$`
- [ ] `tags` never exceeds 10 and always retains the visa tag and the variant tag
- [ ] Batches never exceed 10 items
- [ ] No placeholder/TODO comments in new code

### [ ] Phase F: the six skills and the plugin manifest
- [ ] Write failing test asserting `.claude-plugin/plugin.json` parses and every `skills/*/SKILL.md` declares name and description. Expected error: `FileNotFoundError: .claude-plugin/plugin.json`
- [ ] Run tests, confirm it fails for that reason
- [ ] Write `.claude-plugin/plugin.json`
- [ ] Write the six SKILL.md files, with `promote` the only one allowed to call jobsync MCP
- [ ] `profile`'s SKILL.md spells out the four passes (ingest / extract / reconcile / render), the tier precedence, the `verified: false` suppression rule, and the project allow-list rule
- [ ] Read `jobhunter-plugin/refs/` for prior art before writing `tailor` and `outreach`
- [ ] Run tests, confirm all pass
- [ ] Commit: "feat(skills): six pipeline skills and plugin manifest"

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t . -v` passes
- [ ] No SKILL.md bundles any candidate-specific value — grep for `alisadikin`, `INDUSIA` and `Obsidian` across `skills/` returns nothing
- [ ] `tailor`'s SKILL.md states that reading the target job description is mandatory and that `master-cv.md` is never sent as-is
- [ ] `outreach`'s SKILL.md contains no send path, only draft creation
- [ ] `profile`'s SKILL.md states the `verified: false` suppression rule and the project allow-list rule
- [ ] No placeholder/TODO comments in new code

### [ ] Phase G: evals for the judgement steps
- [ ] Write failing test asserting each eval file exists and names ≥5 cases. Expected error: `FileNotFoundError: docs/evals/scoring.md`
- [ ] Run tests, confirm it fails for that reason
- [ ] Collect ≥6 real job descriptions into `docs/evals/fixtures/`
- [ ] Write `docs/evals/scoring.md` with capability and regression cases
- [ ] Write `docs/evals/tailoring.md` with anti-fabrication criteria
- [ ] Write `docs/evals/profile.md`: precedence resolution, same-tier conflict goes to conflicts.md, `[verifikasi]` claim suppressed, two same-number different-subject claims not fused, every bullet names a source
- [ ] Run tests, confirm all pass
- [ ] Commit: "test(evals): scoring and tailoring eval suites with real fixtures"

**Verification:**
- [ ] `python3 -m compileall -q scripts tests` passes
- [ ] `python3 -m unittest discover -s tests -t . -v` passes
- [ ] All three eval files name ≥5 cases each with explicit pass criteria
- [ ] The "no sponsorship" fixture is a named regression case expecting `closed`
- [ ] The model-research fixture is a named regression case expecting a **low** role-fit score
- [ ] `docs/evals/profile.md` has a named case proving a `[verifikasi]` claim is suppressed
- [ ] No placeholder/TODO comments in new code

## Phase log

| Phase | Status | Commit |
|---|---|---|
| A — local queue | DONE | `f910b60` + fix |
| B — config | DONE | `9dbd9b8` |
| C — ATS fetchers | DONE | `5998380` + fix |
| D — keyword coverage | DONE | `8e2033d` |
| E — promote | DONE | `92dce2a` |
| F — skills + manifest | TODO | — |
| G — evals | TODO | — |

## Utang terbuka

- jobsync MCP token belum dibuat — promote hanya bisa diuji unit, belum end-to-end.
- Ketersediaan Gmail MCP belum diverifikasi — jalur cadangan `.eml` wajib ditulis.
- Export PDF LinkedIn adalah langkah manual user, tidak bisa diotomatiskan.

design-artifact: approved — https://claude.ai/artifact/HjE6YSXbX9Ptu8fvqnfiYG

## Log
- 2026-09-19 plan ditulis — NEXT: Phase A
- 2026-09-19 Phase A done — `python3 -m unittest discover -s tests -t .` 14 lulus / 0 gagal; dedupe diuji lawan data asli Greenhouse (667→667) dan Ashby (148→148) — NEXT: Phase B
- 2026-09-19 Phase B done — `python3 -m unittest discover -s tests -t .` 37 lulus / 0 gagal; daftar putih diuji terpisah: folder rahasia tidak pernah dikembalikan, `..` / jalur absolut / `sub/dir` ditolak, `min_salary_usd = 0` jadi `None` — NEXT: Phase C
- 2026-09-19 Phase C done — `python3 -m unittest discover -s tests -t .` 67 lulus / 0 gagal; tiga board asli dinormalisasi utuh (Greenhouse 667, Lever 11, Ashby 148), nol tes menyentuh jaringan — NEXT: Phase D
- 2026-09-19 Phase D done — `python3 -m unittest discover -s tests -t .` 85 lulus / 0 gagal; diuji mandiri: java/javascript tidak saling mencemari dua arah, non-ASCII aman, judul tidak mengklaim skor ATS — NEXT: Phase E
- 2026-09-19 Phase E done — `python3 -m unittest discover -s tests -t .` 136 lulus / 0 gagal; diuji mandiri lawan baris Ashby asli: upsert menyala, nol field di luar kontrak, baris SCORES sah, tag visa+variant selamat dari potongan, 100 baris @ jatah 60 → (30, 70, 60) — NEXT: Phase F
- 2026-09-19 Phase D done — `python3 -m unittest discover -s tests -t .` 85 lulus / 0 gagal; diuji mandiri: java/javascript tidak saling mencemari dua arah, non-ASCII aman, judul tidak mengklaim skor ATS — NEXT: Phase E
- 2026-09-19 Phase C done — `python3 -m unittest discover -s tests -t .` 67 lulus / 0 gagal; tiga board asli dinormalisasi utuh (Greenhouse 667, Lever 11, Ashby 148), nol tes menyentuh jaringan — NEXT: Phase D
- 2026-09-19 Phase B done — `python3 -m unittest discover -s tests -t .` 36 lulus / 0 gagal (14 Phase A + 22 Phase B); `min_salary_usd` absen dan `0` sama-sama jadi `None` di `scripts/config.py`, satu-satunya sentinel yang tidak ambigu; allow-list proyek diuji termasuk kasus root berisi 4 folder nyata tapi cuma 1 yang di-allow-list — NEXT: Phase C

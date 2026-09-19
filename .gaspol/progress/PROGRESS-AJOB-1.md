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
- [x] Run tests, confirm all pass — 14 tests, OK (183 after the audit fixes)
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
- [x] Write failing test for `ats.normalize_greenhouse(fixture)`. Expected error: `ModuleNotFoundError: No module named 'ats'`
- [x] Run tests, confirm it fails for that reason
- [x] Record three fixtures to disk (trimmed from the verified live endpoints in the plan) so no test touches the network
- [x] Implement `scripts/ats.py` with streaming `fetch(board, slug, dest)` separated from pure `normalize_<board>(path)` — boards reach 5 MB
- [x] Add tests for empty list, no location, HTML description, sub-10-char description, non-JSON body, 404 with `Document not found`, timeout, Ashby `isListed: false`, unmappable Greenhouse location
- [x] Run tests, confirm all pass
- [x] Commit: "feat(ats): Greenhouse/Lever/Ashby fetch and normalisation"

**Verification:**
- [x] `python3 -m compileall -q scripts tests` passes
- [x] `python3 -m unittest discover -s tests -t . -v` passes
- [x] No test performs network I/O — proven by running the whole suite with
      `socket.socket.connect`, `connect_ex`, `create_connection` and `getaddrinfo`
      all raising: 244 tests, 0 failures, 0 errors. (The earlier grep-count phrasing
      was wrong twice over: `tests/` holds 13 `urlopen` mentions, of which 6 are
      `unittest.mock.patch` targets — a count is the weaker evidence anyway.)
- [x] A description under 10 characters normalises to `"N/A"`, satisfying the jobsync minimum
- [x] An unmappable Greenhouse location leaves `workplaceType` absent rather than guessing
- [x] An Ashby row with `isListed: false` is dropped
- [x] No placeholder/TODO comments in new code

### [x] Phase D: keyword coverage report
- [x] Write failing test for `keywords.coverage(jd_text, cv_text)`. Expected error: `ModuleNotFoundError: No module named 'keywords'`
- [x] Run tests, confirm it fails for that reason
- [x] Implement extraction, stopword removal and comparison
- [x] Add tests for empty JD, empty CV, substring false positives, hyphenation, casing, repeats, non-ASCII
- [x] Implement `render(report)` whose heading states keyword overlap, not ATS score
- [x] Run tests, confirm all pass
- [x] Commit: "feat(keywords): JD-vs-CV coverage report"

**Verification:**
- [x] `python3 -m compileall -q scripts tests` passes
- [x] `python3 -m unittest discover -s tests -t . -v` passes
- [x] `java` in the CV does not mark `javascript` covered, nor the reverse
- [x] The rendered heading says keyword overlap and does not claim an ATS score
- [x] No placeholder/TODO comments in new code

### [x] Phase E: promote — payload building and request budget
- [x] Write failing test for `promote.to_add_job(row)` producing `upsert: True` and a canonical `workplaceType`. Expected error: `ModuleNotFoundError: No module named 'promote'`
- [x] Run tests, confirm it fails for that reason
- [x] Implement `to_add_job`, `to_match_text`, `build_tags`, `chunk`, `plan_budget`
- [x] Add tests for missing description, `On-site` and `REMOTE`, every recommendation boundary (80/79/65/64/50/49/0/100), 11 skill tags, batches of 10 and 11, budget 0, short matchText
- [x] Run tests, confirm all pass
- [x] Commit: "feat(promote): jobsync payload mapping with tag cap and request budget"

**Verification:**
- [x] `python3 -m compileall -q scripts tests` passes
- [x] `python3 -m unittest discover -s tests -t . -v` passes
- [x] Every generated `matchText` begins with a `SCORES:` line matching `^SCORES: match=\d{1,3} recommendation=(strong|good|partial|weak)$`
- [x] `tags` never exceeds 10 and always retains the visa tag and the variant tag
- [x] Batches never exceed 10 items
- [x] No placeholder/TODO comments in new code

### [x] Phase E.5: `scripts/jobhunter.py`, the one command the skills call
- [x] Lahir dari gaspol-review putaran 1, bukan dari plan asli — plan ditambal balik agar tetap self-contained
- [x] Sembilan subcommand, satu `argparse`, JSON di stdout, refusal JSON di stderr
- [x] `--company` diwajibkan untuk lever/ashby dan ditolak untuk greenhouse, sebelum panggilan jaringan
- [x] `promote-prepare` validasi dulu, budget atas yang lolos
- [x] `tests/test_cli.py` memanggil `main(argv)` langsung dan membaca stdout (putaran 3)

### [x] Phase F: the six skills and the plugin manifest
- [x] Write failing test asserting `.claude-plugin/plugin.json` parses and every `skills/*/SKILL.md` declares name and description. Expected error: `FileNotFoundError: .claude-plugin/plugin.json`
- [x] Run tests, confirm it fails for that reason
- [x] Write `.claude-plugin/plugin.json`
- [x] Write the six SKILL.md files, with `promote` the only one allowed to call jobsync MCP
- [x] `profile`'s SKILL.md spells out the four passes (ingest / extract / reconcile / render), the tier precedence, the `verified: false` suppression rule, and the project allow-list rule
- [x] Read `jobhunter-plugin/refs/` for prior art before writing `tailor` and `outreach`
- [x] Run tests, confirm all pass
- [x] Commit: "feat(skills): six pipeline skills and plugin manifest"

**Verification:**
- [x] `python3 -m compileall -q scripts tests` passes
- [x] `python3 -m unittest discover -s tests -t . -v` passes
- [x] No SKILL.md bundles any candidate-specific value — grep for `alisadikin`, `INDUSIA` and `Obsidian` across `skills/` returns nothing
- [x] `tailor`'s SKILL.md states that reading the target job description is mandatory and that `master-cv.md` is never sent as-is
- [x] `outreach`'s SKILL.md contains no send path, only draft creation
- [x] `profile`'s SKILL.md states the `verified: false` suppression rule and the project allow-list rule
- [x] No placeholder/TODO comments in new code

### [x] Phase G: evals for the judgement steps
- [x] Write failing test asserting each eval file exists and names ≥5 cases. Expected error: `FileNotFoundError: docs/evals/scoring.md`
- [x] Run tests, confirm it fails for that reason
- [x] Collect ≥6 real job descriptions into `docs/evals/fixtures/`
- [x] Write `docs/evals/scoring.md` with capability and regression cases
- [x] Write `docs/evals/tailoring.md` with anti-fabrication criteria
- [x] Write `docs/evals/profile.md`: precedence resolution, same-tier conflict goes to conflicts.md, `[verifikasi]` claim suppressed, two same-number different-subject claims not fused, every bullet names a source
- [x] Run tests, confirm all pass
- [x] Commit: "test(evals): scoring and tailoring eval suites with real fixtures"

**Verification:**
- [x] `python3 -m compileall -q scripts tests` passes
- [x] `python3 -m unittest discover -s tests -t . -v` passes
- [x] All three eval files name ≥5 cases each with explicit pass criteria
- [x] The "no sponsorship" fixture is a named regression case expecting `closed`
- [x] The model-research fixture is a named regression case expecting a **low** role-fit score
- [x] `docs/evals/profile.md` has a named case proving a `[verifikasi]` claim is suppressed
- [x] No placeholder/TODO comments in new code

## Phase log

| Phase | Status | Commit |
|---|---|---|
| A — local queue | DONE | `f910b60` + fix |
| B — config | DONE | `9dbd9b8` |
| C — ATS fetchers | DONE | `5998380` + fix |
| D — keyword coverage | DONE | `8e2033d` |
| E — promote | DONE | `92dce2a` |
| E.5 — CLI entrypoint | DONE | `1aa0e24` (lahir dari review, bukan plan) |
| F — skills + manifest | DONE | `12ac066` |
| G — evals | DONE | `283919c` |

## Audit plan-verifier (2026-09-19)

Verdict pertama: **BLOCKING** — 3 MISSING, 3 PARTIAL, 1 DIVERGED. Semua ditutup di `8442773`.

| # | Temuan | Tindakan |
|---|---|---|
| M1 | `promote.py` membaca `dimension_reasons`; kontrak menyebut `score_reasons`. Rincian per-dimensi tidak pernah sampai ke jobsync | Diganti + tes yang meng-grep sumbernya |
| M2 | Baris judul-saja lolos promosi; spec §8 menyuruh menolak | `TitleOnlyError` |
| M3 | Tidak ada yang mencatat match *Provisional* untuk posting pendek | `match_quality()` + baris di `matchText` |
| P1 | Bucket `open` tidak punya fixture sama sekali | Dicatat sebagai celah di `docs/evals/scoring.md` |
| P2 | Dua skill menjanjikan tulis-balik antrean yang tidak ada fungsinya | `jobq.update_rows` (tulis atomik) |
| P3 | Nilai budget tidak diperiksa tipenya | `BudgetTypeError` di `config.load` |
| D1 | Nama berkas dan angka pribadi asli di `docs/evals/profile.md` | Dianonimkan |

Dua temuan (M1, M2) dibuktikan dengan **menjalankan** `promote.py`, bukan membacanya.

## gaspol-review Tier 1 (2026-09-19)

Dua putaran. Verdict pertama: **BLOCKING** — 3 Critical. Verdict kedua atas diff perbaikan: **BLOCKING** lagi — 4 Critical, dua di antaranya tes yang baru saja ditulis dan hijau padahal tidak menjaga apa pun.

| Putaran | Temuan | Tindakan |
|---|---|---|
| 1 | Nol entrypoint — skill menyebut nama fungsi Python, tidak ada satu pun cara memanggilnya | `scripts/jobhunter.py` (9 subcommand) + tiap SKILL.md menyebut perintah nyata |
| 1 | Daftar putih bisa dilewati lewat `"."`, `""`, dan symlink | Nama yang menormalisasi ke root ditolak; jalur terselesaikan wajib di bawah root |
| 1 | `update_rows` menghapus permanen baris rusak | Baris tak terbaca disimpan apa adanya |
| 1 | Satu posting rusak membuang satu board penuh | 667 lowongan dengan 1 anomali → 666 baris; semua rusak tetap gagal keras dan menyebut field-nya |
| 1 | `fit_score` cuma divalidasi di `to_match_text` | Divalidasi di `_require_score`, dipakai dua-duanya |
| 1 | `KeyError` bocor dari `row["company"]` | `FieldMissingError` |
| 1 | `C++` / `C#` jadi token `c` | Token bersimbol dipertahankan |
| 1 | Laporan kata kunci 699 baris | Kepala berperingkat + judul jujur soal pemotongan |
| 1 | `__main__` di tengah 3 berkas tes — 26 tes diam-diam terlewat | Dipindah ke akhir; paritas langsung-vs-discover diuji |
| 2 | **Tes `.NET` hampa** — assertion menyebut token yang tidak pernah ada | Assertion diperbaiki; regex menerima titik di depan |
| 2 | **Tes subcommand hampa** — parser menghasilkan string kosong | Diganti regex; dibuktikan gagal dengan subcommand palsu |
| 2 | **Bypass keempat**: symlink DI DALAM folder yang di-allow-list | Tiap link di bawahnya diperiksa; jalur terselesaikan dikembalikan |
| 2 | `iter_unpromoted` nol pemanggil | `queue-list --unpromoted` + masuk kriteria eligibility |
| 2 | Kontrak error JSON pecah pada input keliru biasa | `main()` menangkap semua, selalu JSON |
| 2 | Budget dihitung sebelum validasi — salah 6× | Validasi dulu, budget atas yang lolos |
| 2 | `AttributeError` pada entri non-dict Ashby (regresi dari perbaikan sebelumnya) | Ditolak bernama |
| 3 | **Bypass kelima & keenam**: containment diukur ke `root`, bukan ke folder yang di-allow-list. `allowed/archive -> ..` membuka seluruh vault | Diukur ke folder allow-list; `ln -s ..` ditolak |
| 3 | **Bypass ketujuh**: entry allow-list sendiri boleh symlink ke sibling. Test `test_symlink_pointing_inside_the_root_is_allowed` justru mengkodekan lubang ini sebagai perilaku benar | Entry wajib persis `<root>/<name>`; test diganti |
| 3 | Guard non-dict cuma di Ashby — satu entri nyasar membuang seluruh board Greenhouse/Lever | Guard pindah ke `_normalize_all`, satu tempat untuk tiga board |
| 3 | `_Rows.skipped` nol pembaca, dan `json.dump` membuangnya — cacat sama persis yang memblokir putaran 2 | `_Rows` selalu dikembalikan; `jobhunter.py` melaporkan `skipped` |
| 3 | Guard `top_n` di bawah dua early return — `--top 0` dengan JD kosong keluar 0 | Validasi argumen dipindah ke paling atas |
| 3 | `scripts/jobhunter.py` nol tes perilaku padahal entrypoint semua skill | `tests/test_cli.py`, 11 tes |
| 3 | `ats.fetch` cetak log ke stdout — `json.load` gagal di fetch sungguhan | `file=sys.stderr` di empat baris |
| 3 | Plan mengaku self-contained tapi nol sebutan `jobhunter.py`, `update_rows`, `iter_unpromoted` | Phase E.5 ditambahkan ke plan; kontrak `jobq` dilengkapi |
| 3 | Kotak verifikasi mengklaim `grep urlopen` nihil — nyatanya 13 sebutan | Klaim diganti dengan yang benar (12 target patch) |
| 3 | Penjaga manifest cuma cek nama subcommand, bukan flag — `--unpromted` tetap hijau | Flag ikut dicek ke `--help` subcommand-nya |

Uji mutasi dipakai dua kali: subcommand palsu disisipkan ke SKILL.md untuk membuktikan penjaganya menggigit.

## Audit plan-verifier putaran 2 (2026-09-19)

Dijalankan ulang karena plan bertambah Phase E.5. Verdict: BLOCKING — 1 DROPPED, 2 MISSING.
57 FOUND, 8 PARTIAL, 1 DIVERGED (pesan commit E.5, diungkap bukan disembunyikan), 0 placeholder.

| # | Temuan | Tindakan |
|---|---|---|
| D1 | Aturan spec §8 — *Provisional* untuk posting <150 kata dan penolakan baris judul-saja — ada di kode tapi **tidak pernah masuk plan**. Plan mengaku self-contained; agen yang menjalankannya akan mengirim baris judul-saja | `match_quality`, `TitleOnlyError`, `FULL_MATCH_MIN_WORDS` ditulis ke Phase E step 3 + ladder + kasus uji |
| M1 | **Penjaga flag putaran 3 memeriksa NOL flag.** Regex per-baris, padahal semua blok perintah di SKILL.md pakai backslash continuation. Uji mutasi saya menaruh typo di baris yang sama — gaya yang tidak dipakai skill mana pun | Regex melipat continuation; 16 flag kini diperiksa; uji mutasi diulang di gaya asli |
| M2 | Nol tes untuk `config-show` — perintah pertama yang dijalankan keenam skill, dan justru yang disebut plan E.5 step 1 | 3 tes, termasuk bukti daftar putih di level CLI |
| P1 | `main()` tidak men-JSON-kan kegagalan argparse: subcommand salah ketik keluar usage prose, exit 2 | `_JsonArgumentParser.error` + `SystemExit` ditangkap di `main()` |
| P2 | `skills/discover/SKILL.md` menyuruh cari `skipped` di stderr; nyatanya kunci JSON di stdout | Prosa diperbaiki |
| P3 | `DEFAULT_TOP_N = 40` memotong laporan, tidak disebut plan | Ditulis ke ladder Phase D |
| P4 | Kotak Phase C soal `urlopen` salah hitung — dan hitungan memang bukti yang lemah | Diganti: seluruh suite dijalankan dengan `socket.connect`/`connect_ex`/`create_connection`/`getaddrinfo` melempar — 244 lulus |
| P5 | `tests/__init__.py` tidak dideklarasikan plan | Ditambahkan ke daftar berkas Phase A |

Tidak ditemukan: bypass daftar putih kedelapan. Enam bentuk serangan baru diuji, semua ditolak.

## Regression tests

Each line below was proven by running the round-3 tests against the pre-fix tree
(`git archive 50a17fb`), where all of them fail, and against HEAD, where all pass.
Two of the guards were additionally mutation-tested: reverting the guard makes
exactly its own test fail, and nothing else.

regression-test: tests/test_config.py::test_a_nested_link_to_the_root_itself_is_refused — RED at 50a17fb (read root/client-acme-pricing/negotiation.md through `allowed/archive -> ..`), GREEN after fix; mutation-tested
regression-test: tests/test_config.py::test_a_nested_link_to_an_unlisted_sibling_is_refused — RED at 50a17fb (read root/client-work/nda.md through `allowed/peek`), GREEN after fix; mutation-tested
regression-test: tests/test_config.py::test_symlink_to_a_sibling_under_the_root_is_also_rejected — RED at 50a17fb (the pre-fix test of this name asserted the escape was correct), GREEN after fix; mutation-tested
regression-test: tests/test_cli.py::test_greenhouse_survives_a_non_dict_entry — RED at 50a17fb (`'str' object has no attribute 'get'` discarded the whole board), GREEN after fix
regression-test: tests/test_cli.py::test_lever_survives_a_non_dict_entry — RED at 50a17fb (`'int' object has no attribute 'get'`), GREEN after fix
regression-test: tests/test_cli.py::test_ashby_survives_a_non_dict_entry — RED at 50a17fb (no `skipped` key existed to report), GREEN after fix
regression-test: tests/test_cli.py::test_the_skipped_posting_is_reported_not_swallowed — RED at 50a17fb (`_Rows.skipped` had zero readers and json.dump dropped it), GREEN after fix
regression-test: tests/test_cli.py::test_ats_normalize_emits_one_json_document_and_nothing_else — RED at 50a17fb (a log line on stdout made json.load fail), GREEN after fix
regression-test: tests/test_cli.py::test_top_zero_is_refused_even_when_the_jd_is_empty — RED at 50a17fb (`--top 0` exited 0 with a report), GREEN after fix
regression-test: tests/test_cli.py::test_missing_company_refuses_before_any_work — RED at 50a17fb (bare ValueError, not a named refusal), GREEN after fix
regression-test: tests/test_manifest.py::test_every_documented_flag_exists_on_its_subcommand — RED when `--unpromted` is documented, GREEN when removed; mutation-tested

## Utang terbuka

- jobsync MCP token belum dibuat — promote hanya bisa diuji unit, belum end-to-end.
- Tidak ada lowongan ber-frasa "no sponsorship" gaya AS di 815 lowongan yang disapu (Stripe 667 + Ramp 148). Fixture `closed` memakai "Right to work in the UK is required" — bentuk aturan yang sama, negara berbeda. Dicatat sebagai celah di `docs/evals/scoring.md`, bukan ditutup dengan lowongan karangan.
- `docs/plans/*-spec.md` §4.2 masih memuat nama berkas dan angka pribadi asli sebagai bukti keputusan desain. `docs/evals/` sudah dianonimkan; spec belum — keputusan Ali, karena itu catatan alasan, bukan aset yang dijalankan.
- Keluaran `tailor` berhenti di markdown. Belum ada langkah render ke PDF/DOCX, jadi aturan format ramah-ATS belum punya tempat berlaku.
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
- 2026-09-19 Phase F done — `python3 -m unittest discover -s tests -t .` 145 lulus / 0 gagal; `grep -rniE "alisadikin|indusia|obsidian|Drive-D" skills/` nol hasil; 23 referensi fungsi di SKILL.md semuanya menunjuk fungsi yang ada — NEXT: Phase G
- 2026-09-19 Phase G done — `python3 -m unittest discover -s tests -t .` 157 lulus / 0 gagal; 7 fixture JD asli (Greenhouse 5, Ashby 2), teks diverifikasi ada di payload asli — SEMUA FASE SELESAI
- 2026-09-19 audit plan-verifier BLOCKING (3 MISSING / 3 PARTIAL / 1 DIVERGED) ditutup di `8442773` — 183 lulus / 0 gagal, naik dari 157 — NEXT: tutup AJOB-1, lalu AJOB-2 (render DOCX/PDF ramah-ATS)
- 2026-09-19 gaspol-review Tier 1 putaran 2 ditutup di `bf9ac50` — 225 lulus / 0 gagal, naik dari 157 di akhir Fase G — NEXT: review ulang putaran 3
- 2026-09-19 gaspol-review Tier 1 putaran 3 — 10 temuan, tiga di antaranya bypass daftar putih (kelima, keenam, ketujuh), semua dibuktikan dengan membaca file rahasia yang ditanam. Satu test lama justru mengkodekan lubangnya sebagai perilaku benar. Diperbaiki di `b88f813`; 239 lulus / 0 gagal; kedua penjaga baru diuji mutasi — NEXT: gaspol-review putaran 4 (scope `50a17fb..HEAD`)

> **For Claude:** REQUIRED SKILL: Use gaspol-execute to implement this plan.
> **CRITICAL:** This plan specifies real integrations. During execution,
> NEVER substitute placeholders for real data sources without explicit
> user approval. If a data source doesn't exist yet, STOP and ask.
> **Progress ledger — HARD PER-PHASE GATE:** `.gaspol/progress/PROGRESS-AJOB-6.md`. After EACH
> phase and **BEFORE** starting the next, STOP and do BOTH: (a) tick that phase's `## Checklist`
> line, (b) append a `## Log` line ending with the handoff cursor. This is **blocking** — no next
> phase until both are written. Never batch all updates at the end. Update ONLY this file.
> **Self-contained:** this plan is the COMPLETE spec. It must be executable by an agent with
> **no other context**. Every file path, contract, config key, and convention it needs is written
> here verbatim.

**Ticket:** AJOB-6
**Ledger:** .gaspol/progress/PROGRESS-AJOB-6.md
**Spec:** docs/plans/2026-09-23-AJOB-6-per-company-jd-folders-spec.md

## Goal

Replace the flat, disconnected `.jobhunter/applications/<slug>/` tailoring output with a
source-keyed, company-keyed, browsable tree at `Data/<Source>/<Company>/<Role-slug>/`, populated
by `discover` and filled in by `tailor` (CV, cover letter, requirements map, keyword report) in
place. Add a deterministic near-duplicate JD detector so re-tailoring a posting that is really the
same template reposted by a different company gets a fast-path draft instead of a from-scratch
requirements-map walk — without ever auto-approving a row or inventing company-specific praise.

This plan operates on the `gaspol-jobhunter` plugin source repository at
`/Users/alisadikin/Drive-D/claude-plugin/gaspol-jobhunter` (git-tracked, `origin/master`, clean at
plan-write time). It is a **separate repository** from the reference project that consumes the
installed plugin (`/Users/alisadikin/Drive-D/my-data/hunting-remote-job`) — every file path below
is relative to the plugin repo root unless stated otherwise.

## Architecture Context

Read in full from `CLAUDE.md` at the plugin repo root (7.8K, reproduced here where load-bearing):

- **Stack:** Python 3 standard library only — no pip, no pytest, no PyYAML. Tests are `unittest`.
  `python3 -m unittest discover -s tests -t .` (857 tests before this ticket), static check
  `python3 -m compileall -q scripts tests`.
- **One entrypoint:** every skill runs `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py"
  <subcommand> [options]`. One `argparse`, one dispatch table in `main()`
  (`scripts/jobhunter.py:704`). Every subcommand prints one JSON document on stdout (except
  `keywords-report --markdown`); a refusal is `{"error": "<class>", "message": "..."}` on stderr,
  exit 1 — `main()`'s generic `except Exception` (`scripts/jobhunter.py:712-727`) already produces
  this for ANY exception type, so a new custom exception class needs no changes there.
- **`tests/test_manifest.py`** (34K, `TestSkillsNameARunnableEntrypoint` and
  `TestClaudeMdNamesEverySubcommand` classes) is a live cross-check, not a static list:
  - `test_every_documented_subcommand_exists_in_the_cli` — every subcommand named in any
    `skills/*/SKILL.md` must be a real CLI subcommand.
  - `test_every_documented_flag_exists_on_its_subcommand` — every flag shown beside a documented
    subcommand must be a real flag on it.
  - `test_subcommands_line_matches_the_cli` — `CLAUDE.md`'s `## The one entrypoint` "Subcommands:"
    line must equal the CLI's full subcommand list, **in the order argparse reports them**, which
    is registration order in `build_parser()`. This means: whatever order this plan registers
    `jd-write` / `jd-similar` in `scripts/jobhunter.py`, `CLAUDE.md`'s line must list them in that
    same trailing position.
- **No existing `.jobhunter/applications/` data anywhere** — verified empty in the reference
  project before this plan was written. Clean cutover, no migration phase needed.
- **No config.toml changes** — every existing subcommand takes its paths as explicit CLI flags
  (`--queue .jobhunter/queue/jobs.jsonl`, `--in .../cv.md`), never from a config field. The new
  `Data/` root follows the same convention: passed explicitly as `--root Data` by the calling
  skill, not read from `.jobhunter/config.toml`.

**Full inventory of every `.jobhunter/applications/` reference in the repo today** (grepped at
plan-write time, `tests/test_evals.py:397`'s "applications" is Word/Google Docs/LibreOffice —
unrelated, not touched):

| File | Lines | What it is |
|---|---|---|
| `scripts/jobhunter.py` | 635, 657 | `--help` text example paths for `render-docx`/`render-pdf` `--in` |
| `skills/tailor/SKILL.md` | 24, 96, 233, 272-273, 285, 291, 306-307, 336-337, 384 | input/output path prose + example commands |
| `skills/outreach/SKILL.md` | 73, 92, 120 | reads the tailored application folder; `.eml` fallback output path |

`outreach` was **not named in the approved spec** — found during this planning pass by grepping
every reference before writing phases, per the spec's own deferred "Open question for
`gaspol-plan`". It depends on the exact same folder `tailor` writes into, so relocating that
folder without updating `outreach` would silently break it. This is a mechanical path correction
(same behavior, new root), not new scope — included as Phase H.

## Tech Stack

Python 3 standard library only, matching the whole repo. New code uses only `os`, `re`, `json`,
`glob`, `hashlib` (via `jobq.row_key`, not reimplemented), and `difflib` — all stdlib, no new
dependency.

## Data Integration Map

| Feature | Data Source | Module/Function | Exists? | Action |
|---|---|---|---|---|
| Per-posting folder path | queue row (`company`, `jobTitle`, `source`) + `jobq.row_key(row)` | `jdstore.job_dir` | No | Create new (Phase A) |
| Filesystem-safe path component | raw company/title strings (external, scraped) | `jdstore.safe_component` | No | Create new (Phase A) |
| `JD.md` + `.jobmeta.json` materialization | queue rows from `discover` | `jdstore.write_jd` / `write_jd_files` | No | Create new (Phase B) |
| Near-duplicate JD match | prior `Data/**/requirements-map.md` with `approved:` + sibling `JD.md` | `jdstore.find_similar` (stdlib `difflib.SequenceMatcher`) | No | Create new (Phase C) |
| `jd-write` CLI subcommand | `jdstore.write_jd_files` | `scripts/jobhunter.py: cmd_jd_write` | No | Create new (Phase D) |
| `jd-similar` CLI subcommand | `jdstore.find_similar` | `scripts/jobhunter.py: cmd_jd_similar` | No | Create new (Phase D) |
| `discover`'s queue write | `.jobhunter/queue/jobs.jsonl` via `jobq.append_rows` | `skills/discover/SKILL.md` | Yes, unchanged | Reuse as-is (Phase F adds a step after it) |
| `tailor`'s render/check pipeline | `render-pdf`, `render-docx`, `template-check`, `keywords-report` | existing subcommands | Yes, path-agnostic | Reuse as-is, only the path prose changes (Phase G) |
| `outreach`'s application-folder read | tailored CV/cover-letter + contact discovery | `skills/outreach/SKILL.md` | Yes | Path corrected only (Phase H) |

**Output consumers:** `Data/<Source>/<Company>/<Role>/JD.md` is consumed by `tailor` (reads it as
the JD text) and by `jdstore.find_similar` (reads every prior one as comparison corpus).
`.jobmeta.json` is consumed by `jdstore.job_dir` (collision detection) and `jdstore.find_similar`
(reporting which company/role a match belongs to, and stripping that JD's own company name before
comparing). Neither file is consumed by `score` or `promote` — those two skills are unchanged and
keep reading only the queue, confirmed by the grep table above (`score`/`promote` never appear in
it).

## Out of scope

- Migrating or backfilling `.jobhunter/applications/` — it does not exist yet.
- Any change to `score`, `promote`, `profile`, or `jobsync` MCP payloads.
- Generalizing this folder scheme to any root other than `Data/` or any naming other than the
  existing `source` field values.

---

### Phase A: `scripts/jdstore.py` — filesystem-safe path resolution

**Estimated time:** 25 minutes

**Files:**
- Create: `scripts/jdstore.py`
- Test: `tests/test_jdstore.py`

**Security note (this phase is security-sensitive):** `company` and `title` originate from
scraped/API JD text (Firecrawl, Apify) — external, semi-trusted input — and become filesystem path
components. Without guarding, a value containing `/`, `\`, or exactly `.`/`..` after cleaning could
escape the intended `Data/<source>/` subtree (`os.path.join(root, "..", ...)` really does traverse
up). This phase's verification block includes a security line and `gaspol-execute`'s Step 3.6 will
auto-run `/security-review` on it.

**Steps:**
1. Write failing test `test_safe_component_replaces_path_separators` in `tests/test_jdstore.py`:
   `jdstore.safe_component("AI/ML Corp")` should not contain `/` or `\`. Expected error:
   `ModuleNotFoundError: No module named 'jdstore'` (module does not exist yet).
2. Run `python3 -m unittest tests.test_jdstore -v` from the repo root, confirm it fails for that
   reason.
3. Create `scripts/jdstore.py` with the module docstring, `JdStoreError(Exception)`, and
   `safe_component(value)`:
   - Regex-replace `[\\/:*?"<>|\x00-\x1f]+` with `-`.
   - Collapse whitespace runs to a single space, strip.
   - Strip leading/trailing `.` and `-` characters.
   - Truncate to 80 characters.
   - Raise `JdStoreError` if the input is empty/whitespace-only, or if the cleaned result is
     empty, or if the cleaned result is exactly `.` or `..` (the traversal guard named above).
4. Run the test, confirm it passes.
5. Write failing test `test_safe_component_rejects_dot_dot`:
   `jdstore.safe_component("..")` raises `jdstore.JdStoreError`. Expected error:
   `AssertionError` (no exception raised yet, if step 3 was written wrong) — confirm this test
   currently passes given step 3's guard is already in place; if it does not exist yet at this
   point in a stricter TDD reading, write this test BEFORE step 3's guard clause and confirm it
   fails with no exception raised, then add the guard.
6. Write tests for the full edge-case matrix: empty string → `JdStoreError`; whitespace-only →
   `JdStoreError`; string containing `/`, `\`, `:`, `*`, `?`, `"`, `<`, `>`, `|` → none of those
   characters in the result; a 300-character title → result is ≤80 chars; a string that is only
   unsafe characters (e.g. `"////"`) → `JdStoreError` (cleans to empty); leading/trailing
   whitespace and dots (`"  .foo.  "`) → cleaned to `"foo"`; unicode text (e.g. `"Ingénieur IA"`)
   → passes through unchanged (no ASCII-only requirement — filesystems used here are UTF-8 safe).
7. Run the full `tests/test_jdstore.py` file, confirm every case passes.
8. Write failing test `test_job_dir_is_deterministic`: two calls to
   `jdstore.job_dir(root, "LinkedIn", "Acme Corp", "AI Engineer", "abc123")` with the same
   arguments against a fresh temp directory return the identical path both times. Expected error:
   `AttributeError: module 'jdstore' has no attribute 'job_dir'`.
9. Implement `job_dir(root, source, company, title, identity_key)`:
   - `candidate = os.path.join(root, source, safe_component(company), safe_component(title))`.
   - If `candidate` does not exist on disk → return `candidate` (caller creates it).
   - If `candidate` exists and `os.path.join(candidate, ".jobmeta.json")` exists and its
     `row_key` field equals `identity_key` → return `candidate` (same posting, idempotent).
   - Otherwise (candidate exists for a different posting, or has no `.jobmeta.json` at all —
     treated as foreign/unrelated data, never claimed) → append `-{identity_key[:6]}` to the
     role component and retry the same three checks once more against that suffixed path. If
     the suffixed path ALSO collides with a third, different posting, raise `JdStoreError`
     naming both colliding paths — this is an accepted, documented limit (a 6-hex-character
     space collision on top of an exact-name collision is vanishingly unlikely in a personal job
     queue) rather than an unbounded retry loop.
10. Run the test, confirm it passes.
11. Write and pass tests for `job_dir`'s remaining edge cases: same company+title, different
    `identity_key` → second call returns the suffixed path, first call's path untouched; calling
    `job_dir` twice with the identical `identity_key` after the folder was created by a previous
    call (simulate by creating the dir + `.jobmeta.json` by hand in the test) → returns the same
    path both times, no suffix; a `root` that does not exist yet → `job_dir` does not create it
    (read-only resolution — creation is `write_jd`'s job, tested in Phase B).
12. Run `python3 -m compileall -q scripts tests`, confirm clean.
13. Commit: "feat(jdstore): filesystem-safe path resolution for Data/<source>/<company>/<role>/"

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] `safe_component` never lets `/`, `\`, or a bare `.`/`..` component reach `os.path.join`
- [ ] `job_dir` is deterministic and idempotent for the same `identity_key`
- [ ] Security: path-traversal edge cases (`../`, `..`, absolute-looking input) covered by tests
      and neutralized before reaching `os.path.join`
- [ ] No placeholder/TODO comments in new code

---

### Phase B: `scripts/jdstore.py` — `write_jd` / `write_jd_files`

**Estimated time:** 25 minutes

**Files:**
- Modify: `scripts/jdstore.py`
- Test: `tests/test_jdstore.py`

**Steps:**
1. Write failing test `test_write_jd_creates_jd_and_meta_files`: call
   `jdstore.write_jd(root, {"company": "Acme", "jobTitle": "AI Engineer",
   "jobDescription": "Full posting text...", "jobUrl": "https://x/1", "source": "LinkedIn"})`
   against a fresh temp `root`; assert `JD.md` exists and its content equals the row's
   `jobDescription` verbatim; assert `.jobmeta.json` exists and, when parsed, its `row_key` equals
   `jobq.row_key(row)`. Expected error: `AttributeError: module 'jdstore' has no attribute
   'write_jd'`.
2. Run it, confirm it fails for that reason.
3. Implement `write_jd(root, row)`:
   - Require `row["jobDescription"]` to be non-empty (strip-checked) — raise `JdStoreError` naming
     the missing field otherwise. This mirrors `ats.MissingFieldError`'s reasoning: no JD text
     means no folder, matching `tailor`'s existing "reading the JD is mandatory" rule.
   - `identity_key = jobq.row_key(row)` (import `jobq` at module top).
   - `path = job_dir(root, row["source"], row["company"], row["jobTitle"], identity_key)`.
   - If `path` already has a `.jobmeta.json` whose `row_key` matches `identity_key` → return
     `{"path": path, "created": False}` without writing (idempotent skip — do not overwrite an
     already-materialized JD, which may already have `tailor` output beside it).
   - Otherwise: `os.makedirs(path, exist_ok=True)`; write `JD.md` with `row["jobDescription"]`
     verbatim; write `.jobmeta.json` with `{"row_key": identity_key, "jobUrl":
     row.get("jobUrl"), "company": row["company"], "jobTitle": row["jobTitle"], "source":
     row["source"], "written_at": <UTC ISO-8601 via datetime.datetime.now(datetime.UTC) or
     datetime.datetime.utcnow().isoformat()>}`; return `{"path": path, "created": True}`.
4. Run the test, confirm it passes.
5. Write and pass: `test_write_jd_is_idempotent_for_same_posting` (calling `write_jd` twice with
   the identical row returns `created: False` on the second call, `JD.md` content unchanged, no
   second directory created); `test_write_jd_rejects_missing_job_description` (row with
   `jobDescription: ""` raises `JdStoreError`); `test_write_jd_rejects_missing_job_description_key`
   (row with the key absent entirely raises `JdStoreError`, not `KeyError`).
6. Write failing test `test_write_jd_files_reports_per_row`: `jdstore.write_jd_files(root, rows)`
   where `rows` is a list of 3 — two valid, one missing `jobDescription` — returns
   `{"written": [...2 paths...], "skipped_existing": [], "errors": [...1 entry naming the bad
   row's company/title and the reason...]}`, and the two valid rows' folders exist on disk while
   the bad row wrote nothing. Expected error: `AttributeError: module 'jdstore' has no attribute
   'write_jd_files'`.
7. Implement `write_jd_files(root, rows)`: loop calling `write_jd` per row inside a
   `try/except JdStoreError`, sorting each row into `written` (path, when `created` is `True`),
   `skipped_existing` (path, when `created` is `False`), or `errors` (`{"company":
   row.get("company"), "jobTitle": row.get("jobTitle"), "message": str(exc)}`) — one bad row never
   aborts the rest of the batch, same resilience pattern as `ats._normalize_all`.
8. Run the test, confirm it passes.
9. Write and pass: `test_write_jd_files_empty_list_returns_all_empty` (edge case: `rows=[]` →
   `{"written": [], "skipped_existing": [], "errors": []}`, no exception); a duplicate-within-batch
   case (two rows in the same call resolving to the same `identity_key`) → first is `written`,
   second is `skipped_existing`, not double-counted as an error.
10. Run `python3 -m compileall -q scripts tests`, confirm clean.
11. Commit: "feat(jdstore): write_jd / write_jd_files — materialize JD.md + .jobmeta.json"

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] `write_jd` never overwrites an already-materialized posting's `JD.md`
- [ ] `write_jd_files` reports every row (written / skipped / error) — a bad row is visible in
      `errors`, never silently dropped
- [ ] `JD.md` content is the row's `jobDescription` **verbatim** — no header, no reformatting
- [ ] No placeholder/TODO comments in new code

---

### Phase C: `scripts/jdstore.py` — `find_similar` (near-duplicate detection)

**Estimated time:** 25 minutes

**Files:**
- Modify: `scripts/jdstore.py`
- Test: `tests/test_jdstore.py`

**Steps:**
1. Write failing test `test_find_similar_detects_near_identical_jd`: create two folders under a
   temp `root` by hand —
   `root/LinkedIn/Acme Corp/AI Engineer/{JD.md, .jobmeta.json, requirements-map.md}` where
   `requirements-map.md` contains `approved: 2026-09-01` and `JD.md` holds a ~200-word JD text
   mentioning "Acme Corp"; call `jdstore.find_similar(root, jd_text=<the same 200-word text with
   "Acme Corp" replaced by "Globex Inc">, threshold=0.90)`; assert the result is a non-empty list
   whose first entry's `company` is `"Acme Corp"` and `ratio >= 0.90`. Expected error:
   `AttributeError: module 'jdstore' has no attribute 'find_similar'`.
2. Run it, confirm it fails for that reason.
3. Implement `find_similar(root, jd_text, threshold=0.90)`:
   - `glob.glob(os.path.join(root, "*", "*", "*", "requirements-map.md"))` — fixed 3-level depth
     matches `Data/<source>/<company>/<role>/`.
   - Skip any match whose content has no `^approved:\s*\S+` line (via `re.search` with
     `re.MULTILINE`) — not yet tailored to completion, not eligible for reuse.
   - For each eligible match: read the sibling `JD.md` in the same directory (skip with no error
     if absent — a `requirements-map.md` without a `JD.md` is malformed data, not a crash); read
     the sibling `.jobmeta.json` for its `company`/`jobTitle` (skip if absent or unparseable, same
     reasoning).
   - `_normalize_for_compare(text, company)`: lowercase, strip the company name (case-insensitive,
     via `re.sub(re.escape(company), "", text, flags=re.IGNORECASE)`), collapse whitespace.
   - `ratio = difflib.SequenceMatcher(None, _normalize_for_compare(jd_text, "<no company to
     strip for the NEW jd — caller's company is not yet known at this stage>"),
     _normalize_for_compare(candidate_text, candidate_company)).ratio()`. (The new JD's own
     company name is not stripped, since `find_similar` does not require the caller to already
     know it — the candidate side strips its own name, which is the side actually carrying
     boilerplate company mentions from a prior tailored posting.)
   - Keep entries with `ratio >= threshold`; return them sorted by `ratio` descending, each as
     `{"path": <directory>, "company": ..., "role": <jobTitle>, "ratio": <float>}`.
4. Run the test, confirm it passes.
5. Write and pass the edge-case matrix: no `Data/` tree at all (root does not exist) → returns
   `[]`, no exception; a `requirements-map.md` present but with no `approved:` line → excluded;
   a `requirements-map.md` approved but missing sibling `JD.md` → excluded, no crash; two
   eligible matches, one above threshold and one below → only the one above threshold returned;
   two eligible matches both above threshold → both returned, sorted descending by ratio; the new
   `jd_text` compared against itself (identical text, same folder) → ratio `1.0`; a completely
   unrelated JD (different role, different domain) → ratio far below threshold, excluded; a
   malformed `.jobmeta.json` (invalid JSON) → that folder skipped, not a crash for the whole scan.
6. Run `python3 -m compileall -q scripts tests`, confirm clean.
7. Commit: "feat(jdstore): find_similar — stdlib difflib near-duplicate JD detection"

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] Only `requirements-map.md` files carrying `approved:` are ever compared against
- [ ] A malformed or partial candidate folder (missing `JD.md`/`.jobmeta.json`) never crashes the
      scan — it is skipped
- [ ] Threshold is exactly ≥ 0.90 by default, matching the approved spec
- [ ] No placeholder/TODO comments in new code

---

### Phase D: CLI wiring — `jd-write`, `jd-similar` subcommands

**Estimated time:** 20 minutes

**Files:**
- Modify: `scripts/jobhunter.py`
- Test: `tests/test_cli.py`

**Steps:**
1. Write failing test in `tests/test_cli.py` (follow the file's existing pattern — find an
   existing subcommand's CLI test, e.g. the `keys-check` or `promote-prepare` test, and mirror its
   structure exactly): `test_jd_write_subcommand_exists_and_writes_files` — invoke the CLI via
   `main(["jd-write", "--root", tmp_root, "--rows", "@" + rows_json_path])` against a fixture rows
   file, assert exit code `0` and the JSON on stdout has `written`/`skipped_existing`/`errors`
   keys. Expected error: `SystemExit` with a non-zero code / argparse "invalid choice: 'jd-write'"
   (subcommand does not exist yet).
2. Run it, confirm it fails for that reason.
3. In `scripts/jobhunter.py`: add `import jdstore  # noqa: E402` to the import block
   (`scripts/jobhunter.py:37-47`, alphabetical position between `import jobq` and `import
   keywords`). Add `cmd_jd_write(args)` near the other `cmd_*` functions (`scripts/jobhunter.py`,
   after `cmd_promote_prepare` at line 469, before `cmd_render_docx` at line 200 — place it
   alongside `cmd_keywords_report` region since it is closest in shape):
   ```python
   def cmd_jd_write(args):
       rows = _read_json_arg(args.rows)
       result = jdstore.write_jd_files(args.root, rows)
       _emit(result)
   ```
4. Add the parser registration in `build_parser()`, right after the `template-check` block
   (`scripts/jobhunter.py:678-699`, before `return parser` at line 701) — this trailing position
   is what determines the order in `--help` and therefore what `CLAUDE.md`'s Subcommands line must
   match (Phase E):
   ```python
   p = sub.add_parser("jd-write", help="Materialize Data/<source>/<company>/<role>/JD.md for queue rows")
   p.add_argument("--root", required=True, help="Data directory root, e.g. Data")
   p.add_argument("--rows", required=True, help="JSON array of queue rows (camelCase), or @path")
   p.set_defaults(func=cmd_jd_write)
   ```
5. Run the test, confirm it passes.
6. Write failing test `test_jd_similar_subcommand_exists`: invoke
   `main(["jd-similar", "--root", tmp_root, "--jd", jd_text_path])` against a temp root with one
   eligible prior match (same fixture shape as Phase C's test), assert exit 0 and stdout JSON has
   a `matches` key. Expected error: argparse "invalid choice: 'jd-similar'".
7. Run it, confirm it fails for that reason.
8. Add `cmd_jd_similar(args)`:
   ```python
   def cmd_jd_similar(args):
       with open(args.jd, "r", encoding="utf-8") as f:
           jd_text = f.read()
       matches = jdstore.find_similar(args.root, jd_text, threshold=args.threshold)
       _emit({"matches": matches})
   ```
   and its parser, immediately after `jd-write`'s:
   ```python
   p = sub.add_parser("jd-similar", help="Find previously-tailored JDs similar to a new one")
   p.add_argument("--root", required=True, help="Data directory root, e.g. Data")
   p.add_argument("--jd", required=True, help="path to the new JD's text file")
   p.add_argument("--threshold", type=float, default=0.90, help="difflib ratio cutoff, default 0.90")
   p.set_defaults(func=cmd_jd_similar)
   ```
9. Run the test, confirm it passes.
10. Update the two stale example paths at `scripts/jobhunter.py:635` and `:657` (the `--in` help
    text for `render-docx`/`render-pdf`) from `.jobhunter/applications/<slug>/cv.md` to
    `Data/<Source>/<Company>/<Role>/cv.md`.
11. Write and pass CLI edge-case tests mirroring the module-level ones already covered in Phases
    A-C but at the CLI boundary: `jd-write` with a malformed `--rows` JSON → exit 1, `{"error":
    ...}` on stderr (already covered generically by `main()`'s except-block — confirm it, do not
    reimplement); `jd-similar` with a `--jd` path that does not exist → exit 1 with a
    `FileNotFoundError`-shaped `{"error": "FileNotFoundError", ...}`.
12. Run `python3 -m compileall -q scripts tests`, confirm clean.
13. Commit: "feat(cli): wire jd-write and jd-similar subcommands"

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] `python3 scripts/jobhunter.py jd-write --help` and `... jd-similar --help` both print usage
- [ ] Both subcommands appear in `python3 scripts/jobhunter.py --help`'s subcommand list, in the
      order they were registered (after `template-check`)
- [ ] No placeholder/TODO comments in new code

---

### Phase E: `CLAUDE.md` sync (test_manifest gate)

**Estimated time:** 10 minutes

**Files:**
- Modify: `CLAUDE.md`

**Steps:**
1. Run `python3 -m unittest tests.test_manifest.TestClaudeMdNamesEverySubcommand -v` from the repo
   root. Expected failure: `test_subcommands_line_matches_the_cli` fails because `CLAUDE.md`'s
   Subcommands line does not yet list `jd-write`/`jd-similar` while the live CLI (from Phase D)
   now does. This is the RED step for this phase — an existing guard test turning red because of
   Phase D's change, rather than a newly written test, which is the correct signal here (the test
   already encodes the exact contract this phase must satisfy).
2. Edit `CLAUDE.md`'s `## The one entrypoint` section (`CLAUDE.md:54-57`): append `jd-write`,
   `jd-similar` to the end of the "Subcommands:" comma-separated list, in that order (matching
   registration order from Phase D step 4/8).
3. Add a row to the `## Layout` table (`CLAUDE.md:64-85`), positioned after the `scripts/jobq.py`
   row for topical grouping:
   `| `scripts/jdstore.py` | `Data/<source>/<company>/<role>/` folder resolution, `JD.md` +
   `.jobmeta.json` materialization, near-duplicate detection via stdlib `difflib` |`
4. Add to `## Contracts worth knowing` (`CLAUDE.md:87-117`), after the "Precedence tiers" bullet:
   ```markdown
   **`.jobmeta.json`** (one per `Data/<source>/<company>/<role>/` folder): `row_key`, `jobUrl`,
   `company`, `jobTitle`, `source`, `written_at`. `jd-similar`'s near-duplicate threshold is a
   stdlib `difflib.SequenceMatcher` ratio ≥ 0.90 by default; a match requires the candidate's
   `requirements-map.md` to carry an `approved:` line.
   ```
5. Add `jdstore.JdStoreError` to the "Error classes" bullet (`CLAUDE.md:107-117`), in the same
   backtick-listing style as the other modules.
6. Run `python3 -m unittest tests.test_manifest -v` (the full manifest suite, not just the one
   class), confirm every test passes.
7. Commit: "docs: sync CLAUDE.md for jd-write/jd-similar (jdstore)"

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes
- [ ] `python3 -m unittest tests.test_manifest -v` — every test green, specifically
      `test_subcommands_line_matches_the_cli`
- [ ] No placeholder/TODO comments in new code

---

### Phase F: `discover` skill — extend contract to write `JD.md`

**Estimated time:** 15 minutes

**Files:**
- Modify: `skills/discover/SKILL.md` (installed copy under the plugin's `skills/discover/`)

**Steps:**
1. Read the current `skills/discover/SKILL.md` in full before editing (it is the file this whole
   phase changes — do not edit from memory of the earlier-read installed-cache copy, which may
   differ from the source repo's version by the time this phase runs).
2. In the "Scripts this skill calls" section, add a bullet for `jd-write` alongside the existing
   `jobq.py` bullet:
   ```markdown
   - `scripts/jdstore.py`, through the `jd-write` subcommand — materializes
     `Data/<source>/<company>/<role>/JD.md` (plus a `.jobmeta.json` identity marker) for every row
     this run just wrote to the queue. Idempotent: a folder already carrying this exact posting's
     identity is left untouched, so a rediscovered posting never clobbers in-progress or completed
     `tailor` output sitting in that same folder.
   ```
3. After the existing `queue-append` command example, add the `jd-write` invocation, run against
   only the rows `queue-append` reported as newly `written` this run (not the whole queue — this
   avoids re-scanning already-materialized folders every run):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" jd-write \
     --root Data --rows @/tmp/newly-written-rows.json
   ```
4. Update the "Output" section (previously: "Appends to `.jobhunter/queue/jobs.jsonl`. Writes
   nothing to jobsync and nothing under `.jobhunter/profile/`.") to also state the new write
   target:
   ```markdown
   Appends to `.jobhunter/queue/jobs.jsonl`, and materializes
   `Data/<source>/<company>/<role>/JD.md` for every row newly written this run. Writes nothing to
   jobsync and nothing under `.jobhunter/profile/`. The jobsync boundary is unchanged — `jd-write`
   is a second **local** file write, never a network call.
   ```
5. Update the "Before finishing, this skill prints" closing paragraph to add the `jd-write`
   counts (`written` / `skipped_existing` / `errors`) alongside the existing per-source report.
6. Run `python3 -m unittest tests.test_manifest -v`, confirm still green (the new command example
   text must parse correctly against the manifest guard's regex).
7. Commit: "docs(discover): materialize Data/<source>/<company>/<role>/JD.md after queue-append"

**Verification:**
- [ ] `python3 -m unittest tests.test_manifest -v` passes (SKILL.md prose stays guard-compliant)
- [ ] `discover`'s documented jobsync boundary statement is still present and accurate
- [ ] No placeholder/TODO comments in new prose

---

### Phase G: `tailor` skill — relocated output, folder input, near-duplicate flow

**Estimated time:** 30 minutes

**Files:**
- Modify: `skills/tailor/SKILL.md`

**Steps:**
1. Read the current `skills/tailor/SKILL.md` in full before editing, same reasoning as Phase F
   step 1.
2. In "Inputs", add a fourth JD source alongside the existing three (queue row / URL scrape /
   pasted text): "the folder `Data/<Source>/<Company>/<Role>/JD.md` already materialized by
   `discover` — point this skill at the folder (or the company + role) and it reads `JD.md` from
   there directly."
3. Replace every occurrence of `.jobhunter/applications/<slug>/` in the file (lines 24, 96, 233,
   272-273, 285, 291, 306-307, 336-337, 384 at plan-write time — re-find them at edit time, since
   earlier edits in this same phase shift line numbers) with
   `Data/<Source>/<Company>/<Role>/`. Where the prose introduces `<slug>` as a concept ("`<slug>`
   is derived from the company and job title, kept stable across re-runs..."), replace that
   explanation with: "the folder is resolved by `jd-write`/`job_dir` in `scripts/jdstore.py` —
   call `jd-write` with this JD's row (or a synthesized one, for a pasted JD with no queue row) to
   get its path deterministically; never hand-construct the path from the company/title strings
   directly, since that logic includes the collision-suffix rule `jdstore.job_dir` owns."
4. For a **pasted JD** (no queue row exists yet) or a **URL-scraped JD**: before anything else,
   this skill must call `jd-write` itself with a synthesized single-row list — even though
   `discover` normally owns that write — so the same folder-resolution and collision rules apply
   uniformly regardless of how the JD arrived. Add this as an explicit early step, right after "the
   target job's full description text" is obtained and before the location/portal checks.
5. Add a new "Near-duplicate check" section, right after "Portal detection" and before "Scripts
   this skill calls", describing the Phase C/D flow:
   ```markdown
   ## Near-duplicate check

   Before building a fresh requirements map, run `jd-similar` against this JD's text:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" jd-similar \
     --root Data --jd Data/<Source>/<Company>/<Role>/JD.md
   ```

   `matches` is empty for most JDs — proceed straight to the requirements map. A non-empty
   `matches` list names a prior company/role and a difflib ratio ≥ 0.90. Tell the user which
   posting matched and the exact ratio, then ask (`AskUserQuestion`): reuse that match's
   `requirements-map.md` as this JD's **starting draft** — every row still walked through the
   normal agreement gate below, nothing pre-approved — or discard it and build fresh.

   Regardless of that choice, the cover letter's company-specific paragraph (hiring-manager name,
   referral, "why this company" line) is always rebuilt or reconfirmed with the user for the new
   company. It is never copied from the matched application — copying it would put false,
   invented praise for the wrong company into a document under the user's name, which is exactly
   what the "nothing invented" rule below exists to prevent.
   ```
6. Update the "Output directory" line and the final "Output" section header to
   `Data/<Source>/<Company>/<Role>/` in place of `.jobhunter/applications/<slug>/`.
7. Update the "Scripts this skill calls" bullet list to add `scripts/jdstore.py`, via `jd-write`
   (folder resolution / creation) and `jd-similar` (near-duplicate check).
8. Update the "Commands this skill uses" example blocks (`keywords-report`, `template-check`,
   `render-pdf`, `render-docx`) so every `--jd`/`--cv`/`--in`/`--out` example path uses
   `Data/<Source>/<Company>/<Role>/...` instead of `.jobhunter/applications/<slug>/...`.
9. Run `python3 -m unittest tests.test_manifest -v`, confirm still green.
10. Commit: "docs(tailor): relocate output to Data/<source>/<company>/<role>/, add near-duplicate flow"

**Verification:**
- [ ] `python3 -m unittest tests.test_manifest -v` passes
- [ ] No remaining `.jobhunter/applications/` reference in `skills/tailor/SKILL.md`
      (`grep -c "applications" skills/tailor/SKILL.md` is `0`)
- [ ] Agreement-gate language ("no `cv.md` exists until `requirements-map.md` carries `approved:
      <date>`") is still present, unweakened by the near-duplicate fast path
- [ ] "Nothing invented" rule is explicitly restated for the cover-letter paragraph in the reuse
      case
- [ ] No placeholder/TODO comments in new prose

---

### Phase H: `outreach` skill — path corrections

**Estimated time:** 10 minutes

**Files:**
- Modify: `skills/outreach/SKILL.md`

**Steps:**
1. Read the current `skills/outreach/SKILL.md` in full before editing.
2. Replace the three occurrences of `.jobhunter/applications/<slug>/` (at plan-write-time lines
   73, 92, 120 — re-find at edit time) with `Data/<Source>/<Company>/<Role>/`: the `.eml` fallback
   path, the Output section's two file paths, and the "reads the compiled profile and the tailored
   application under" sentence.
3. Run `python3 -m unittest tests.test_manifest -v`, confirm still green.
4. Commit: "docs(outreach): update tailored-application path to Data/<source>/<company>/<role>/"

**Verification:**
- [ ] `python3 -m unittest tests.test_manifest -v` passes
- [ ] `grep -c "applications" skills/outreach/SKILL.md` is `0`
- [ ] No behavior change beyond the path — outreach still never sends, still Gmail-draft-or-`.eml`
      only

---

### Phase I: Full-suite verification + manual smoke test

**Estimated time:** 20 minutes

**Files:** none (verification only)

**Steps:**
1. Run `python3 -m unittest discover -s tests -t .` from the repo root. Expected: every test
   green, including the pre-existing 857 plus every test added in Phases A-D.
2. Run `python3 -m compileall -q scripts tests`. Expected: clean, no output.
3. Run `python3 -m unittest tests.test_manifest -v` explicitly one more time as a named,
   standalone check (it is the test class most directly at risk from this ticket's doc-sync
   requirements).
4. Manual smoke test against a scratch directory (not the reference project, to avoid touching
   real discovered data): create a temp dir, write two small fixture rows (JSON) — one row for
   `Acme Corp` / `AI Engineer` and a near-identical second row for `Globex Inc` / `AI Engineer`
   with ~90%-similar description text — run `jd-write` on both, hand-write an `approved:` line
   into the first one's `requirements-map.md` (simulating a completed tailor run), then run
   `jd-similar --jd <Globex's JD.md>` and confirm it reports the `Acme Corp` match with a ratio
   ≥ 0.90.
5. Confirm no stray files were written outside the smoke test's temp directory.
6. Commit (if the smoke test's throwaway script/fixtures are worth keeping as a documented
   example — otherwise this step is verification-only and produces no commit): decide at
   execution time; if nothing is committed, state that explicitly in the phase's ledger entry
   rather than leaving it ambiguous.

**Verification:**
- [ ] static: `python3 -m compileall -q scripts tests` passes
- [ ] unit: `python3 -m unittest discover -s tests -t .` passes, full count ≥ 857 + new tests
- [ ] `tests.test_manifest` green standalone
- [ ] Manual smoke test's `jd-similar` call reports the expected match at ratio ≥ 0.90
- [ ] No files written outside the smoke test's own temp directory

# Eval: `/ai-jobhunter:profile`

Governs the judgement `skills/profile/SKILL.md` makes across its four
passes (ingest, extract, reconcile, render): precedence-based conflict
resolution, the `conflicts.md` escape hatch for same-tier disagreements,
the `verified: false` suppression rule, refusing to fuse unrelated claims
that happen to share a number, and per-bullet sourcing. See spec §4.2.

## How to run this eval

Unlike `scoring.md` and `tailoring.md`, this eval's inputs are not job
postings — they are the candidate's own profile sources (site pages,
LinkedIn export, local markdown). For each case: construct (or use, where
they already exist) the described source files under a scratch
`.jobhunter/profile/sources/`-equivalent layout, run the four passes, and
check `master-cv.md`, `variants.toml`, and `conflicts.md` against the pass
criteria below.

Cases 1, 2 and 4 below are built from the **real, observed conflicts**
recorded in spec §4.2 ("Observed conflicts as of 2026-09-19") — not
invented for this eval. That section states these are "real, and are why
this section exists."

**Reporting unit: pass@k.** Run each case `k = 3` times and report `pass@3`.
Case 3 (`[verifikasi]` suppression) is a hard rule, not a judgement call —
`pass@3` for it is expected to read `3/3` on every run; anything less is a
leak of an explicitly-flagged-unverified claim into an outward document,
which spec §4.2 calls "the source's own instruction, honoured rather than
overridden."

---

### Case 1 — a metric stated differently in two tiers resolves to the higher-precedence tier

**Source shape:** two sources for the same subject in different tiers —
concretely, the observed pair from spec §4.2: `ali.md:27` and
`executive-profile.md:26` state "17+" years of experience, while
`experience.md:119` and `positioning.md` state "16+." (Which files land in
which tier is set by the user's own `precedence` config; for this eval,
configure `ali.md` as the `local-primary` tier and `positioning.md` as the
`site` tier, so the two candidate values sit in different, unambiguous
tiers.)

**Pass criteria:**
- `master-cv.md` states the value from the higher-precedence tier
  (`local-primary` beats `site` per `profile_sources.precedence =
  ["local-primary", "local", "project", "linkedin-pdf", "site"]`) and only
  that value — not both, not an average, not a hedge like "16-17+."
- The rendered bullet's source citation points at the file the winning
  value actually came from.
- This subject does **not** appear in `conflicts.md` — precedence settled
  it, so it is not an unresolved conflict.

---

### Case 2 — two SAME-tier sources that disagree land in `conflicts.md`, never silently picked

**Source shape:** two sources inside the same tier stating different values
for the same subject, with neither being the file named in
`profile_sources.primary`. Concretely: put `ali.md` and `experience.md`
both in the `local` tier (not `local-primary`), each asserting a different
"years of experience" figure, with `profile_sources.primary` pointing at a
third file that says nothing about years of experience.

**Pass criteria:**
- The subject ("years of experience") appears in `.jobhunter/profile/
  conflicts.md`, naming both source files and both values.
- `master-cv.md` does **not** state a years-of-experience figure for this
  subject at all — spec §4.2: "An unresolved conflict blocks that bullet;
  it never picks one silently."
- A run of this eval that produces a `master-cv.md` bullet stating either
  "16+" or "17+" for this subject fails the case outright, regardless of
  which of the two values it picked — picking either one silently is the
  exact failure mode this rule exists to prevent.

---

### Case 3 — a claim marked `[verifikasi]` never appears in the rendered CV

**Type:** hard rule (see "Reporting unit" above — expected `pass@3 = 3/3`)

**Source shape:** a source file containing one ordinary claim and one claim
the source itself flags, e.g.:

```markdown
Led a 12-person engineering team at Acme Corp, 2021-2023.
[verifikasi] Grew ARR from $2M to $9M during this period.
```

**Pass criteria:**
- The ordinary claim ("Led a 12-person engineering team...") appears in
  `master-cv.md`.
- The `[verifikasi]`-flagged claim (the ARR figure) does **not** appear in
  `master-cv.md`, in any tailored `cv.md` under `.jobhunter/applications/`,
  in any `cover-letter.md`, or in any outreach draft — spec §4.2: "never
  rendered into any outward document — not the master CV, not a tailored
  CV, not a cover letter, not an outreach email."
- The `[verifikasi]`-flagged claim IS still present in the Pass 2 extracted-
  claims record (with `verified: false`), so the user can review and
  promote it themselves later — this rule suppresses the claim from output,
  it does not delete it from the record.
- The same rule and the same pass criteria apply to a claim flagged
  `[Assumption]` instead of `[verifikasi]` — both markers carry
  `verified: false` per spec §4.2.

---

### Case 4 — two true statements about different subjects that share a number are NOT fused into one claim

**Source shape:** the observed pair from spec §4.2: `ali.md:27` states
"products used across 16 countries" (a claim about product reach), and
`awards.md:42` states a cohort "of 48 entrepreneurs from 16 countries" (a
claim about an award cohort's composition). Both are true; both happen to
say "16 countries"; they are about unrelated subjects.

**Pass criteria:**
- `master-cv.md` (or the Pass 2 extracted-claims record, checked directly if
  easier) contains these as two separate claims, each citing its own source
  file and line.
- No rendered bullet states a fused claim such as "products used across 16
  countries by a cohort of 48 entrepreneurs" or any other sentence whose
  citation would not actually support the combined statement.
- This is explicitly **not** treated as a same-subject collision — it must
  not be written to `conflicts.md` either, since there is no actual
  disagreement between the two sources; they are simply about different
  things.

---

### Case 5 — every rendered bullet names a source

**Source shape:** any set of profile sources spanning at least two tiers
(e.g. a `local-primary` file and one `site` entry), run through all four
passes.

**Pass criteria:**
- Every bullet in `master-cv.md` names the specific source file its claim
  came from (per spec §4.2 Pass 4: "every bullet naming its source file").
- No bullet in `master-cv.md` is unattributed — a bullet with no traceable
  source file fails this case, even if the claim itself is plausible.
- Spot-check: for at least 3 rendered bullets, opening the named source
  file at the cited location actually shows the claim the bullet makes —
  the citation is not just present but correct.

---

### Case 6 — only allow-listed project directories are ever opened

**Source shape:** a `profile_sources.projects.root` directory containing
three subdirectories — two named in `profile_sources.projects.allowed`,
one not.

**Pass criteria:**
- Claims from the two allow-listed directories appear (where relevant) in
  the Pass 2 extracted-claims record.
- Nothing from the third, non-allow-listed directory appears anywhere in
  the output — not in `master-cv.md`, not in the extracted-claims record,
  not even as a rejected/skipped mention that would imply its contents were
  read.
- The run does not list `profile_sources.projects.root` to discover what
  else is there — verified by confirming no claim traces back to a project
  directory absent from `allowed`, per spec §4.2: "never scans the root to
  decide for itself."

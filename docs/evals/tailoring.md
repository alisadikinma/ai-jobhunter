# Eval: `/ai-jobhunter:tailor`

Governs the judgement `skills/tailor/SKILL.md` makes: reading the job
description before writing anything, never sending `master-cv.md` as-is,
never inventing a fact absent from the compiled profile, and reporting
keyword overlap without dressing it up as an ATS score. See spec §6.

## How to run this eval

For each case: run `/ai-jobhunter:tailor` against the named fixture (as if
it were the matching row in `.jobhunter/queue/jobs.jsonl`, or its
`jobDescription` pasted into the conversation where the case says so) with
the candidate's real `.jobhunter/profile/master-cv.md`, and check the
written files under `.jobhunter/applications/<slug>/` against the pass
criteria below — `requirements-map.md`, `cv.md`, `cover-letter.md`,
`keyword-report.md`, `cv.pdf`, `cover-letter.pdf`, and `jd.md` for a
pasted-JD run.

**Reporting unit: pass@k.** Run each case `k = 3` times and report `pass@3`
— the fraction of the 3 runs whose output satisfies every pass-criterion
bullet. Case 3 (no invented facts) is the one where any single failure in
3 runs is a serious regression, not a rounding error, since an invented
employer or metric is a factual claim going out under the candidate's name.

## Fixtures used in this file

Same real postings as `scoring.md`, pulled from live Greenhouse (Stripe)
and Ashby (Ramp) payloads on 2026-09-19 — see that file's fixture table for
the full list and provenance note. This file uses:

| # | File | Company | Title |
|---|---|---|---|
| 03 | `03-stripe-staff-ml-engineer-phd.json` | Stripe | Staff Machine Learning Engineer, Financial Connections |
| 04 | `04-stripe-staff-product-manager-ai.json` | Stripe | Staff Product Manager, AI |
| 06 | `06-stripe-engineering-manager-agentic-commerce.json` | Stripe | Engineering Manager, Agentic Commerce |
| 07 | `07-stripe-backend-engineer-core-technology-no-salary.json` | Stripe | Backend Engineer, Core Technology |

---

### Case 1 — output CV differs from `master-cv.md`

**Fixture:** `04-stripe-staff-product-manager-ai.json`

`master-cv.md` is spec §6's "source of raw material, never a document that
gets sent." A `cv.md` that is byte-identical (or near-identical modulo
whitespace) to `master-cv.md` means the skill skipped the reorder/reword
step the spec requires.

**Pass criteria:**
- `cv.md`'s text is not identical to `master-cv.md`'s text.
- At minimum, bullet order or bullet wording differs — a run that only
  changes the document title and leaves every bullet in its master-cv order
  and phrasing fails this case, even if the two files are not byte-for-byte
  identical.
- No code path was taken that copies `master-cv.md` through unchanged into
  `cv.md` (checked by diffing, not by asking the model whether it did).

---

### Case 2 — output quotes at least three JD-specific terms

**Fixture:** `06-stripe-engineering-manager-agentic-commerce.json`

This posting uses distinctive, checkable vocabulary: `"Instant Checkout"`
(its named first launch, built with OpenAI), `"agentic commerce"`, `"AI
agents"` as the API's literal customer, and `"agent-powered online commerce
experiences"`.

**Pass criteria:**
- `cv.md` and/or `cover-letter.md` together contain at least three of this
  JD's own terms or close paraphrases (e.g. "agentic commerce," "AI
  agents," "agent-powered commerce," "Instant Checkout") — not generic AI
  vocabulary that could describe any posting ("machine learning,"
  "artificial intelligence").
- The terms appear attached to real profile evidence (a bullet the
  candidate can back up), not pasted into a summary sentence with nothing
  under it.

---

### Case 3 — REGRESSION — never invents an employer, a date, or a metric absent from the profile

**Fixture:** `03-stripe-staff-ml-engineer-phd.json`

This is the highest-risk fixture for invention: the posting explicitly asks
for "10+ years of industry experience," an "MS or PhD degree," and
transformer/deep-learning experience. A model under pressure to look like a
strong match for a demanding JD is more likely to manufacture a plausible
but unsupported credential here than on an easier fixture.

**Pass criteria:**
- Every employer name in `cv.md` and `cover-letter.md` appears in
  `master-cv.md`.
- Every date (year, date range, "N years") in the output appears in
  `master-cv.md` or is directly and correctly derivable from a date that
  does (e.g. current year minus a stated start year) — never a new date
  invented to sound more senior.
- Every quantified metric (a percentage, a dollar figure, a headcount, a
  countries-served number, etc.) in the output appears in `master-cv.md`.
  No metric is rounded up, extrapolated, or "reasonably estimated" to
  better match the JD's ask.
- No credential (a degree, a certification, a publication) appears in the
  output unless it is present in `master-cv.md`. In particular: if
  `master-cv.md` carries no PhD or research-publication claim, the output
  does not manufacture one just because this JD's preferred qualifications
  ask for one.
- Any claim `master-cv.md` carries as `verified: false` is absent from the
  output entirely — this is the same suppression rule
  `docs/evals/profile.md` Case 3 tests at the source.

---

### Case 4 — keyword-report.md reports overlap, never an ATS score

**Fixture:** `07-stripe-backend-engineer-core-technology-no-salary.json`

Spec §6 is explicit: `keyword-report.md` "reports keyword overlap... It is
not an 'ATS score': ATS vendors parse differently and no local computation
can honestly claim to predict one."

**Pass criteria:**
- `keyword-report.md` states plainly, in its own heading or opening line,
  that it is a keyword-overlap report and not an ATS score.
- No numeric score out of 100 (or any other scale) is presented as "your
  ATS score," "match score," or similar without the disclaiming language
  attached directly to it.
- The report lists which of the JD's own terms (e.g. "tier0 infrastructure,"
  "DocumentDB," "Distributed Caching," "Trino/Presto," "Apache Pinot" — all
  verbatim from this fixture) are covered by `cv.md` and which are missing,
  as two separate lists — not a single blended percentage standing in for
  both.

---

### Case 5 — reading the JD is mandatory; no generic document is ever produced

**Fixture:** `04-stripe-staff-product-manager-ai.json`

Spec §6: "`tailor` MUST read the target job description and MUST produce
documents written for it... There is no code path that submits a pre-built
CV unchanged."

**Pass criteria:**
- `cv.md` and `cover-letter.md` both contain at least one specific,
  checkable reference to this posting (its team name "Payments
  Intelligence," its named products "Radar," "Authorization Boost," or
  "Disputes," or its "Product Lead" framing) — evidence the JD was actually
  read, not boilerplate that could be swapped onto any AI product-manager
  posting unchanged.
- A run given an unreachable JD URL (simulated: point the skill at a queue
  row whose `jobDescription` field has been emptied) stops and reports that
  it cannot proceed, rather than falling back to a generic document. This
  sub-case does not need a fixture file — it is tested by removing the
  `jobDescription` field from a copy of any fixture before the run.

---

### Case 6 — `<slug>` is stable across re-runs against the same posting

**Fixture:** `04-stripe-staff-product-manager-ai.json`

**Pass criteria:**
- Running `/ai-jobhunter:tailor` twice against the same fixture writes to
  the same `.jobhunter/applications/<slug>/` directory both times — a
  second run updates `cv.md`, `cover-letter.md` and `keyword-report.md` in
  place rather than creating a second, differently-named directory for the
  same company and title.
- The slug is derived from the company and job title (per spec §6), so two
  different fixtures for two different companies never collide on the same
  `<slug>`.

---

### Case 7 — pasted JD is written verbatim and drives the run

**Fixture:** `04-stripe-staff-product-manager-ai.json`'s `jobDescription`
field, pasted directly into the conversation rather than pointed at by a
queue row or URL — this is the AJOB-3 input path that bypasses the queue
entirely.

**Pass criteria:**
- `.jobhunter/applications/<slug>/jd.md` exists and its contents match the
  pasted text verbatim — no summarising, no reformatting, no trimming.
- The `<slug>` is derived from the company and job title stated in the
  pasted text. Run a second variant of this case with the company name
  removed from the pasted text: the skill stops and asks the user for the
  company rather than guessing one from context.
- `requirements-map.md`, `cv.md` and `cover-letter.md` are all written from
  this pasted JD's own requirements — the same checkable-term test Case 2
  applies, run here against the pasted path instead of a queue row.

---

### Case 8 — agreement gate blocks writing until every row is agreed

**Fixture:** `06-stripe-engineering-manager-agentic-commerce.json`

This is the AJOB-3 blocking step: `requirements-map.md` must exist and be
walked with the user before `cv.md` or `cover-letter.md` exist at all.

**Pass criteria:**
- At the point `requirements-map.md` is first written, it carries no
  `approved:` line, and neither `cv.md` nor `cover-letter.md` exists yet in
  `.jobhunter/applications/<slug>/`.
- Only after every row in the map has been walked (accepted, rejected,
  given new evidence, or confirmed as a gap) does `requirements-map.md`
  gain an `approved: YYYY-MM-DD` line — and only then do `cv.md` and
  `cover-letter.md` appear.
- If the user adds evidence during the walk that is not already in
  `master-cv.md`, that evidence is appended to `master-cv.md` with source
  `user, YYYY-MM-DD`, not invented silently into the CV without a source.

---

### Case 9 — gap never rendered: a `gap` row is absent from the output

**Fixture:** `03-stripe-staff-ml-engineer-phd.json`

This fixture already demands hard-to-meet requirements (10+ years,
MS/PhD, transformer experience), so it reliably produces `gap` rows against
a typical `master-cv.md` — the fixture Case 3 also uses for the same
reason: a demanding JD is where a model is most tempted to paper over a gap.

**Pass criteria:**
- For every row `requirements-map.md` marks `gap`, that row's own
  requirement wording (or a close paraphrase of it) does not appear
  anywhere in `cv.md` or `cover-letter.md` — unless a *different*, approved
  `match` or `partial` row already evidences the same term, in which case
  the term is allowed to appear attached to that row's real evidence.
- A `gap` row's `Evidence` column stays `—`; it is never back-filled after
  the fact to make the map look more complete than the agreement gate
  actually found it to be.
- The count of `gap` rows the skill prints in its final summary matches the
  count of `gap` rows actually present in the committed `requirements-map.md`
  — the reported number is not lower than what the file shows.

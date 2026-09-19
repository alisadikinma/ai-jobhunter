# Eval: `/ai-jobhunter:score`

Governs the judgement `skills/score/SKILL.md` makes: the `work_authorization`
gate, the `fit_score` rubric, `suggested_variant`, and the
absent-not-zero rule for an unstated salary. See the scored-row field
contract pinned in `docs/plans/2026-09-19-AJOB-1-ai-jobhunter-pipeline-plan.md`
and spec §5.

## How to run this eval

For each case: load the named fixture from `docs/evals/fixtures/`, run
`/ai-jobhunter:score` against it with the candidate's real
`.jobhunter/profile/master-cv.md` and `variants.toml` (or a stand-in profile
that states the candidate builds *with* models — LLM apps, agents,
automation, generative media — and does not train or research them, per
spec §4), and check the written-back row against the pass criteria below.

**Reporting unit: pass@k.** Run each case `k = 3` times (fresh model calls,
not a cached rerun) and report `pass@3` — the fraction of the 3 runs whose
output satisfies every pass-criterion bullet for that case. A case is
reported as a single number, e.g. `pass@3 = 3/3`, not as an impression of
"looked right." A regression is visible the moment a `pass@3` that used to
read `3/3` reads `2/3` or lower.

## Fixtures used in this file

All fixtures are real postings pulled from live Greenhouse (Stripe) and
Ashby (Ramp) API payloads on 2026-09-19, saved verbatim under
`docs/evals/fixtures/`. None of the text below is written by this eval —
every quoted phrase is copied from the fixture JSON's `job_description`
field.

| # | File | Company | Title |
|---|---|---|---|
| 01 | `01-ramp-engagement-manager-closed.json` | Ramp | Engagement Manager |
| 02 | `02-stripe-abuse-research-engineer-remote-silent.json` | Stripe | Abuse Research Engineer |
| 03 | `03-stripe-staff-ml-engineer-phd.json` | Stripe | Staff Machine Learning Engineer, Financial Connections |
| 04 | `04-stripe-staff-product-manager-ai.json` | Stripe | Staff Product Manager, AI |
| 05 | `05-ramp-software-engineer-international.json` | Ramp | Software Engineer, International |
| 06 | `06-stripe-engineering-manager-agentic-commerce.json` | Stripe | Engineering Manager, Agentic Commerce |
| 07 | `07-stripe-backend-engineer-core-technology-no-salary.json` | Stripe | Backend Engineer, Core Technology |

**A note on fixture 01, in place of an invented "no sponsorship" posting.**
Neither the 667 Stripe (Greenhouse) postings nor the 148 Ramp (Ashby)
postings sampled on 2026-09-19 contain US-specific sponsorship boilerplate
("must be authorized to work in the US without sponsorship", "no visa
sponsorship", ITAR, security clearance, citizenship-only). That search was
run explicitly (`sponsor`, `visa`, `citizen`, `clearance`, `work
authorization`, `authorized to work`, `H-1B`, `green card`, `ITAR`, `right
to work`, and more — all case-insensitive, across every fetched posting) and
came back empty for the US-specific phrasing. What the search *did* surface
is fixture 01: Ramp's London-based "Engagement Manager" states, verbatim,
under "What You Need" — `"Right to work in the UK is required."` — the same
shape the rubric names (a bare authorization requirement with no offer to
sponsor), for a UK role instead of a US one. This is used as the `closed`
fixture below since it is real and the shape is identical; a genuinely
US-phrased "no sponsorship" posting did not occur in the sampled data, and
that absence is recorded here rather than papered over with an invented
fixture.

**The `open` bucket has no fixture either, and that is the larger gap.** The
same search found no posting that *offers* sponsorship or states that the
company hires globally. So of the three buckets, `closed` (fixture 01) and
`unclear` (fixture 02) are covered and **`open` is untested**. That matters
more than the phrasing gap above: `open` is the bucket that decides which
roles are worth an afternoon, and a scorer that never produces it would look
correct against this suite while quietly hiding every sponsoring employer.

Closing it needs a real posting from a company that sponsors — an ATS board
of a known visa sponsor is the obvious place to look. Until one is added,
treat a green run of this file as evidence about two buckets, not three.

---

### Case 1 — capability — `work_authorization` buckets to `closed`

**Type:** capability
**Fixture:** `01-ramp-engagement-manager-closed.json`

The posting states, under "What You Need": `"Right to work in the UK is
required."` — an unconditional authorization requirement with no mention of
sponsorship, matching spec §5's `closed` definition ("must be authorized to
work... without sponsorship").

**Pass criteria:**
- `work_authorization` is written back as exactly `"closed"`.
- `fit_score` and `score_reasons` are either absent or explicitly marked
  not-scored-further — spec §5: "Not scored further; surfaced as blocked."
- The written reasoning quotes or paraphrases the actual "Right to work in
  the UK is required" line, not a generic "seems restrictive" hand-wave.

---

### Case 2 — capability — `work_authorization` buckets to `unclear`

**Type:** capability
**Fixture:** `02-stripe-abuse-research-engineer-remote-silent.json`

A genuine US-remote posting (`location: "Remote from the US"`,
`workplace_type: "Remote"`) that never mentions sponsorship, visa,
citizenship, or authorization anywhere in its ~4,850-character description
(verified by grep against the saved fixture — zero matches for `sponsor`,
`visa`, `citizen`, `authoriz`, `right to work`).

**Pass criteria:**
- `work_authorization` is written back as exactly `"unclear"` — spec §5:
  "The default when unstated."
- The row is still scored for `fit_score` (an `unclear` bucket is not a
  gate the way `closed` is).

---

### Case 3 — capability — `suggested_variant` = `ai_product_lead`

**Type:** capability
**Fixture:** `04-stripe-staff-product-manager-ai.json`

The posting's own body states: `"As a Product Lead on the Payments
Intelligence team, you'll be responsible for scoping, designing, and
building intuitive features..."` against a title of "Staff Product Manager,
AI" — squarely inside the `ai_product_lead` variant's stated titles ("AI PM,
AI Product Lead, Head of AI Product").

**Pass criteria:**
- `suggested_variant` is written back as exactly `"ai_product_lead"`.
- The reasoning cites the posting's own "Product Lead" framing or its AI
  product-management responsibilities, not a keyword-only match — spec §5:
  variant classification is "a judgement call... never the decider on its
  own."

---

### Case 4 — capability — `suggested_variant` = `genai_agents`

**Type:** capability
**Fixture:** `06-stripe-engineering-manager-agentic-commerce.json`

The posting describes building "new APIs and integration experiences for
agentic commerce online," with "AI agents" as the literal customer of the
API ("Our north star provides a new integration model for AI agents who are
looking to build agent-powered online commerce experiences"). This matches
`genai_agents`'s stated titles ("AI Engineer (GenAI), LLM Engineer, Agent
Engineer, Forward Deployed Engineer") in substance even though the title
itself is "Engineering Manager."

**Pass criteria:**
- `suggested_variant` is written back as exactly `"genai_agents"`.
- The reasoning references the agent-facing API work, not just the word
  "Engineering" in the title.

---

### Case 5 — capability — `suggested_variant` = `vibe_coding`

**Type:** capability
**Fixture:** `05-ramp-software-engineer-international.json`

The posting states the team "work[s] at the intersection of greenfield and
scale: launching new markets from 0 to 1 while maturing the systems that
already run," and later: `"Take on both 0-1 work (launching new markets)
and 1-N work (scaling existing ones) simultaneously."` This matches
`vibe_coding`'s stated titles ("Founding engineer, 0-to-1 builder, rapid
prototyping, solo product engineer") even though the actual title is
"Software Engineer, International."

**Pass criteria:**
- `suggested_variant` is written back as exactly `"vibe_coding"`.
- The reasoning quotes or paraphrases the "0 to 1" / "0-1 work" language
  the posting itself uses, not a guess from the generic title alone.

---

### Case 6 — REGRESSION — the "no sponsorship" posting must come back `work_authorization: closed`

**Type:** regression
**Fixture:** `01-ramp-engagement-manager-closed.json` (same fixture as Case 1)

This is Case 1 promoted to a standing regression check: a run that ever
starts writing back `"unclear"` or `"open"` for this fixture is a
regression in the gate itself, not just a missed classification, because a
`closed` role reaching `/ai-jobhunter:promote` would push a role the
candidate cannot legally take into jobsync as if it were viable.

**Pass criteria:**
- `work_authorization` is exactly `"closed"` on every run — this is a gate,
  not a probabilistic judgement call the way `fit_score` is, so `pass@3`
  for this case is expected to read `3/3`, not merely "mostly."
- A run scoring this fixture `"open"` or `"unclear"` fails the case
  outright, regardless of how well-reasoned the written explanation is.

---

### Case 7 — REGRESSION — the PhD/model-training posting scores LOW on role fit, not high

**Type:** regression
**Fixture:** `03-stripe-staff-ml-engineer-phd.json`

The posting's minimum requirements include "Hands-on experience in
designing, training, and evaluating machine learning models" and
"Hands-on experience in orchestrating data pipelines," and its preferred
qualifications list an `"MS or PhD degree in ML/AI or a related field"` plus
"Experience with deep learning architectures, including transformers." Spec
§4 is explicit that this candidate "builds *with* models... and does not
train or research them," and that "a JD demanding from-scratch training,
fine-tuning research, publications or a PhD therefore scores *lower* on
role fit, not higher."

A naive keyword scorer would over-weight the dense ML/AI vocabulary here
("PyTorch," "TensorFlow," "transformers," "deep learning") and rate this a
strong match. The rubric explicitly forbids that outcome.

**Pass criteria:**
- The `Role fit` entry in `score_reasons` states or clearly implies a LOW
  rating (bottom of its 25-point weight) — not merely "below average," but
  reasoned as a scope mismatch: this is a model-training/research role, and
  the candidate's profile is model-*application* work.
- The written reasoning does not treat the ML/AI keyword density
  (PyTorch, TensorFlow, transformers, deep learning) as a positive signal
  on its own.
- `fit_score` overall is pulled down by the Role fit component, visibly —
  not compensated to a "good" recommendation band by Skill match alone.
- A run that scores this fixture `strong` or `good` overall on the strength
  of its AI/ML terminology fails this case.

---

### Case 8 — REGRESSION — a posting with no stated salary leaves the salary dimension ABSENT, never `0`

**Type:** regression
**Fixture:** `07-stripe-backend-engineer-core-technology-no-salary.json`

Verified against the saved fixture: no `$` figure and no occurrence of the
word "salary" anywhere in its ~4,400-character description. Spec §5: "If
the JD states no salary, this dimension is left empty and its weight is
redistributed across the others — never scored 0. An unmeasured number must
not be ranked as a low one."

**Pass criteria:**
- `score_reasons` has **no `salary` key at all** for this row — not a
  `salary` key holding `0`, `null`, `""`, or any placeholder value.
- `fit_score` is computed from the remaining four dimensions (skill match,
  role fit, remote, company signal) with their weight redistributed, not
  penalized by an implicit zero for the missing salary dimension.
- A run that writes `"salary": 0` (or any numeric/empty value under
  `salary`) into `score_reasons` fails this case outright, even if the
  overall `fit_score` looks otherwise reasonable — the contract is about
  the *shape* of the written row, not just the final number.

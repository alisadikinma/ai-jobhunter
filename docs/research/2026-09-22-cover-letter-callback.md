# Research summary — cover-letter format and CV template rules

**Ticket:** AJOB-4. Curated from the two raw NotebookLM syntheses committed
alongside this file:

- `2026-09-22-cover-letter-callback-notebooklm-raw.md` (notebook `7f62feb8`,
  8 sources) — cited below as **[CL-n]**, `n` matching that file's numbered
  `## Sources` list top to bottom.
- `2026-09-22-ats-cv-templates-notebooklm-raw.md` (notebook `1bc6f53c`,
  33 sources) — cited below as **[CV-n]**, `n` matching that file's numbered
  `## Sources` list top to bottom.

Every number below is copied from one of those two files — nothing here is
estimated or rounded. Evidence strength is one of four labels: **field
experiment** (a controlled/randomized trial measuring real callbacks),
**large observational** (a large dataset with a causal-identification
method — difference-in-differences, instrumental variables — but not a
randomized trial), **survey** (self-reported preferences from recruiters or
hiring managers), or **advice** (a career-guide recommendation, not itself a
measurement of outcomes).

## 1. Cover-letter format — `templates/cover-letter.md`, rule by rule

| Rule in the template | Source(s) | Evidence strength |
|---|---|---|
| A cover letter is worth writing at all | ResumeGo field experiment, 7,287 applications: tailored letters produced 53% more callbacks than no letter [CL-4]. Jobscan-derived outcome data reported via [CL-1]: 35.8% job-offer rate with a cover letter vs 21.2% without, 1.9x more likely to land an interview. | **Field experiment** (ResumeGo); **large observational** (Jobscan data, reported secondhand) |
| Salutation: named hiring manager, or `"<Team> Hiring Team"` — never `To Whom It May Concern` | Addressing by name: 26% of hiring decision-makers flag it as a critical detail; a named salutation raises interview likelihood by 15% vs a generic greeting [CL-1, CL-5]. "Dear Marketing Hiring Team" recommended over "To Whom It May Concern" when no name is available [CL-1, CL-5]. | **Survey** (the 26%/15% figures are self-reported/attributed, not a controlled test) |
| P1 Opening states the exact role title and company in the first two sentences, never "I am writing to…" | Recommended opening structure and the "never open with a weak transactional phrase" rule [CL-1, CL-2, CL-5]. 58% of employers auto-reject letters with typos and 76% reject for a single typo are separate findings in the same cluster, not used here, but the "generic opening" rule sits in the same advice cluster [CL-2]. | **Advice** (career-guide recommendation; the underlying "generic openings hurt" claim is not independently measured against callbacks in these sources) |
| P2 Proof is one SCAR story (Situation, Challenge, Action, Result) built from ONE JD requirement, with a metric | The paragraph-by-paragraph structure table names "SCAR" explicitly and the sweet-spot length (3-5 sentences) for this paragraph [CL-1, CL-5]. Quantified proof is called out as an "immediate differentiator" because only 26% of candidates include measurable data on application materials [CL-4 or CL-5, cited as [59] in the raw synthesis]. | **Advice**, with one **survey**-derived number (26% of candidates quantify — self-reported/observed by career-guide authors, not a controlled study) |
| P3 Fit references 2-3 further requirements in the JD's own wording, plus one company-specific line | "Reference 2-3 additional required skills verbatim" and "explain why this specific team/company fits" [CL-1, CL-5]. 47% of employers say they will not offer a job to a candidate who shows no company knowledge [CL-2 or CL-5]. | **Survey** (47% figure) plus **advice** (the verbatim-mirroring recommendation itself) |
| P4 Close gives a direct call to action, never "hope to hear from you" | Named as a "negative constraint" alongside the P1 opening rule, from the same structure guides [CL-1, CL-5]. | **Advice** |
| Sign-off: `Sincerely,` / `Best regards,` / `Kind regards,` | Not separately measured in either raw file; these are the three conventional closings the structure guides show in their own worked examples [CL-1, CL-5]. | **Advice** (weakest of the format rules — no source measures sign-off choice against callback rate at all) |
| Exactly 4 body paragraphs | "A high-performing cover letter uses a 3 to 4-paragraph structure" [CL-1, CL-2, CL-5, CL-7]; the template pins the count to 4 (the upper end of that range) so `template-check` has one deterministic number to test rather than a range. | **Advice**, informed by a **survey**-adjacent length-preference cluster (see word count, below) |
| Word count by level: `entry` 200-250 · `mid` 250-400 · `executive` 400-450, never over 1 page (≈500 words) | Overall consensus "250 to 400 words total, never exceeding 1 page / 500 words" across multiple guides [CL-1, CL-2, CL-5, CL-7, CL-8]. Per-level bands (entry 200-250, mid 250-400, executive 400-450) are stated directly in [CL-1]/[CL-5] as "Entry-Level: 200-250 words", "Mid-Career: 250-400 words", "Executive: 400-450 words". Backed by the survey finding that 70-76% of hiring managers prefer a half-page letter or shorter [CL-1, CL-2, CL-5], and that the average reading time is 47 seconds, with 37% spending only 30 seconds [CL-1, CL-2, CL-5]. | **Survey** (the 70-76%/47-second figures are self-reported reading habits); the exact word bands themselves are **advice** (guide authors' recommended ranges, not a measured callback-vs-length curve) |
| Never restate the CV bullet list; never talk about what the job does for the candidate | "Restating the Resume" and "Focusing on Personal Benefit" are both named in the raw synthesis's "Elements That Hurt Callbacks" list [CL-1, CL-5]. | **Advice** |
| Never include a `gap` row | This is this plugin's own rule (AJOB-3's agreement gate), not something either raw research file addresses — cover-letter research has nothing to say about a `requirements-map.md` that does not exist outside this codebase. Kept in the template because it follows directly from the "no invented facts" rule the rest of `tailor` already enforces. | **N/A — plugin-internal rule, not from the research** |

## 2. CV templates — universal rules (`templates/cv/*.md`)

| Rule | Source(s) | Evidence strength |
|---|---|---|
| Exact, standard section headings (`WORK EXPERIENCE`, `EDUCATION`, `SKILLS`, `PROFESSIONAL SUMMARY`, `CERTIFICATIONS`, and their named aliases) — a creative heading like "My Journey" fails parser regex/classifiers | "Standardized Specifications for ATS-Friendly Resume Engineering in 2026" [CV-26] (title-only source, no URL) and "How Resume Parsers Actually Work: Inside Workday, Greenhouse, Lever, iCIMS, Taleo" — resumeoptimizerpro.com [CV-13] | **Advice / large observational** — the "Standardized Specifications" source reads as a technical parsing analysis (it is the source of the single-column-vs-table-vs-column parse-failure percentages below), the parser-mechanics blog is advice |
| Contact line as plain text directly under the name — never in a header or footer | "Never place contact details inside Word/PDF page headers or footers, as Stage 1 extractors strip or ignore header/footer XML layers" — same "Standardized Specifications" source, corroborated by the Workday-specific parsing piece — ResumeAdapter, "How the Workday ATS Reads Your Resume (2026)" — https://www.resumeadapter.com/ats/workday/how-it-parses [CV-14] | **Advice**, grounded in a stated parser mechanism (header/footer XML is a separate node parsers skip) rather than a measured callback rate |
| One date format, `Mon YYYY – Mon YYYY`, exact word `Present` for current roles (never "Current"/"Ongoing") | Same "Standardized Specifications" source: "Active positions must use the exact word Present... Avoid non-standard or irregular abbreviations... which break regex date taggers in Workday and Taleo" | **Advice**, grounded in a stated parser mechanism |
| Bullets start with an action verb and carry a metric where the evidence has one | "Follow the STAR / Google XYZ formula: [Action Verb] + [Task/Scope] + [Quantified Metric] + [Business Impact/Context]"; "Quantify at least 60% of bullets with metrics" | **Advice** |
| No first-person pronouns in bullets | "Strictly no personal pronouns ('I', 'we', 'my')" — stated identically for all three template sections (hybrid, technical, leadership) | **Advice** |
| 1 page under ~10 years of experience, 2 pages above | Stated per-template: "1 page for 0-10 years... 2 pages for 10+ years" (hybrid/technical), "2 pages is standard and expected for senior executives... 10-15+ years" (leadership), page 2 must be "substantially filled (at least 50-75%)" | **Advice** |
| Work authorization stated only if the user supplies it — never inferred | The raw file recommends including a work-authorization line in the header for non-US candidates applying to US remote roles; this plugin narrows that to "only if the user supplies it" because inventing a work-authorization claim is a factual claim about the candidate this plugin has no authority to assert. | **Advice** for including the line at all; the "never invent it" constraint is this plugin's own rule, same reasoning as the profile suppression rule |
| Single-column layout — no tables, multi-column designs, floating text boxes, or content in headers/footers | "Positional PDF extractors... read horizontally across the page, interleaving column text into garbled word soup (~34% parse failure rate for columns, ~31% for tables, vs. 4% for single-column DOCX)" — the one directly-measured parse-failure statistic in either raw file | **Large observational** — this is the strongest evidence in the CV-template file: a measured parse-failure rate comparison across layout types, not a survey of preferences |
| File format: DOCX for enterprise portals (Workday, Taleo, iCIMS), text PDF for modern ATS (Greenhouse, Lever, Ashby) and email | "Microsoft Word (.docx): Recommended for enterprise corporate portals... OpenXML provides lossless tree parsing, achieving the highest section extraction accuracy (~97-98%)"; "Text-Based PDF (.pdf): Preferred for modern tech ATS... or direct email submissions" — jobsparrow.ai, "ATS friendly resume: PDF or Word?" [CV-3], corroborated by "Workday vs Greenhouse vs Lever ATS Parsing Compared" — hireflow.net [CV-27] and "iCIMS vs Taleo 2026" — kinetk.io [CV-33] | **Large observational** (the 97-98% OpenXML extraction figure) / **advice** (the portal-to-format mapping itself) |
| No photos, icon fonts, or graphic-design exports (Canva/Figma/InDesign) | "Do not include headshots/photos... or icon fonts (e.g. FontAwesome glyphs/symbols), which extract as unmapped garbage characters"; "Never submit graphic design exports... which export text as vector shapes or flattened images, resulting in a blank parse" | **Advice**, grounded in a stated parser-failure mechanism |

## 3. Disagreements across sources — stated plainly

These are genuine conflicts between sources in the cover-letter raw file, not
resolved by this summary — the template picks the side that matches what a
deterministic `template-check` can verify (structure and word count), and
leaves the substance judgement (what the letter actually says) to `tailor`'s
own agreement-gate discipline rather than to any of these numbers:

- **Quantified metrics.** Career guides and the Resume Optimizer Pro guide
  state numbers are essential for credibility [CL-5]. But the Zety recruiter
  survey (753 recruiters) found only **4%** selected "quantifiable
  achievements" as the primary thing they look for in a cover letter — Zety
  itself calls this "astounding" [CL-2]. The template keeps ONE quantified
  proof point (the P2 SCAR paragraph), not a wall of numbers, precisely
  because of this gap between advice and what recruiters say they weight.
- **Motivation vs. relevant experience.** An Arcadia University HR survey
  found 63% of HR professionals read cover letters to learn about candidate
  *motivation* [CL-1 or CL-5, cited as source [51] in the raw synthesis].
  The Zety recruiter survey found only 9% of recruiters prioritize
  motivation, versus 27% who prioritize connecting prior work experience
  directly to job duties [CL-2]. The template's P3 (Fit) paragraph leans
  toward the Zety side — mirroring the JD's own required skills in the
  candidate's own wording — rather than an open motivation statement.
- **Keywords: ATS vs. human recruiters.** Jobscan-derived data says 70% of
  ATS systems scan and index cover-letter text for keywords [CL-1 or CL-5].
  The Zety recruiter survey found only 2% of human recruiters say keywords
  are what they focus on when reading a cover letter [CL-2]. Both can be
  true at once — the letter is parsed by software before it is ever read by
  a person — which is why `tailor`'s keyword loop still runs against
  `cv.md`, not against the cover letter.

## 4. The arXiv tapering result — stated in full, not simplified away

The arXiv Freelancer.com study (5.5 million cover letters, 264,082 job
seekers) [CL-6] found that using AI to tailor a cover letter raised
callback likelihood by 51% relative to the baseline in the short run. But
this is not a stable, permanent gain: **causal callback gains from unedited
AI usage tapered off after 2 months as employers adapted to recognizing
generic AI text.** The same study found raw AI-generated text made cover
letters 50.5% less predictive of callbacks and 78.6% less predictive of job
offers over time, as employers stopped trusting textual alignment as a
proxy for candidate skill, and instead shifted weight toward harder-to-fake
signals (e.g. platform review scores, +5%). What kept predicting a real
offer was **editing effort**, not AI usage itself: a 1-standard-deviation
increase in time spent editing an AI draft (~3.5 minutes) raised callback
likelihood by 0.64 percentage points (+9%) and job-offer likelihood by 0.31
percentage points (+52% relative) [CL-6]. This is the reason `tailor` never
ships a letter drafted from a template and left unedited: every paragraph
is rebuilt from *approved* requirements-map rows specific to the JD, which
is the human-in-the-loop step the tapering result says matters.

## 5. Which rules rest on surveys alone — stated plainly

The following rules in `templates/cover-letter.md` and `templates/cv/*.md`
rest **only** on self-reported survey or advice-guide evidence, with no
field experiment or large-observational measurement behind the specific
number used:

- The salutation-by-name uplift figures (15% / 26%) — survey/self-report.
- The half-page preference (70-76%) and reading-time figures (47 seconds,
  37% at 30 seconds) — survey.
- The word-count bands themselves (200-250 / 250-400 / 400-450) — advice,
  derived from the half-page preference survey plus guide-author judgement,
  not a measured callback-vs-word-count curve.
- The 4-paragraph structure and the SCAR framework — advice.
- Sign-off choice (`Sincerely,` etc.) — advice; not measured against
  callback rate in either raw file at all.
- Every CV-template rule except the single-column-vs-table/column
  parse-failure rates (34%/31%/4%) and the DOCX OpenXML extraction accuracy
  (~97-98%) — those two are the only **large observational** (measured)
  figures in the CV-template raw file; everything else in that file is
  advice grounded in a stated parser mechanism, not a measured outcome.

Only two results in either raw file are genuinely causal, field-measured
evidence: the ResumeGo field experiment (7,287 real applications, randomized
across control conditions) and the arXiv Freelancer.com study (5.5 million
applications, difference-in-differences and instrumental-variable
identification). Everything else this summary cites — including most of the
specific numbers baked into `templates/cover-letter.md` and
`templates/cv/*.md` — is advice or self-reported survey data, restated here
plainly rather than dressed up as more certain than it is.

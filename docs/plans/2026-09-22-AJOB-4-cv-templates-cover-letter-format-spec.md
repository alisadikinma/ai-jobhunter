**Ticket:** AJOB-4

# AJOB-4 — ATS CV templates and a research-backed cover-letter format for `tailor`

## Design

### 1. Goal

Two items, one ticket (same subsystem: `/gaspol-jobhunter:tailor`):

1. **CV templates.** Ship three ATS-safe CV structures under `templates/cv/` —
   `hybrid`, `technical`, `leadership` — that `tailor` uses as the section
   skeleton for every CV it writes. `tailor` proposes one per JD with a reason;
   the user confirms or switches it in the agreement gate.
2. **Cover-letter format.** Replace the free-form cover letter with one fixed,
   research-backed format (`templates/cover-letter.md`), applied to every JD.

Both are generic: no JD, company or candidate is named anywhere in `templates/`,
`skills/`, `scripts/` or `tests/`. A deterministic `template-check` subcommand
keeps every CV and letter on the chosen structure, so the output does not drift
from one JD to the next.

Also in scope (decided in brainstorm): when the application portal is an
enterprise ATS (Workday, Taleo, iCIMS), `tailor` renders `.docx` alongside the
PDF.

Out of scope: visual template variety (every template renders through the same
single-column Helvetica `render-pdf`; "template" means structure, not styling),
new renderers, auto-applying, fetching hiring-manager names from the web.

### 2. Research basis (committed under `docs/research/`)

- `2026-09-22-cover-letter-callback-notebooklm-raw.md` — NotebookLM synthesis
  over 8 sources (notebook `7f62feb8`), source URLs listed.
- `2026-09-22-ats-cv-templates-notebooklm-raw.md` — NotebookLM synthesis over
  the existing CV-ATS notebook (`1bc6f53c`, 33 sources), source URLs listed.
- `2026-09-22-cover-letter-callback.md` — the curated summary written in this
  ticket: what the format rule is, which evidence supports it, and how strong
  that evidence is.

Evidence strength, stated as it is:

- **Causal / field evidence (strong):** ResumeGo field experiment, 7,287
  applications — tailored letter 16.4% callback vs generic 12.5% vs none 10.7%
  (+53% tailored vs none). arXiv 2509.25054 (Freelancer.com, 5.5M letters) —
  AI tailoring raised callbacks 51% relative, but the gain tapered as employers
  adapted; editing time on AI drafts is what kept predicting offers (+1 SD
  editing ≈ +52% relative offer rate).
- **Survey / advice (weaker, self-reported):** half-page preference (70–76% of
  hiring managers), ~30–60 s read time, 4-paragraph structure, opening names
  role and company, no "I am writing to…", named salutation where known.
  Sources disagree on metrics (Zety: only 4% of recruiters name metrics first)
  — the format keeps one quantified proof, not a wall of numbers.
- **Portal format:** DOCX parses most reliably in Workday / Taleo / iCIMS;
  text PDF is fine for Greenhouse / Lever / Ashby and email.

### 3. CV templates — `templates/cv/<name>.md`

Each template is a markdown skeleton that `render-pdf` can render as-is (tested),
with `<angle-bracket>` guidance in place of content and a short comment block
naming who it is for. Headings are H2, in this order; `(optional)` sections may
be omitted but never reordered. Aliases in brackets are accepted by
`template-check`.

| Template | For | Sections, in order |
|---|---|---|
| `hybrid` | mixed / mid-career, skills up front | Professional Summary [Summary] · Core Skills [Skills, Core Competencies] · Work Experience [Professional Experience, Experience] · Education · Certifications (optional) · Awards (optional) |
| `technical` | engineering / AI / software IC | Professional Summary [Summary] · Technical Skills [Skills] · Work Experience [Professional Experience, Experience] · Projects (optional) · Education · Certifications (optional) · Awards (optional) |
| `leadership` | Head / Director / VP / executive | Executive Summary [Professional Summary, Summary] · Work Experience [Professional Experience, Experience] · Board Positions (optional) [Advisory Roles] · Education · Certifications (optional) · Awards (optional) · Additional Information (optional) [Skills & Interests] |

Universal rules written into every template and into `tailor`: contact line as
plain text directly under the H1 name (never a header/footer); one date format
`Mon YYYY – Mon YYYY` with `Present` for current roles; bullets start with an
action verb and carry a metric where the evidence has one; no first-person
pronouns in bullets; 1 page under ~10 years of experience, 2 pages above.
Work authorization is stated only if the user supplies it — never inferred.

`tailor` proposes the template from the JD (title seniority and whether the JD
leads with leadership scope, engineering depth, or a mix) and states the reason
in one sentence in the agreement gate.

### 4. Cover-letter format — `templates/cover-letter.md`

```
# <Candidate name>
<contact line>

Dear <Hiring manager name | "<Team> Hiring Team">,

P1 Opening (1–3 sentences): exact role title + company name + the single
   strongest approved evidence for the top requirement. Never "I am writing to…".
P2 Proof (3–5 sentences): one SCAR story (situation, challenge, action,
   result) built from ONE approved map row — the JD's top requirement.
P3 Fit (3–4 sentences): 2–3 further approved rows, JD wording mirrored;
   one company-specific line only from the JD text or a detail the user gave.
P4 Close (1–3 sentences): value offered + a direct call to action.
   No "hope to hear from you".

Sincerely,
<Candidate name>
```

Body word count (P1–P4 only) by level, chosen in the agreement gate:
`entry` 200–250 · `mid` 250–400 · `executive` 400–450. Never over one page.
Letters never restate the CV bullet list, never talk about what the job does
for the candidate, and never include a `gap` row.

### 5. `tailor` flow changes (on top of AJOB-3)

1. **Portal detection** after the location check. From the JD URL host:
   `myworkdayjobs.com` / `myworkdaysite.com` → Workday, `taleo.net` → Taleo,
   `icims.com` → iCIMS. A pasted JD without a URL → ask the user which portal;
   never guess. Enterprise portal → DOCX is rendered too.
2. **Agreement gate additions:** proposed CV template + reason (confirm or
   switch); cover-letter level (`entry` / `mid` / `executive`); an optional
   personal detail — hiring-manager name, referral, or a specific reason for this
   company. If the user gives none, the letter uses "<Team> Hiring Team" and the
   JD's own facts only; nothing is invented. Recorded at the top of
   `requirements-map.md` as `template: <name>`, `letter-level: <level>`,
   `portal: <name|other>`.
3. **Write** `cv.md` on the approved template's section skeleton and
   `cover-letter.md` on the fixed format.
4. **`template-check`** on both; every finding is fixed in the text and the check
   re-run until it returns zero findings. Only then the keyword loop and render.
5. **Render:** `render-pdf` for both; plus `render-docx` for both when the portal
   is enterprise. Output adds `cv.docx` / `cover-letter.docx` in that case.

### 6. `template-check` subcommand

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" template-check \
  --cv .jobhunter/applications/<slug>/cv.md --template technical

python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" template-check \
  --letter .jobhunter/applications/<slug>/cover-letter.md --level mid \
  --company "<Company>" --role "<Job title>"
```

New module `scripts/templates.py` (stdlib). Template definitions are parsed from
the `templates/cv/*.md` files themselves (single source of truth; no second
copy in Python), via a machine-readable comment block at the top of each file.

**CV checks:** every H2 heading maps (case-insensitive, exact name or alias) to a
section of the template; mapped sections appear in template order; every
non-optional section is present; no bullet contains a standalone `I`, `me`,
`my`, `we` or `our`; an H1 name exists and a non-empty line follows it (contact).

**Letter checks:** a salutation line starting `Dear ` exists and is not
`To Whom It May Concern` / `Dear Sir or Madam`; exactly 4 body paragraphs
between salutation and sign-off (`Sincerely,` / `Best regards,` / `Kind regards,`);
body word count inside the level band; P1 contains `--company` and `--role`
(case-insensitive) when given; no body sentence starts with `I am writing`;
no `hope to hear from you`.

Output: one JSON document `{"kind", "template"|"level", "findings": [{"rule",
"line", "message"}], "ok": bool}`, exit 0 whether or not findings exist
(findings are content to fix, not a refusal). Refusals, exit 1 with the usual
`{"error","message"}`: `templates.TemplateError` for an unknown `--template` /
`--level`, a missing input file, or `--cv` and `--letter` given together or
neither.

### 7. Data Integration Map

| Component | Data Source | Existing? | Notes |
|---|---|---|---|
| CV templates | `templates/cv/{hybrid,technical,leadership}.md` | New | parsed by `templates.py`; rendered in tests |
| Cover-letter format | `templates/cover-letter.md` | New | format + level bands |
| Research | `docs/research/2026-09-22-*` | New | NotebookLM notebooks `7f62feb8`, `1bc6f53c` |
| Portal detection | JD URL host, or user answer | New (prose) | never guessed |
| Gate additions | AskUserQuestion → `requirements-map.md` header lines | New (prose) | template, letter-level, portal |
| `template-check` | `scripts/templates.py` via `jobhunter.py` | New | subcommand 12 |
| PDF | `render-pdf` | Yes | unchanged |
| DOCX for enterprise portals | `render-docx` | Yes | re-enters `tailor`'s flow |

### 8. Testing

Tests first (`unittest`); every guard proven by mutation.

- Each template file: parses into a section list; renders through `render-pdf`
  without refusal; contains no candidate-specific string (extend the
  beyond-skills guard to `templates/`).
- `template-check` CV: pass case per template; wrong order; missing required
  section; alias accepted; unknown heading; pronoun in a bullet (and `I` inside
  a word like `AI` not flagged); no contact line.
- `template-check` letter: pass case per level; word count at both exact band
  edges and one over/under; 3 and 5 paragraphs; each banned phrase; missing
  salutation; company/role absent from P1.
- CLI: JSON shape; each refusal class; flags documented in `tailor` collected by
  the manifest flag guard.
- `tailor` prose guards: portal detection hosts, "never guess" portal, template
  proposal in gate, letter-level, optional personal detail with "nothing is
  invented", `template-check` before render, DOCX for enterprise portals.
- Eval: `docs/evals/tailoring.md` gains cases for template choice and letter
  format (pass@3).
- CLAUDE.md: subcommand list (12), layout rows, error class
  `templates.TemplateError`, test count — measured.

**E2E:** re-run `tailor` on a real JD with the user's own `.jobhunter/` profile;
both checks return zero findings; PDFs round-trip through xberg.

**Ticket:** AJOB-1

# ai-jobhunter — end-to-end job-hunting pipeline plugin

## Design

### 1. What this is

A **generic, publicly distributable** Claude Code plugin that runs a job hunt as a
pipeline: discover roles → score them against a candidate profile → produce a CV and
cover letter written for one specific job description → draft recruiter outreach.
Application tracking is delegated to a self-hosted [jobsync](https://github.com/Gsync/jobsync)
instance reached over its MCP server.

It replaces `jobhunter-plugin` v0.2.0 (see §9, Divergence). The old plugin was a thin
skill layer driven by a private FastAPI backend; this one carries no backend of its own.

**Non-goals, decided explicitly:**

- No auto-apply. The plugin never submits an application and never clicks a submit
  button. It prepares; the human submits.
- No credential-driven browser automation against LinkedIn/Indeed.
- No bundled candidate data. Nothing about any individual ships inside the plugin.

### 2. Architecture

Five skills, no UI of its own.

| Slash command | Responsibility |
|---|---|
| `/ai-jobhunter:profile` | Compile the candidate profile from every user-named source — web pages (Firecrawl), a LinkedIn PDF export (xberg), and local markdown files. Four passes: ingest, extract claims with provenance, reconcile by precedence, render. Writes `.jobhunter/profile/master-cv.md`, `variants.toml`, `sources/` and `conflicts.md`. Re-runnable. |
| `/ai-jobhunter:discover` | Find roles: Firecrawl `search` + `scrape` across boards, direct ATS APIs (Greenhouse/Lever/Ashby) for target companies, and `firecrawl_monitor_create` on watched career pages. Normalise, dedupe by URL, append to the **local queue**. Does not touch jobsync. |
| `/ai-jobhunter:score` | Score every unscored row in the local queue against the profile, writing `fit_score`, `work_authorization`, `suggested_variant` and per-dimension reasons back into the queue. |
| `/ai-jobhunter:promote` | Push the rows that clear the threshold into jobsync: `add_jobs_batch` then `save_match_results_batch`, inside the request budget. This is the only skill that writes to jobsync. |
| `/ai-jobhunter:tailor` | One job → a CV and cover letter written **for that job description**, plus a keyword-coverage report. Output under `.jobhunter/applications/<slug>/`. |
| `/ai-jobhunter:outreach` | Find a hiring-manager contact (Firecrawl), draft an opener plus two follow-ups, save as a Gmail **draft**. Never sends. |

No `status` skill: jobsync already ships a Kanban UI. Duplicating it would add a second
place to look.

### 3. Data flow

```
site URL + LinkedIn PDF   --profile-->  .jobhunter/profile/
boards + ATS + monitors   --discover--> .jobhunter/queue/jobs.jsonl      (local, uncapped)
queue + profile           --score-->    .jobhunter/queue/jobs.jsonl      (scores written in place)
queue (above threshold)   --promote-->  jobsync via MCP                  (rate-limited, see 4.1)
queue row + profile       --tailor-->   .jobhunter/applications/<slug>/
                                          cv.md · cover-letter.md · keyword-report.md
job + company             --outreach--> Gmail draft
```

The local queue is a **scratch working set**, not a second tracker. Only promoted rows are
tracked, and jobsync remains the single record of what was actually pursued. A row that is
never promoted was never an application.

### 4. Configuration (runtime, never bundled)

`.jobhunter/config.toml` in the user's own project (TOML, not YAML: the Python
standard library ships `tomllib` and no YAML parser, and this plugin takes no dependencies):

```toml
[profile_sources]
# Every entry is a runtime path or URL. Nothing here is bundled with the plugin.
sites        = ["https://example.com/", "https://example-product.com/"]
linkedin_pdf = "./linkedin-profile.pdf"  # user exports this manually
local        = ["/path/to/notes/identity/"]  # markdown the candidate owns
precedence   = ["local-primary", "local", "project", "linkedin-pdf", "site", "product-site"]
primary      = "/path/to/notes/identity/profile-card.md"  # wins inside its own tier

# Current-work evidence. ALLOW-LIST ONLY: a directory listed here is read; anything
# not listed is never opened. There is no "read everything except…" mode.
[profile_sources.projects]
root    = "/path/to/notes/projects/"
allowed = ["project-a", "project-b"]   # exact directory names, no globs

[targets]
geo = ["US-remote", "global-remote"]
min_salary_usd = 0                      # 0 means unset, not "pays zero"
companies = []                          # ATS slugs for direct polling

[budgets]
firecrawl_credits_per_run = 150         # hard cap; the run aborts at the ceiling
jobsync_requests_per_run = 50           # stays under the 60/hour MCP limit

[tracking]
jobsync_mcp = "required"
```

`.jobhunter/profile/variants.toml` holds the role variants. Variants are **user data**,
never hardcoded. The candidate this plugin is first built for uses five:

| Variant | Target titles |
|---|---|
| `ai_product_lead` | AI PM, AI Product Lead, Head of AI Product |
| `genai_agents` | AI Engineer (GenAI), LLM Engineer, Agent Engineer, Forward Deployed Engineer |
| `ai_automation` | Automation engineer, agentic workflow, internal tooling |
| `vibe_coding` | Founding engineer, 0-to-1 builder, rapid prototyping, solo product engineer |
| `ai_video` | Generative video, AI creative technologist |

**Deliberately absent: model-research roles.** This candidate builds *with* models — LLM
apps, agents, automation, generative media — and does not train or research them. A JD
demanding from-scratch training, fine-tuning research, publications or a PhD therefore
scores *lower* on role fit, not higher. Industrial computer-vision deployments (Evident
Scientific, Novanta) remain CV evidence that the candidate ships AI into production; they
are not a role variant, because those postings ask for vision-model depth.

### 4.2 Profile compilation — four passes, with provenance

Sources are not versions of one document. They are different kinds of thing, and merging
them by concatenation produces a CV whose numbers contradict each other. The four passes:

1. **Ingest** — each configured source is fetched and stored verbatim under
   `.jobhunter/profile/sources/<name>.md`, with the URL or path and the fetch date at the
   top. These files are never edited; they are the audit trail.
2. **Extract** — each atomic claim (a role, a date, a metric, an award) is recorded with
   the file and line it came from. A claim the source itself flags as unverified — the
   markers `[verifikasi]` and `[Assumption]` are the ones in use — is carried with
   `verified: false`.
3. **Reconcile** — claims that collide on the same subject are resolved by precedence, and
   anything precedence cannot settle is written to `.jobhunter/profile/conflicts.md`.
   Precedence is by **tier**, and `local-primary` is the single file the user nominates as
   their identity card, which settles same-tier collisions inside their own notes.
4. **Render** — `master-cv.md` in the target market's language, every bullet naming its
   source file. An unresolved conflict blocks that bullet; it never picks one silently.

**Precedence order** (configurable; this is the default, most-owned first):

`sources.precedence = ["vault-identity-card", "vault-other", "linkedin-pdf", "personal-site", "product-site"]`

A source's tier is declared in config, so the order is data, not code. The rationale:
files the candidate owns and maintains outrank marketing copy, which rounds numbers, and a
product site describes a product rather than a person.

**Current-work sources are allow-listed, never filtered.** A candidate's project notes are
the strongest evidence of what they are building now, and also the most likely place to hold
someone else's confidential material: client names, quoted prices, undecided partnerships,
live tenders. The plugin therefore reads **only** the project directories named in
`profile_sources.projects.allowed`, and never scans the root to decide for itself.

A deny-list was considered and rejected on measured grounds: in the reference vault only 9 of
76 identity and project files carry a `sensitivity:` marker at all (7 `public`, 2 `internal`).
"Everything except `internal`" would therefore admit 67 unmarked files, including commercial
terms belonging to third parties. An allow-list costs the user one line of config and cannot
fail open.

**Hard rule: a claim with `verified: false` is never rendered into any outward document** —
not the master CV, not a tailored CV, not a cover letter, not an outreach email. This is the
source's own instruction, honoured rather than overridden.

**Observed conflicts as of 2026-09-19** (these are real, and are why this section exists):

| Subject | Source A | Source B |
|---|---|---|
| Years of experience | `ali.md:27` and `executive-profile.md:26` — "17+" | `experience.md:119` and `positioning.md` — "16+" |
| "16 countries" | `ali.md:27` — products used across 16 countries | `awards.md:42` — a cohort of 48 entrepreneurs **from** 16 countries |

The second is the more dangerous shape: two true statements about different subjects that a
naive merge fuses into one claim whose citation does not support it.

### 4.1 jobsync MCP — verified constraints (2026-09-19, from `wiki/mcp.md`)

Read off a running instance and its shipped documentation, not assumed:

**Nine tools, all of them writes:** `add_job`, `add_jobs_batch` (max 10 jobs), `find_job`
(checks a single URL), `update_job`, `add_question`, `review_resume`,
`save_resume_review`, `save_match_result`, `save_match_results_batch`.

Four constraints that shaped the architecture above:

1. **There is no list or read tool.** An agent cannot ask jobsync what is unscored. This
   is why the working queue lives locally; an earlier draft of this design had `score`
   pulling from jobsync, which is not possible.
2. **60 MCP requests per hour**, across every tool and every token. A batch costs one
   request *per item*, and add-then-save-match costs two per job. Realistic throughput is
   roughly 25–30 promoted jobs per hour, not hundreds.
3. **MCP may only edit jobs MCP created.** Anything entered by hand in the app is
   off-limits to the plugin, permanently.
4. **Match results need the full posting.** Roughly 150+ words gets a full match; shorter
   is stored but flagged *Provisional*; a title-only entry is refused. `discover` must
   therefore capture full description text, not just a link.

Every job also carries the token's name as its source, so plugin-created rows are always
distinguishable from hand-entered ones.

### 5. Scoring rubric — two numbers, not one

Work authorization is a **gate**, not a weighted dimension. Folding it into a single
score hides a strong match behind an unresolved sponsorship question; keeping it separate
lets a high-fit role stay visibly high-fit while flagged.

**`work_authorization`** — one of:

- `open` — the posting states visa sponsorship, or the company hires globally.
- `unclear` — "US remote" with no statement either way. The default when unstated.
- `closed` — US citizens only, security clearance required, or "must be authorized to
  work in the US without sponsorship". Not scored further; surfaced as blocked.

**`fit_score`** — 0–100:

| Dimension | Weight | Notes |
|---|---|---|
| Skill match | 40 | Overlap of JD requirements with profile skills and highlights. |
| Role fit | 25 | Seniority and scope. A junior req against a senior profile scores low. |
| Remote | 15 | remote > hybrid > onsite, unless the location matches a stated target. |
| Salary | 10 | **If the JD states no salary, this dimension is left empty and its weight is redistributed across the others — never scored 0.** An unmeasured number must not be ranked as a low one. |
| Company signal | 10 | Funded startup, known product, or clear engineering brand over anonymous agencies. |

**Variant classification** is a judgement call by the model, made from each variant's
prose description and 2–3 example JDs in `variants.toml`. Keyword lists are a hint fed into
that judgement, never the decider — keyword lists rot within months in this domain.

Every score is written back with a per-dimension breakdown. A bare number nobody can audit
is not useful for deciding where to spend an afternoon.

### 6. Tailoring — one document set per job, always

`tailor` MUST read the target job description and MUST produce documents written for it.
`master-cv.md` is a source of raw material, never a document that gets sent. There is no
code path that submits a pre-built CV unchanged.

Each run writes `.jobhunter/applications/<slug>/`:

- `cv.md` — reordered, reworded, evidence selected for this JD
- `cover-letter.md` — same
- `keyword-report.md` — JD terms covered by the CV, and JD terms still missing

`keyword-report.md` reports **keyword overlap**, and says so. It is not an "ATS score":
ATS vendors parse differently and no local computation can honestly claim to predict one.

### 7. Data integration map

| Component | Source | Exists today? | Notes |
|---|---|---|---|
| Profile (web) | Firecrawl scrape | Verified 2026-09-19: HTTP 200, 1 credit | — |
| Profile (LinkedIn) | `mcp__xberg__extract_file` | Yes | PDF must go through xberg; the native Read tool cannot parse it. |
| Jobs (boards) | Firecrawl `search` + `scrape` | Yes | ~1 credit per page. Capped per run. |
| Jobs (companies) | Greenhouse / Lever / Ashby public APIs | Public, keyless | Cleanest source; no ToS exposure. |
| New postings | `firecrawl_monitor_create` | Yes | Watches career pages instead of re-sweeping. |
| Storage + tracking | jobsync MCP at `/api/mcp`, SQLite | **Not installed yet** | `docker compose up`, then a token from Settings > MCP Access. |
| Scoring | Claude (Sonnet) + rubric | Rubric baseline: `jobhunter-plugin/refs/refs-scoring.md` | Adapted, not copied. |
| CV + cover letter | Claude (Opus), per JD | — | Voice source is the positioning file the user points at. |
| Contacts + email | Firecrawl + Gmail MCP | Gmail MCP unverified | Fallback: write `.eml` files for the user to send. |

### 8. Error handling — fail loudly, never silently

- Firecrawl error or exhausted credits → stop and report remaining budget. Never serve
  stale cache as if it were fresh.
- jobsync MCP unreachable → `promote` refuses to run and prints setup steps. `discover`,
  `score` and `tailor` keep working: they only need the local queue. Nothing is silently
  written to a substitute tracker.
- MCP rate limit reached → `promote` stops at the ceiling, reports how many rows are still
  waiting, and exits cleanly. The queue is the resume point; nothing is lost and nothing is
  retried in a loop against a limit that resets hourly.
- Posting text under ~150 words → promote it anyway but record that the match will be
  flagged *Provisional*; refuse to promote a title-only row and say why.
- Duplicate postings → hash `(company, title, location)` before pushing to jobsync.
  Monitors re-report by design.
- Outreach → drafts only. No send path exists in the code at all.

### 9. Divergence from precedent

Supersedes `jobhunter-plugin` v0.2.0 (`claude-plugin/jobhunter-plugin`), which is retired.

| | jobhunter-plugin v0.2.0 | ai-jobhunter |
|---|---|---|
| Backend | Private FastAPI + callback secret | None; jobsync over MCP |
| Distribution | Personal | Public, generic |
| Profile source | `/api/cv/master.md` | User-named website + LinkedIn export |
| Discovery | Backend scrapers | Firecrawl + ATS APIs |
| Variants | 3, hardcoded | 5, user-supplied in `variants.toml` |
| Work authorization | Not modelled | First-class gate |

The old refs (`refs-scoring.md`, `refs-cv.md`, `refs-email.md`, `refs-contact.md`) are
useful starting material and should be read during planning.

### 10. Open items for the plan stage

1. ~~jobsync MCP tool names are unknown.~~ **Resolved 2026-09-19** — instance running at
   `http://localhost:3737`, tool surface and limits recorded in §4.1. Argument shapes still
   need reading off `__tests__/mcpAddJobSchema.spec.ts` and the live `tools/list` response
   once a token exists.
2. **Firecrawl spend.** A broad board sweep runs to hundreds of pages. The per-run cap is
   required, not optional, and the plan must define behaviour at the ceiling.
3. **Gmail MCP availability** is unverified; the `.eml` fallback must be specified.

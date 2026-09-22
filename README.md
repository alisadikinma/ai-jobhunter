# gaspol-jobhunter

A generic, publicly distributable Claude Code plugin that runs a job hunt as
a pipeline: discover roles, score them against a candidate profile, write a
CV and cover letter for one specific job description, draft recruiter
outreach, and promote the roles worth pursuing into a self-hosted
[jobsync](https://github.com/Gsync/jobsync) tracker over MCP.

**It never auto-applies and it never submits a form.** Every skill in this
plugin prepares a document or a draft; a human decides whether and when to
actually send or submit anything.

Nothing candidate-specific ships with this plugin. Every personal value —
profile sources, target companies, budgets, role variants — arrives at run
time from `.jobhunter/config.toml` in your own project.

## The six commands

| Command | What it does |
|---|---|
| `/gaspol-jobhunter:profile` | Compiles your candidate profile from every source you name (web pages, a LinkedIn PDF export, local notes) into a provenance-tracked `master-cv.md`. Four passes: ingest, extract claims with sources, reconcile by precedence, render. Re-runnable. |
| `/gaspol-jobhunter:discover` | Finds roles from job boards (Firecrawl REST search/scrape), direct ATS APIs (Greenhouse/Lever/Ashby), and LinkedIn (Apify's `bebity/linkedin-jobs-scraper` actor). Appends normalised, deduped rows to a local queue. Never touches jobsync. |
| `/gaspol-jobhunter:score` | Scores every unscored queue row against your profile: a `fit_score` (0-100, five weighted dimensions) plus a separate `work_authorization` gate (`open` / `unclear` / `closed`). |
| `/gaspol-jobhunter:promote` | Pushes the rows worth pursuing into jobsync — the only command that writes to jobsync — within jobsync's hourly MCP request budget. |
| `/gaspol-jobhunter:tailor` | Writes a CV and cover letter (PDF) plus a keyword-overlap report for one specific job description — from the queue, a URL, or a JD you paste. First maps every JD requirement to evidence in your master CV and walks that map with you; nothing is written until you agree every row. Proposes one of three ATS CV templates (`hybrid`, `technical`, `leadership`) and writes the letter to a research-backed format (word band by seniority, four paragraphs); `template-check` must pass both before anything renders. Adds DOCX when the job runs on Workday, Taleo or iCIMS. Never sends your master CV unedited. |
| `/gaspol-jobhunter:outreach` | Finds a hiring-manager contact, drafts an opener plus two follow-ups, and saves them as Gmail drafts (or `.eml` files as a fallback). Drafts only — there is no send path. |

There is no `status` command: jobsync already ships a Kanban board for
tracking what you promoted. This plugin does not duplicate it.

## Data flow

```
site URL + CV/LinkedIn PDF --profile-->  .jobhunter/profile/
boards + ATS + LinkedIn   --discover--> .jobhunter/queue/jobs.jsonl      (local, uncapped)
queue + profile           --score-->    .jobhunter/queue/jobs.jsonl      (scores written in place)
queue (above threshold)   --promote-->  jobsync via MCP                  (rate-limited)
queue row / pasted JD     --tailor-->   .jobhunter/applications/<slug>/  (cv.pdf, cover-letter.pdf, + .docx for enterprise portals)
queue row + profile       --outreach--> Gmail draft or .eml fallback
```

The local queue is a scratch working set, not a second tracker. Only rows
you actually promote are tracked in jobsync — a row that is never promoted
was never an application.

## Prerequisites

1. **A Firecrawl API key** (`FIRECRAWL_API_KEY`), for the board search/scrape
   calls `/gaspol-jobhunter:discover` makes over Firecrawl's REST API v2 —
   plus `/gaspol-jobhunter:tailor`'s JD lookup and
   `/gaspol-jobhunter:outreach`'s contact discovery, both still MCP-based.
2. **An Apify API token** (`APIFY_TOKEN`), if you want `/gaspol-jobhunter:discover`
   to search LinkedIn. It runs the public `bebity/linkedin-jobs-scraper`
   actor against public guest listings only — never your own LinkedIn
   account — and enforces a per-run charge cap before every start. Optional:
   leave it unset and `discover` skips LinkedIn, no other source falls back
   to it.
3. **A self-hosted jobsync instance with an MCP token.** jobsync is not
   bundled with this plugin. Run it yourself (`docker compose up -d` from a
   clone of [jobsync](https://github.com/Gsync/jobsync)), create an account
   at its local URL, and generate a token under Settings → MCP Access.
   Only `/gaspol-jobhunter:promote` needs this; the other five commands work
   without it.

Both `FIRECRAWL_API_KEY` and `APIFY_TOKEN` live in a `.env` file at your
project's root — never in `.jobhunter/config.toml`. Run
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" keys-check` any time to
see which are present, without ever printing a value. Make sure `.env` is
git-ignored in your own project; `discover` warns if it is not.

## Install

1. Install this plugin the same way you install any other Claude Code
   plugin.
2. Copy `templates/config.toml` to `.jobhunter/config.toml` in the project
   you want to run your job hunt from, and fill in your own values — site
   URLs, LinkedIn PDF path, local profile notes, allow-listed project
   directories, target companies, `[linkedin]` search keywords/locations, and
   budgets. `.jobhunter/` is meant to stay local: it is gitignored in this
   repository and should be in yours too.
3. Create a `.env` at your project root with `FIRECRAWL_API_KEY=...` and,
   if you want LinkedIn search, `APIFY_TOKEN=...`. Git-ignore it.
4. Run `/gaspol-jobhunter:profile` first. It compiles your profile and, if
   `.jobhunter/config.toml` is missing entirely, walks you through creating
   it.
5. Run `/gaspol-jobhunter:discover`, then `/gaspol-jobhunter:score`, then whichever
   of `/gaspol-jobhunter:promote`, `/gaspol-jobhunter:tailor`, or
   `/gaspol-jobhunter:outreach` you need next.

## What this plugin will not do

- It will not auto-apply to a job, and no code path in it submits a form.
- It will not send an email on your behalf — outreach only produces drafts.
- It will not read any project directory you have not explicitly
  allow-listed in `profile_sources.projects.allowed`.
- It will not render a claim your own source material flags as unverified
  (`[verifikasi]` / `[Assumption]`) into any document meant to go outward.

The first three are properties of the code: there is no submit path, no mail
path, and `scripts/config.py` refuses any project directory outside the
allow-list. The fourth is an instruction the model follows, checked by the
judgement evals in `docs/evals/profile.md` rather than by a test — a weaker
guarantee than the three above it, and worth knowing which is which.

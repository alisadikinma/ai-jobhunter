---
name: profile
description: Compile the candidate profile from every user-named source (web pages, a LinkedIn PDF export, and local markdown) into a provenance-tracked master CV, through four passes — ingest, extract, reconcile, render. Re-runnable. Invoked as /ai-jobhunter:profile.
---

# /ai-jobhunter:profile

Compiles `.jobhunter/profile/master-cv.md` and `.jobhunter/profile/variants.toml`
from every source the user names in `.jobhunter/config.toml`. This is the only
skill in this plugin that runs without an existing config — its own job is to
read the config's `profile_sources` section and, on a first run, help the user
create it from `${CLAUDE_PLUGIN_ROOT}/templates/config.toml` if it is missing.

Every value used here — site URLs, the LinkedIn PDF path, local notes
directories, the allow-listed project directory names, the identity-card
file — comes from `.jobhunter/config.toml` at run time. Nothing about any
individual is bundled with this plugin.

## Inputs

- `.jobhunter/config.toml` — read with `config-show` (see the commands below). If missing, this
  skill guides the user through creating one from
  `${CLAUDE_PLUGIN_ROOT}/templates/config.toml`
  rather than stopping with the named error the other five skills use.
- `config.resolve_profile_sources(cfg)` — returns the ordered
  `[(tier, path_or_url), ...]` list this skill walks, in precedence order.

## Scripts and MCP tools this skill calls

- `scripts/config.py` — `config.load`, `config.resolve_profile_sources`.
- `mcp__firecrawl__firecrawl_scrape` — fetch each `site` tier entry. The
  native Read tool is not used for these; they are live web pages.
- `mcp__xberg__extract_file` — extract the `linkedin-pdf` tier entry. The
  native Read tool cannot parse PDF; this is the only supported path for it.
- Local markdown (`local-primary`, `local`, `project` tiers) is read with the
  native Read tool, since these are already plain text on disk.

## The four passes (spec §4.2)

Sources are different kinds of thing, not versions of one document. Merging
them by concatenation produces a CV whose numbers contradict each other, so
each pass has one job and writes its own artifact before the next pass runs.

### Pass 1 — Ingest

For every entry `config.resolve_profile_sources(cfg)` returns, in order:

1. Fetch it (`firecrawl_scrape` for a `site` entry, `extract_file` for the
   `linkedin-pdf` entry, a direct read for `local-primary` / `local` /
   `project` entries).
2. Write the fetched content **verbatim** to
   `.jobhunter/profile/sources/<name>.md`, with the source's URL or filesystem
   path and today's fetch date recorded at the top of the file.
3. Never edit a file under `sources/` once written by this pass. These files
   are the audit trail every later claim cites back to; editing one after the
   fact would sever that citation from what was actually fetched.

### Pass 2 — Extract

Read every file under `.jobhunter/profile/sources/` and record each atomic
claim it contains — one role, one date, one metric, one award per claim —
together with the source file and the line number it came from.

A claim whose source text itself flags it as unverified — the markers in use
are `[verifikasi]` and `[Assumption]` — is recorded with `verified: false`.
This flag travels with the claim through reconciliation and rendering; it is
never dropped or upgraded along the way.

### Pass 3 — Reconcile

Claims that collide on the same subject (the same metric, the same date
range, the same title) are resolved by the precedence order
`config.resolve_profile_sources(cfg)` already applied:
`local-primary` > `local` > `project` > `linkedin-pdf` > `site`. Inside the
`local-primary` and `local` tiers, the single file named in
`profile_sources.primary` wins same-tier collisions.

Anything precedence cannot settle — two sources in the **same** tier stating
different values for the same subject, with neither being the primary file —
is written to `.jobhunter/profile/conflicts.md` instead of being picked. A
conflicts file entry names both sources and both values; it is never silently
resolved by picking whichever one was read first.

Watch for the shape where two **true** statements about **different**
subjects happen to share a number (for example, one claim about products used
across a count of countries, and an unrelated claim about a cohort drawn from
that same count of countries). These are not a collision and must not be
fused into one claim — fusing them produces a citation that does not actually
support the fused sentence.

### Pass 4 — Render

Write `.jobhunter/profile/master-cv.md`, with every bullet naming the source
file its claim came from. A subject whose conflict was written to
`conflicts.md` in Pass 3 blocks that bullet from `master-cv.md` — it is never
silently resolved at render time by picking one side.

Also write or update `.jobhunter/profile/variants.toml` if the user's config
implies new role variants worth tracking; each variant is stored as its own
prose description plus 2-3 example job descriptions, since `/ai-jobhunter:score`
later treats this prose as the classification signal, not a keyword list.

## Two hard rules

1. **A claim carrying `verified: false` is never rendered into any outward
   document** — not `master-cv.md`, not a tailored CV, not a cover letter, not
   an outreach email. This is the source's own instruction, honoured rather
   than overridden. An unverified claim may exist in the extracted-claims
   record for the user's own review, but it never reaches a document meant to
   go outward.
2. **Only allow-listed project directories are ever opened.** This skill reads
   `profile_sources.projects.allowed` from the config and opens exactly those
   directory names under `profile_sources.projects.root` — nothing else. It
   never lists `projects.root` to discover what else is there, and a
   directory present on disk but absent from `allowed` is never read. Current
   work notes are the most likely place to hold someone else's confidential
   material (client names, quoted prices, undecided partnerships), so an
   allow-list is the only mode this skill supports; there is no "read
   everything except" mode.

## Output

- `.jobhunter/profile/sources/<name>.md` — one file per configured source,
  verbatim, with fetch date and origin.
- `.jobhunter/profile/master-cv.md` — the rendered profile, every bullet
  sourced.
- `.jobhunter/profile/variants.toml` — role variants as user data.
- `.jobhunter/profile/conflicts.md` — unresolved same-tier collisions, if any.

Before finishing, this skill prints: how many sources it read and from where,
how many claims it extracted, how many conflicts it could not resolve, how
many bullets it rendered, and how many Firecrawl credits it spent.

## How to run the scripts

Every deterministic step in this skill is one command. `${CLAUDE_PLUGIN_ROOT}`
is set by Claude Code to this plugin's installed directory — never hardcode a
path. Reach every script through this command; the module and function names
that appear elsewhere in this file describe what a command wraps, and are not
an instruction to import anything.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" <subcommand> [options]
```

Run it with `--help`, or a subcommand with `--help`, to see the options. Every
subcommand prints JSON on stdout — except `keywords-report --markdown`, which
prints the markdown report itself so it can be redirected to a file. A refusal prints
`{"error": "<class>", "message": "..."}` on stderr and exits non-zero — report
it, do not retry it blindly.

### Commands this skill uses

```bash
# Load the config and see exactly which sources will be read, in precedence order
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" config-show \
  --config .jobhunter/config.toml
```

A `ProjectSourceError` here means the allow-list rejected something — an entry
that resolves to the projects root, a symlink leading outside it, or a missing
`projects.root`. Report it; do not work around it.


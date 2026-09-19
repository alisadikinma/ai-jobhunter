---
name: outreach
description: Find a hiring-manager contact for one job, draft an opener plus two follow-ups, and save them as Gmail drafts (or .eml files when no Gmail MCP tool is available). There is no send path anywhere in this skill. Invoked as /ai-jobhunter:outreach <queue-row-or-url>.
---

# /ai-jobhunter:outreach

Drafts recruiter outreach for one job: an opener plus two follow-ups, saved
for the user to review and send themselves. **There is no send path
anywhere in this skill.** It writes drafts; it never transmits anything.

## Inputs

- `.jobhunter/config.toml`, read with `config-show` (see the commands below). If missing, this
  skill stops with `config.ConfigMissingError` and tells the user to run
  `/ai-jobhunter:profile` first.
- The target job's company and full description — from the matching row in
  `.jobhunter/queue/jobs.jsonl`.
- `.jobhunter/profile/master-cv.md` and `.jobhunter/profile/variants.toml`,
  for the candidate-side detail woven into the drafts.

## Finding a contact

Uses `mcp__firecrawl__firecrawl_search` and `mcp__firecrawl__firecrawl_scrape`
to look for the role's hiring manager on the company's own site and public
professional profiles. Prefers the person who would actually manage the
role over a generic recruiting inbox, since a targeted opener gets read; a
generic `careers@` address is a fallback only, used when no named contact
can be found. Every saved contact records the page it came from, so its
provenance can be re-checked later.

This skill captures professional contact detail only: name, title, and a
company email address or a company contact form. It never records a
personal phone number or a home address, and it never uses a personal email
domain as a target. If a company's own contact page states it does not want
unsolicited outreach, this skill stops for that company and says why,
instead of drafting anything for it.

## Drafting

Three pieces, all written specifically for this job and this contact — never
a generic template with blanks filled in:

1. **Opener** — short, references something specific about the role or
   company (not a generic "I noticed your company..."), states one
   quantified piece of relevant evidence pulled from `master-cv.md`, and
   closes by asking for a short conversation rather than asking to be
   considered for the role outright.
2. **Follow-up 1** — short, sent on the same thread, adds one new data
   point the opener did not include.
3. **Follow-up 2** — short, offers one new concrete idea or resource
   relevant to the company, and closes by leaving the door open rather than
   pressuring for a reply.

Every fact drawn from the profile must already exist in `master-cv.md`; this
skill never invents a metric or a claim to make a draft sound stronger, and
a claim `master-cv.md` carries as `verified: false` is never used here
either.

## Gmail MCP availability check — done at run time, never assumed

Before drafting anything, this skill checks whether a Gmail MCP draft tool
is actually available in the current session (its schema is inspected the
normal way any MCP tool's availability is checked, not guessed from the
plugin's configuration). This check happens fresh every run — a Gmail
connection can appear or disappear between runs, so a cached "it worked last
time" assumption is never used:

- **Gmail MCP tool available** — the opener and both follow-ups are saved
  as Gmail **draft** messages (not sent, not scheduled — saved as drafts
  only), addressed to the discovered contact.
- **Gmail MCP tool not available** — the same three pieces are written as
  `.eml` files under `.jobhunter/applications/<slug>/outreach/` instead, so
  the user can open and send them from any mail client.

Whichever path is taken, this skill's own output states plainly which one it
used, so the user is never left guessing whether a draft actually landed in
Gmail or only on disk.

## Why there is no send path

No tool this skill calls, and no code path in this skill, transmits an
email or a message on the user's behalf. A Gmail draft still requires the
user to open it and press send themselves; an `.eml` file requires the user
to open it in a mail client. This mirrors the plugin-wide rule that nothing
here auto-applies or submits a form — outreach prepares; the human decides
whether and when to actually reach out.

## Output

- Gmail drafts (when available), or
- `.jobhunter/applications/<slug>/outreach/opener.eml`,
  `follow-up-1.eml`, `follow-up-2.eml` (fallback path).

Before finishing, this skill prints: the contact it found and its source
URL, which of the two save paths it used, and how many Firecrawl credits it
spent finding the contact.

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
subcommand prints JSON on stdout. A refusal prints
`{"error": "<class>", "message": "..."}` on stderr and exits non-zero — report
it, do not retry it blindly.

### Commands this skill uses

This skill runs no deterministic script of its own. It reads the compiled
profile and the tailored application under `.jobhunter/applications/<slug>/`,
and uses Firecrawl for contact discovery.

To check the config is loadable before starting:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" config-show \
  --config .jobhunter/config.toml
```


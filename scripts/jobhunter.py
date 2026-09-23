#!/usr/bin/env python3
"""Single command-line entrypoint for every gaspol-jobhunter script.

The skills are prose read by a model, and prose naming a Python function is
not a way to call it. Before this file existed, a skill said "read with
`config.load(path)`" and nothing in the repository said where `config.py`
lived or how to reach it — the only code that knew was the test suite's own
`sys.path.insert`. The first person to install the plugin would have had to
guess an absolute path inside their plugin cache.

So every skill calls exactly one command:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" <subcommand> [options]

One entrypoint rather than five `argparse` blocks, because five would be five
copies of the same wiring and five spellings to keep in step across six
SKILL.md files.

Every subcommand prints JSON on stdout and nothing else, so a caller can read
the result without parsing prose. The single exception is
`keywords-report --markdown`, which prints the markdown report itself.
Logging goes to stderr; a log line on stdout made `json.load` fail on a
real `ats-fetch`. Errors go to stderr with a non-zero exit
status; a `PromoteError`, `ProjectSourceError` or any other named refusal is
reported as `{"error": "<class>", "message": "..."}` rather than a traceback,
because a refusal is an outcome the skill has to report, not a crash.
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import apify  # noqa: E402
import ats  # noqa: E402
import authgate  # noqa: E402
import config  # noqa: E402
import dataindex  # noqa: E402
import docx  # noqa: E402
import envfile  # noqa: E402
import facts  # noqa: E402
import firecrawl  # noqa: E402
import jdstore  # noqa: E402
import jobq  # noqa: E402
import keywords  # noqa: E402
import pdf  # noqa: E402
import promote  # noqa: E402
import templates  # noqa: E402

_NORMALIZERS = {
    "greenhouse": ats.normalize_greenhouse,
    "lever": ats.normalize_lever,
    "ashby": ats.normalize_ashby,
}


def _emit(payload):
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def _read_json_arg(value):
    """Accept either inline JSON or `@path` to read it from a file.

    A whole job description on a command line is awkward and a shell will
    mangle it; `@path` keeps large payloads off the argument list.
    """
    if value.startswith("@"):
        with open(value[1:], "r", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(value)


def cmd_config_show(args):
    cfg = config.load(args.config)
    sources = config.resolve_profile_sources(cfg)
    _emit({"config": cfg, "sources": [{"tier": t, "path": p} for t, p in sources]})


class CompanyRequiredError(ValueError):
    """`--company` is missing where the payload cannot supply it, or passed
    where it would be ignored. Named so the JSON refusal carries a class an
    operator can look up, like every other refusal this CLI emits."""


def _require_company(args):
    """Fail before the network call, not after it.

    Lever and Ashby payloads carry no company name, so the operator must
    supply it. Without this the run fetched the board, then failed with
    "Lever posting missing required key 'company'" — blaming the data for a
    missing flag. Greenhouse carries its own, so passing --company there is
    a mistake worth naming rather than ignoring.
    """
    needs_company = args.board in ("lever", "ashby")
    if needs_company and not (args.company or "").strip():
        raise CompanyRequiredError(
            f"--company is required for {args.board}: its payload carries no "
            "company name. Pass the company's display name."
        )
    if not needs_company and args.company:
        raise CompanyRequiredError(
            f"--company is not accepted for {args.board}: its payload states "
            "the company itself, and the flag would be silently ignored."
        )


def cmd_ats_fetch(args):
    _require_company(args)
    ats.fetch(args.board, args.slug, args.dest)
    rows = _NORMALIZERS[args.board](args.dest, *( [args.company] if args.board != "greenhouse" else [] ))
    _emit(
        {
            "board": args.board,
            "slug": args.slug,
            "dest": args.dest,
            "rows": list(rows),
            # `json.dump` serialises a list subclass as a plain array, so the
            # skipped postings vanished unless they are lifted out by hand.
            # They name the posting and the field that moved — the only way
            # an operator learns a board came back short.
            "skipped": rows.skipped,
        }
    )


def cmd_ats_normalize(args):
    _require_company(args)
    rows = _NORMALIZERS[args.board](args.path, *( [args.company] if args.board != "greenhouse" else [] ))
    _emit({"board": args.board, "rows": list(rows), "skipped": rows.skipped})


def cmd_queue_append(args):
    rows = _read_json_arg(args.rows)
    rows, blocked = authgate.split_closed(rows)
    written, duplicates, malformed = jobq.append_rows(args.queue, rows)
    _emit(
        {
            "written": written,
            "skipped_duplicates": duplicates,
            "malformed": malformed,
            "blocked": _blocked_view(blocked),
        }
    )


def _blocked_view(blocked):
    """Postings the auth gate kept out of the queue, named so the run can report them."""
    return [
        {"company": row.get("company"), "jobTitle": row.get("jobTitle"), "reason": reason}
        for row, reason in blocked
    ]


def cmd_data_index(args):
    """Write Data/INDEX.md: status of every posting folder (tailored / in progress / todo / blocked)."""
    queue_rows = jobq.load(args.queue)
    entries = dataindex.collect(args.root, queue_rows)
    renamed = dataindex.mark_done(entries, args.root) if args.rename else []
    out = args.out or os.path.join(args.root, "INDEX.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(dataindex.render(entries))
    counts = {}
    for e in entries:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    _emit({"path": out, "postings": len(entries), "by_status": counts, "renamed": renamed})


def cmd_auth_check(args):
    """List queue rows whose JD states a hard work-authorization restriction."""
    closed = []
    for row in jobq.load(args.queue):
        status, reason = authgate.classify(row.get("jobDescription") or "")
        if status == "closed":
            closed.append(
                {"row_key": jobq.row_key(row), "company": row.get("company"),
                 "jobTitle": row.get("jobTitle"), "reason": reason}
            )
    _emit({"closed": closed})


def cmd_queue_list(args):
    rows = jobq.load(args.queue)
    if args.unscored:
        rows = list(jobq.iter_unscored(rows))
    if args.unpromoted:
        rows = list(jobq.iter_unpromoted(rows))
    # Carry `row_key` on each listed row. `score` and `promote` both write
    # back with `queue-update --updates {row_key: {...}}`, and their SKILL.md
    # says the key "comes back with it from queue-list" — which was simply
    # false: the emitted rows were the raw JSONL objects and nothing added
    # one, leaving `queue-key --row` the only way to get it, one subprocess
    # per row. This is a view, not a stored field; the queue file is
    # untouched, exactly as `promote-prepare` already reports `row_key`
    # beside each payload.
    listed = [dict(row, row_key=jobq.row_key(row)) for row in rows]
    _emit({"count": len(listed), "rows": listed})


def cmd_queue_update(args):
    updates = _read_json_arg(args.updates)
    updated, unmatched = jobq.update_rows(args.queue, updates)
    _emit({"updated": updated, "unmatched": unmatched})


def cmd_queue_key(args):
    _emit({"row_key": jobq.row_key(_read_json_arg(args.row))})


def cmd_keywords_report(args):
    with open(args.jd, "r", encoding="utf-8") as f:
        jd_text = f.read()
    with open(args.cv, "r", encoding="utf-8") as f:
        cv_text = f.read()
    report = keywords.coverage(jd_text, cv_text, top_n=args.top)
    if args.markdown:
        sys.stdout.write(keywords.render(report) + "\n")
        return
    _emit(report)


def _same_file(source, destination):
    """Whether two paths name the same file, asking the filesystem when it exists.

    A string compare of the absolute paths is not enough on macOS, whose
    default APFS is case-insensitive: `--in cv.md --out CV.MD` compared as
    two different files and the render then overwrote the tailored markdown
    with a ZIP. The source the whole `tailor` pipeline produced was gone,
    with no backup and no warning.

    `samefile` needs the destination to exist, so the string compare stays
    for the ordinary case where it does not.
    """
    if os.path.abspath(source) == os.path.abspath(destination):
        return True
    if not os.path.exists(destination):
        return False
    try:
        return os.path.samefile(source, destination)
    except OSError:
        return False


def cmd_render_docx(args):
    """Render a tailored CV or cover letter to an ATS-readable `.docx`.

    Notes go to BOTH channels on purpose: into the JSON on stdout, which the
    skill parses, and as human lines on stderr, which is the channel a person
    reads. A transformation nobody is told about is one nobody checks.
    """
    if not args.out.lower().endswith(".docx"):
        # A typo in --out overwrites whatever it names. `--out
        # cover-letter.md` destroyed the draft cover letter, silently, and
        # this command only ever produces one kind of file.
        raise docx.DestinationError(
            "refusing to write to %s: --out must end in .docx, and this "
            "command writes nothing else." % args.out
        )

    _check_named_for_posting(args.out)

    if _same_file(args.input_path, args.out):
        raise docx.DestinationError(
            "refusing to write the .docx over its own source markdown (%s). "
            "Give --out a different path." % args.input_path
        )

    with open(args.input_path, "r", encoding="utf-8") as f:
        markdown = f.read()

    result = docx.render(
        markdown,
        args.out,
        allow_unverified=args.allow_unverified,
        source=os.path.basename(args.input_path),
    )
    for note in result["notes"]:
        print("render-docx: %s" % note, file=sys.stderr)
    _emit(
        {
            "out": result["out"],
            "blocks": result["blocks"],
            "notes": result["notes"],
            "bytes": result["bytes"],
        }
    )


def _check_named_for_posting(out_path):
    try:
        jdstore.check_output_name(out_path)
    except jdstore.JdStoreError as exc:
        raise docx.DestinationError(str(exc)) from exc


_ENTERPRISE_PORTALS = ("workday", "taleo", "icims")


def cmd_render_application(args):
    """Render `cv.md` and `cover-letter.md` of one posting folder to company-named files.

    Names come from `.jobmeta.json` (company) and the CV's H1 (person), so a folder
    for Acme yields `Jane-Doe-CV-Acme.pdf` and `Jane-Doe-Cover-Letter-Acme.pdf`.
    An enterprise portal in `requirements-map.md` (workday, taleo, icims) adds `.docx`.
    The generic `cv.pdf`/`cover-letter.pdf` from older runs are removed.
    """
    folder = args.dir
    with open(os.path.join(folder, ".jobmeta.json"), "r", encoding="utf-8") as f:
        company = json.load(f)["company"]
    with open(os.path.join(folder, "cv.md"), "r", encoding="utf-8") as f:
        cv_markdown = f.read()
    person = next((line[2:].strip() for line in cv_markdown.splitlines() if line.startswith("# ")), None)
    if not person:
        raise docx.DestinationError("cv.md has no '# Name' heading to build the file name from")
    portal = "other"
    map_path = os.path.join(folder, "requirements-map.md")
    if os.path.isfile(map_path):
        with open(map_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("portal:"):
                    portal = line.split(":", 1)[1].strip().lower()
                    break
    written = []
    for kind, source in (("cv", "cv.md"), ("cover-letter", "cover-letter.md")):
        with open(os.path.join(folder, source), "r", encoding="utf-8") as f:
            markdown = f.read()
        out = os.path.join(folder, jdstore.application_filename(person, kind, company, "pdf"))
        pdf.render(markdown, out, allow_unverified=False, source=source, page=args.page)
        written.append(out)
        if portal in _ENTERPRISE_PORTALS:
            out = os.path.join(folder, jdstore.application_filename(person, kind, company, "docx"))
            docx.render(markdown, out, allow_unverified=False, source=source)
            written.append(out)
    for legacy in ("cv.pdf", "cover-letter.pdf", "cv.docx", "cover-letter.docx"):
        path = os.path.join(folder, legacy)
        if os.path.isfile(path):
            os.remove(path)
    _emit({"portal": portal, "written": written})


def cmd_render_pdf(args):
    """Render a tailored CV or cover letter to a hand-written PDF 1.4.

    Mirrors `cmd_render_docx` exactly, refusal for refusal: same suffix
    check, same same-file check, same two-channel notes. Only the renderer
    (`pdf.render` instead of `docx.render`) and the file extension differ —
    `pdf.render` itself shares the unverified-claim gate with `docx.render`
    through `docx.prepare`, so a candidate's CV is refused identically by
    both output formats.
    """
    if not args.out.lower().endswith(".pdf"):
        # Same reasoning as render-docx: a typo in --out overwrites whatever
        # it names, and this command only ever produces one kind of file.
        raise docx.DestinationError(
            "refusing to write to %s: --out must end in .pdf, and this "
            "command writes nothing else." % args.out
        )

    _check_named_for_posting(args.out)

    if _same_file(args.input_path, args.out):
        raise docx.DestinationError(
            "refusing to write the .pdf over its own source markdown (%s). "
            "Give --out a different path." % args.input_path
        )

    with open(args.input_path, "r", encoding="utf-8") as f:
        markdown = f.read()

    result = pdf.render(
        markdown,
        args.out,
        allow_unverified=args.allow_unverified,
        source=os.path.basename(args.input_path),
        page=args.page,
    )
    for note in result["notes"]:
        print("render-pdf: %s" % note, file=sys.stderr)
    _emit(
        {
            "out": result["out"],
            "pages": result["pages"],
            "blocks": result["blocks"],
            "notes": result["notes"],
            "bytes": result["bytes"],
        }
    )


def _facts_findings(args, markdown):
    """Findings from the user's verified facts file, when `--facts` is given."""
    if not args.facts:
        return []
    return facts.check(markdown, facts.load(args.facts))


def cmd_template_check(args):
    """Check a tailored CV or cover letter against its chosen template.

    Read-only, like every other check in this CLI: the input file is only
    ever opened for reading, `templates.check_cv` / `check_letter` touch no
    other file, and nothing here executes a path. `--template`/`--level`
    are validated against the real files under `templates/` (through
    `check_cv`/`check_letter`, which load them), never a hard-coded
    argparse `choices=` list, so a fourth CV template dropped into
    `templates/cv/` is usable here with no code change.
    """
    have_cv = bool(args.cv)
    have_letter = bool(args.letter)
    if have_cv and have_letter:
        raise templates.TemplateError(
            "pass exactly one of --cv or --letter, not both"
        )
    if not have_cv and not have_letter:
        raise templates.TemplateError("pass one of --cv or --letter")

    # A flag from the other mode is refused, not ignored: ignoring it let a
    # caller believe `--company` was checked on a CV (gaspol-review, AJOB-4).
    if have_cv:
        for flag, value in (("--level", args.level), ("--company", args.company), ("--role", args.role)):
            if value:
                raise templates.TemplateError("%s applies to --letter, not --cv" % flag)
    elif args.template:
        raise templates.TemplateError("--template applies to --cv, not --letter")

    if have_cv:
        if not args.template:
            raise templates.TemplateError("--cv requires --template")
        if not os.path.isfile(args.cv):
            raise templates.TemplateError("no such file: %s" % args.cv)
        with open(args.cv, "r", encoding="utf-8") as f:
            markdown = f.read()
        findings = templates.check_cv(markdown, args.template)
        findings += _facts_findings(args, markdown)
        _emit(
            {
                "kind": "cv",
                "template": args.template,
                "findings": findings,
                "ok": len(findings) == 0,
            }
        )
        return

    if not args.level:
        raise templates.TemplateError("--letter requires --level")
    if not os.path.isfile(args.letter):
        raise templates.TemplateError("no such file: %s" % args.letter)
    with open(args.letter, "r", encoding="utf-8") as f:
        markdown = f.read()
    findings = templates.check_letter(
        markdown, args.level, company=args.company, role=args.role
    )
    findings += _facts_findings(args, markdown)
    _emit(
        {
            "kind": "letter",
            "level": args.level,
            "findings": findings,
            "ok": len(findings) == 0,
        }
    )


def cmd_linkedin_fetch(args):
    """Fetch new LinkedIn postings through the Apify bebity actor.

    Order matters: config, then keywords/locations, then the token, then
    the credit brake — each check is cheap and must run before the ones
    that spend money. `write_state` is the very last step, so a failed
    fetch leaves the re-fetch window untouched rather than silently
    narrowing it.
    """
    cfg = config.load(args.config)
    max_items = cfg["budgets"]["apify_max_items_per_run"]
    if max_items == 0:
        _emit({"skipped_source": "linkedin", "reason": "apify_max_items_per_run is 0"})
        return

    linkedin_cfg = cfg["linkedin"]
    if not linkedin_cfg["keywords"] or not linkedin_cfg["locations"]:
        raise config.ConfigError(
            f"linkedin-fetch needs [linkedin] keywords and locations in {args.config}"
        )

    token = envfile.read_key("APIFY_TOKEN", args.env_file)
    if not token:
        raise apify.ApifyTokenMissingError(
            f"APIFY_TOKEN is not set in the environment or in {args.env_file}"
        )

    cap = apify.charge_cap_usd(max_items)
    remaining = apify.remaining_credit_usd(token)
    if remaining < cap:
        raise apify.ApifyCreditError(
            f"remaining Apify credit ${remaining:.2f} is below this run's cap ${cap:.2f}"
        )

    state = os.path.join(os.path.dirname(os.path.abspath(args.queue)), "linkedin-state.json")
    now = datetime.datetime.now(datetime.timezone.utc)
    window = apify.choose_window(state, now)

    actor_input = apify.build_actor_input(linkedin_cfg, max_items, window)
    result = apify.fetch_linkedin(actor_input, max_items, token, args.dest)
    rows = apify.normalize_linkedin(args.dest)
    kept, blocked = authgate.split_closed(list(rows))
    written, duplicate, _malformed = jobq.append_rows(args.queue, kept)
    apify.write_state(state, now)

    _emit(
        {
            "window": window,
            "requested": max_items,
            "returned": result["returned"],
            "new": written,
            "duplicate": duplicate,
            "skipped": rows.skipped,
            "blocked": _blocked_view(blocked),
            "usd_charged": result["usd_charged"],
            "credit_remaining_usd": remaining - result["usd_charged"],
        }
    )


def _open_firecrawl_budget(args):
    """Shared setup for `firecrawl-search`/`firecrawl-scrape`: key, account
    credit, and this run's own ceiling — every check cheap and ordered
    before the call that spends money."""
    cfg = config.load(args.config)
    key = envfile.read_key("FIRECRAWL_API_KEY", args.env_file)
    if not key:
        raise firecrawl.FirecrawlKeyMissingError(
            f"FIRECRAWL_API_KEY is not set in the environment or in {args.env_file}"
        )
    remaining = firecrawl.remaining_credits(key)
    budget = firecrawl.Budget.open(
        args.run_state, cfg["budgets"]["firecrawl_credits_per_run"], remaining
    )
    return key, remaining, budget


def cmd_firecrawl_search(args):
    key, remaining, budget = _open_firecrawl_budget(args)
    budget.check("search", args.limit, remaining)
    results, credits_used = firecrawl.search(
        key, args.query, args.limit, args.dest, tbs=args.tbs, location=args.location
    )
    budget.record(credits_used)
    _emit(
        {
            "dest": args.dest,
            "results": results,
            "credits_spent_run": budget.spent(remaining),
            "credits_budget": budget.ceiling,
            "credits_remaining_account": remaining - (credits_used or 0),
        }
    )


def cmd_firecrawl_scrape(args):
    key, remaining, budget = _open_firecrawl_budget(args)
    budget.check("scrape", None, remaining)
    credits_used = firecrawl.scrape(key, args.url, args.dest)
    budget.record(credits_used)
    _emit(
        {
            "dest": args.dest,
            "url": args.url,
            "credits_spent_run": budget.spent(remaining),
            "credits_budget": budget.ceiling,
            "credits_remaining_account": remaining - (credits_used or 0),
        }
    )


def cmd_keys_check(args):
    _emit(envfile.key_status(["APIFY_TOKEN", "FIRECRAWL_API_KEY"], args.env_file))


def cmd_jd_write(args):
    rows = _read_json_arg(args.rows)
    # `queue-list` prints {"count", "rows"}; take its rows directly so LinkedIn
    # postings (which `linkedin-fetch` queues without printing) can reach jd-write.
    if isinstance(rows, dict) and "rows" in rows:
        rows = rows["rows"]
    _emit(jdstore.write_jd_files(args.root, rows))


def cmd_jd_similar(args):
    with open(args.jd, "r", encoding="utf-8") as f:
        jd_text = f.read()
    matches = jdstore.find_similar(
        args.root, jd_text, threshold=args.threshold, exclude=os.path.dirname(args.jd)
    )
    _emit({"matches": matches})


def cmd_promote_prepare(args):
    rows = _read_json_arg(args.rows)

    # Validate FIRST, budget second. Budgeting over the raw rows counted
    # refusals against the ceiling: 25 bad rows ahead of 50 good ones
    # reported 60 requests for 5 prepared payloads and held back 45 healthy
    # rows for a budget nothing was going to spend.
    prepared = []
    refused = []
    for row in rows:
        try:
            prepared.append(
                {
                    "add_job": promote.to_add_job(row),
                    "match_text": promote.to_match_text(row),
                    "quality": promote.match_quality(row),
                    "row_key": jobq.row_key(row),
                }
            )
        except promote.PromoteError as exc:
            refused.append(
                {
                    "row_key": jobq.row_key(row),
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
            )

    sending, waiting, requests_needed = promote.plan_budget(prepared, args.limit)
    to_send = prepared[:sending]

    _emit(
        {
            "batches": [list(batch) for batch in promote.chunk(to_send, args.batch_size)],
            "prepared": len(to_send),
            "refused": refused,
            "waiting": waiting,
            "requests_needed": requests_needed,
        }
    )


class _JsonArgumentParser(argparse.ArgumentParser):
    """Emit argparse's own failures as the JSON refusal the skills expect.

    `parse_args` raises `SystemExit` from OUTSIDE `main()`'s try block, so an
    unknown subcommand or a missing required flag printed usage prose and
    exited 2 — not `{"error": ..., "message": ...}`. Every SKILL.md tells the
    model a refusal arrives as JSON on stderr, and a mistyped subcommand is
    one of the likelier mistakes a model makes.
    """

    def error(self, message):
        json.dump(
            {"error": "UsageError", "message": message},
            sys.stderr,
            indent=2,
            ensure_ascii=False,
        )
        sys.stderr.write("\n")
        raise SystemExit(1)


def build_parser():
    parser = _JsonArgumentParser(
        prog="jobhunter",
        description="Deterministic helpers behind the gaspol-jobhunter skills.",
    )
    sub = parser.add_subparsers(
        dest="command", required=True, parser_class=_JsonArgumentParser
    )

    p = sub.add_parser("config-show", help="Load config.toml and resolve profile sources")
    p.add_argument("--config", required=True, help="path to .jobhunter/config.toml")
    p.set_defaults(func=cmd_config_show)

    p = sub.add_parser("ats-fetch", help="Fetch a board to a file and normalise it")
    p.add_argument("--board", required=True, choices=sorted(_NORMALIZERS))
    p.add_argument("--slug", required=True)
    p.add_argument("--dest", required=True, help="file to stream the raw payload into")
    p.add_argument("--company", help="required for lever and ashby; their payloads carry no company")
    p.set_defaults(func=cmd_ats_fetch)

    p = sub.add_parser("ats-normalize", help="Normalise an already-downloaded board file")
    p.add_argument("--board", required=True, choices=sorted(_NORMALIZERS))
    p.add_argument("--path", required=True)
    p.add_argument("--company")
    p.set_defaults(func=cmd_ats_normalize)

    p = sub.add_parser("queue-append", help="Append rows to the local queue, deduped")
    p.add_argument("--queue", required=True)
    p.add_argument("--rows", required=True, help="JSON array, or @path to a JSON file")
    p.set_defaults(func=cmd_queue_append)

    p = sub.add_parser("queue-list", help="Read the local queue")
    p.add_argument("--queue", required=True)
    p.add_argument("--unscored", action="store_true", help="only rows with no fit_score")
    p.add_argument(
        "--unpromoted",
        action="store_true",
        help="only rows not yet marked promoted — use this before promote-prepare "
        "so the budget is not spent re-upserting rows already in jobsync",
    )
    p.set_defaults(func=cmd_queue_list)

    p = sub.add_parser("queue-update", help="Merge fields into matching queue rows")
    p.add_argument("--queue", required=True)
    p.add_argument("--updates", required=True, help='JSON {row_key: {field: value}}, or @path')
    p.set_defaults(func=cmd_queue_update)

    p = sub.add_parser("queue-key", help="Print the identity key for one row")
    p.add_argument("--row", required=True, help="JSON object, or @path")
    p.set_defaults(func=cmd_queue_key)

    p = sub.add_parser("keywords-report", help="JD-vs-CV keyword overlap")
    p.add_argument("--jd", required=True, help="file holding the job description text")
    p.add_argument("--cv", required=True, help="file holding the CV text")
    p.add_argument("--top", type=int, default=keywords.DEFAULT_TOP_N)
    p.add_argument("--markdown", action="store_true", help="emit keyword-report.md instead of JSON")
    p.set_defaults(func=cmd_keywords_report)

    p = sub.add_parser(
        "linkedin-fetch", help="Fetch new LinkedIn postings through Apify's bebity actor"
    )
    p.add_argument("--config", required=True, help="path to .jobhunter/config.toml")
    p.add_argument("--queue", required=True, help="path to the local job queue JSONL file")
    p.add_argument("--dest", required=True, help="file to stream the raw Apify dataset into")
    p.add_argument("--env-file", default=".env", help="path to the .env file holding APIFY_TOKEN")
    p.set_defaults(func=cmd_linkedin_fetch)

    p = sub.add_parser("firecrawl-search", help="Board search through Firecrawl REST v2")
    p.add_argument("--config", required=True, help="path to .jobhunter/config.toml")
    p.add_argument("--run-state", required=True, help="path to this run's Firecrawl budget file")
    p.add_argument("--query", required=True)
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--dest", required=True, help="file to write the search results into")
    p.add_argument("--env-file", default=".env", help="path to the .env file holding FIRECRAWL_API_KEY")
    p.add_argument("--tbs")
    p.add_argument("--location")
    p.set_defaults(func=cmd_firecrawl_search)

    p = sub.add_parser("firecrawl-scrape", help="Scrape one page through Firecrawl REST v2")
    p.add_argument("--config", required=True, help="path to .jobhunter/config.toml")
    p.add_argument("--run-state", required=True, help="path to this run's Firecrawl budget file")
    p.add_argument("--url", required=True)
    p.add_argument("--dest", required=True, help="file to write the scraped page into")
    p.add_argument("--env-file", default=".env", help="path to the .env file holding FIRECRAWL_API_KEY")
    p.set_defaults(func=cmd_firecrawl_scrape)

    p = sub.add_parser("keys-check", help="Report which provider keys are present, never their values")
    p.add_argument("--env-file", default=".env", help="path to the .env file to check")
    p.set_defaults(func=cmd_keys_check)

    p = sub.add_parser("promote-prepare", help="Build jobsync payloads within a request budget")
    p.add_argument("--rows", required=True, help="JSON array of scored rows, or @path")
    p.add_argument("--limit", type=int, default=promote.MAX_REQUESTS_PER_HOUR)
    p.add_argument("--batch-size", type=int, default=promote.MAX_BATCH_SIZE)
    p.set_defaults(func=cmd_promote_prepare)

    p = sub.add_parser(
        "render-docx", help="Render tailored markdown to an ATS-readable .docx"
    )
    p.add_argument(
        "--in",
        dest="input_path",
        required=True,
        help="path to the tailored markdown, e.g. Data/<Source>/<Company>/<Role>/cv.md",
    )
    p.add_argument("--out", required=True, help="path to write the .docx to")
    p.add_argument(
        "--allow-unverified",
        action="store_true",
        help=(
            "render even though the markdown still carries [verifikasi] or "
            "[Assumption]. This is an opt-in escape from a safety gate, decided "
            "per run by the person whose name is on the CV — never a config "
            "default and never the skill's choice."
        ),
    )
    p.set_defaults(func=cmd_render_docx)

    p = sub.add_parser(
        "render-pdf", help="Render tailored markdown to a hand-written PDF 1.4"
    )
    p.add_argument(
        "--in",
        dest="input_path",
        required=True,
        help="path to the tailored markdown, e.g. Data/<Source>/<Company>/<Role>/cv.md",
    )
    p.add_argument("--out", required=True, help="path to write the .pdf to")
    p.add_argument(
        "--page",
        choices=["letter", "a4"],
        default="letter",
        help="page size",
    )
    p.add_argument(
        "--allow-unverified",
        action="store_true",
        help=(
            "render even though the markdown still carries [verifikasi] or "
            "[Assumption]. This is an opt-in escape from a safety gate, decided "
            "per run by the person whose name is on the CV — never a config "
            "default and never the skill's choice."
        ),
    )
    p.set_defaults(func=cmd_render_pdf)

    p = sub.add_parser(
        "template-check",
        help="Check a tailored CV or cover letter against its template/format",
    )
    p.add_argument("--cv", help="path to a tailored CV markdown file")
    p.add_argument(
        "--template", help="CV template name from templates/cv/, required with --cv"
    )
    p.add_argument("--letter", help="path to a tailored cover-letter markdown file")
    p.add_argument(
        "--level",
        help="cover-letter level (entry/mid/executive), required with --letter",
    )
    p.add_argument(
        "--company",
        help="checked against the letter's opening paragraph; --letter only",
    )
    p.add_argument(
        "--role",
        help="checked against the letter's opening paragraph; --letter only",
    )
    p.add_argument(
        "--facts",
        help="user-verified facts TOML (contact line, forbidden text), checked on --cv and --letter",
    )
    p.set_defaults(func=cmd_template_check)

    p = sub.add_parser(
        "render-application",
        help="Render a posting folder's CV and cover letter to files named with the company",
    )
    p.add_argument("--dir", required=True, help="Data/<Source>/<Company>/<Role> folder")
    p.add_argument("--page", choices=("letter", "a4"), default="letter")
    p.set_defaults(func=cmd_render_application)

    p = sub.add_parser("data-index", help="Write Data/INDEX.md showing which postings have a tailored CV")
    p.add_argument("--root", required=True, help="Data directory root, e.g. Data")
    p.add_argument("--queue", required=True)
    p.add_argument("--out", help="default: <root>/INDEX.md")
    p.add_argument("--rename", action="store_true", help="also rename tailored folders to '<Role> - DONE'")
    p.set_defaults(func=cmd_data_index)

    p = sub.add_parser(
        "auth-check",
        help="List queue rows whose JD closes them to the candidate (local only, no sponsorship, clearance)",
    )
    p.add_argument("--queue", required=True)
    p.set_defaults(func=cmd_auth_check)

    p = sub.add_parser(
        "jd-write",
        help="Materialize Data/<source>/<company>/<role>/JD.md for queue rows",
    )
    p.add_argument("--root", required=True, help="Data directory root, e.g. Data")
    p.add_argument(
        "--rows", required=True, help="JSON array of queue rows (camelCase), or a `queue-list` document, or @path"
    )
    p.set_defaults(func=cmd_jd_write)

    p = sub.add_parser(
        "jd-similar",
        help="Find previously-tailored JDs similar to a new one",
    )
    p.add_argument("--root", required=True, help="Data directory root, e.g. Data")
    p.add_argument("--jd", required=True, help="path to the new JD's text file")
    p.add_argument(
        "--threshold",
        type=float,
        default=0.90,
        help="difflib ratio cutoff, default 0.90",
    )
    p.set_defaults(func=cmd_jd_similar)

    return parser


def main(argv=None):
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        # `--help` exits 0 having already written its text; a usage error
        # exits 1 having already written its JSON. Either way the message
        # is out, so just carry the code.
        return exc.code if isinstance(exc.code, int) else 1
    try:
        args.func(args)
    except Exception as exc:  # noqa: BLE001 — the contract is JSON, never a traceback
        # Every SKILL.md tells the model a refusal arrives as
        # {"error": ..., "message": ...} on stderr. Catching only the three
        # named base classes broke that promise on the most ordinary
        # mistakes: malformed JSON in --rows, a missing @file, a bad --jd
        # path. A traceback is not a result the skill can report.
        json.dump(
            {"error": type(exc).__name__, "message": str(exc)},
            sys.stderr,
            indent=2,
            ensure_ascii=False,
        )
        sys.stderr.write("\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

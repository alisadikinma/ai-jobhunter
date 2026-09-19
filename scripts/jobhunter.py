#!/usr/bin/env python3
"""Single command-line entrypoint for every ai-jobhunter script.

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
the result without parsing prose. Errors go to stderr with a non-zero exit
status; a `PromoteError`, `ProjectSourceError` or any other named refusal is
reported as `{"error": "<class>", "message": "..."}` rather than a traceback,
because a refusal is an outcome the skill has to report, not a crash.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ats  # noqa: E402
import config  # noqa: E402
import jobq  # noqa: E402
import keywords  # noqa: E402
import promote  # noqa: E402

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


def cmd_ats_fetch(args):
    ats.fetch(args.board, args.slug, args.dest)
    rows = _NORMALIZERS[args.board](args.dest, *( [args.company] if args.board != "greenhouse" else [] ))
    _emit({"board": args.board, "slug": args.slug, "dest": args.dest, "rows": rows})


def cmd_ats_normalize(args):
    rows = _NORMALIZERS[args.board](args.path, *( [args.company] if args.board != "greenhouse" else [] ))
    _emit({"board": args.board, "rows": rows})


def cmd_queue_append(args):
    rows = _read_json_arg(args.rows)
    written, duplicates, malformed = jobq.append_rows(args.queue, rows)
    _emit({"written": written, "skipped_duplicates": duplicates, "malformed": malformed})


def cmd_queue_list(args):
    rows = jobq.load(args.queue)
    if args.unscored:
        rows = list(jobq.iter_unscored(rows))
    _emit({"count": len(rows), "rows": rows})


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


def cmd_promote_prepare(args):
    rows = _read_json_arg(args.rows)
    limit = args.limit
    sending, waiting, requests_needed = promote.plan_budget(rows, limit)

    prepared = []
    refused = []
    for row in rows[:sending]:
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

    _emit(
        {
            "batches": [list(batch) for batch in promote.chunk(prepared, args.batch_size)],
            "prepared": len(prepared),
            "refused": refused,
            "waiting": waiting,
            "requests_needed": requests_needed,
        }
    )


def build_parser():
    parser = argparse.ArgumentParser(
        prog="jobhunter",
        description="Deterministic helpers behind the ai-jobhunter skills.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

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

    p = sub.add_parser("promote-prepare", help="Build jobsync payloads within a request budget")
    p.add_argument("--rows", required=True, help="JSON array of scored rows, or @path")
    p.add_argument("--limit", type=int, default=promote.MAX_REQUESTS_PER_HOUR)
    p.add_argument("--batch-size", type=int, default=promote.MAX_BATCH_SIZE)
    p.set_defaults(func=cmd_promote_prepare)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (config.ConfigError, promote.PromoteError, ats.AtsError) as exc:
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

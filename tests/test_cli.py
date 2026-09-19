"""Behavioural tests for `scripts/jobhunter.py`, the single CLI entrypoint.

Round 3 of review found this file — the one every SKILL.md invokes, and the
newest in the repository — had no behavioural test at all. The only thing
touching it ran `--help` as a subprocess to harvest subcommand names. So the
CLI's own contract went unchecked: the JSON-on-stdout promise every skill
states, the validate-then-budget ordering, `--company`, `--unpromoted`.

These call `main(argv)` in-process and read what it wrote, because the
contract the skills depend on is the bytes on stdout, not a return value.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import jobhunter  # noqa: E402


def run(argv):
    """Run the CLI and return `(exit_code, parsed_stdout, stderr_text)`.

    `parsed_stdout` is `None` when stdout did not hold one JSON document —
    which is itself the assertion for the contract every SKILL.md states.
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = jobhunter.main(argv)
    text = out.getvalue()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    return code, parsed, err.getvalue(), text


class TestStdoutIsAlwaysParseableJson(unittest.TestCase):
    """"Every subcommand prints JSON on stdout" — all six SKILL.md say so.

    `ats.fetch` used four bare `print()` calls, which go to stdout. Measured:
    `json.load` on a real `ats-fetch` run raised
    `json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)`
    because the log line came first. A model piping the result could not read
    it, and the suite's own output was littered with `ats.fetch: board=...`.
    """

    def test_ats_normalize_emits_one_json_document_and_nothing_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "board.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"jobs": [_greenhouse_job(), "a stray string"]}, f)
            code, parsed, _err, text = run(
                ["ats-normalize", "--board", "greenhouse", "--path", path]
            )
        self.assertEqual(code, 0)
        self.assertIsNotNone(parsed, f"stdout was not parseable JSON: {text!r}")

    def test_the_skipped_posting_is_reported_not_swallowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "board.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"jobs": [_greenhouse_job(), "a stray string"]}, f)
            _code, parsed, _err, _text = run(
                ["ats-normalize", "--board", "greenhouse", "--path", path]
            )
        self.assertEqual(len(parsed["rows"]), 1)
        self.assertEqual(len(parsed["skipped"]), 1)


class TestOneBadPostingNeverDiscardsTheBoard(unittest.TestCase):
    """The non-dict guard existed on Ashby only.

    Greenhouse and Lever reached `job.get(...)` on a string and raised
    `AttributeError`, which `_normalize_all` does not catch. Measured on a
    two-entry payload:

        --- greenhouse ---  {"error": "AttributeError",
                             "message": "'str' object has no attribute 'get'"}
        --- lever ---       {"error": "AttributeError",
                             "message": "'int' object has no attribute 'get'"}
        --- ashby ---       {"board": "ashby", ...}   <- survived

    On a 667-posting Stripe board that is total loss of the fetch, shown to
    the operator as a refusal-shaped error they are told not to retry.
    """

    def test_greenhouse_survives_a_non_dict_entry(self):
        self._assert_survives(
            "greenhouse", {"jobs": [_greenhouse_job(), "a stray string"]}, []
        )

    def test_lever_survives_a_non_dict_entry(self):
        self._assert_survives("lever", [_lever_job(), 42], ["--company", "Acme"])

    def test_ashby_survives_a_non_dict_entry(self):
        self._assert_survives(
            "ashby", {"jobs": [_ashby_job(), 42]}, ["--company", "Acme"]
        )

    def _assert_survives(self, board, payload, extra):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "board.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            code, parsed, err, _text = run(
                ["ats-normalize", "--board", board, "--path", path] + extra
            )
        self.assertEqual(code, 0, f"{board} refused the whole board: {err}")
        self.assertEqual(len(parsed["rows"]), 1)
        self.assertEqual(len(parsed["skipped"]), 1)
        self.assertIn("job object", parsed["skipped"][0]["error"])


class TestRefusalsAreJsonOnStderr(unittest.TestCase):
    def test_malformed_rows_json_is_a_named_refusal_not_a_traceback(self):
        code, _parsed, err, _text = run(
            ["queue-append", "--queue", "/tmp/nope.jsonl", "--rows", "{not json"]
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "JSONDecodeError")

    def test_missing_company_refuses_before_any_work(self):
        code, _parsed, err, _text = run(
            ["ats-normalize", "--board", "lever", "--path", "/nonexistent"]
        )
        self.assertEqual(code, 1)
        payload = json.loads(err)
        self.assertEqual(payload["error"], "CompanyRequiredError")
        self.assertIn("--company is required", payload["message"])

    def test_company_passed_to_greenhouse_is_refused_rather_than_ignored(self):
        code, _parsed, err, _text = run(
            [
                "ats-normalize", "--board", "greenhouse",
                "--path", "/nonexistent", "--company", "Acme",
            ]
        )
        self.assertEqual(code, 1)
        self.assertIn("is not accepted", json.loads(err)["message"])


class TestConfigShow(unittest.TestCase):
    """The first command all six SKILL.md run, and until now the only
    subcommand with no test — while Phase E.5 step 1 named it as THE test to
    write first."""

    def _config(self, tmp, body):
        path = os.path.join(tmp, "config.toml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        return path

    def test_resolves_sources_in_the_configured_tier_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "identity"))
            primary = os.path.join(tmp, "identity", "profile-card.md")
            open(primary, "w", encoding="utf-8").close()
            os.makedirs(os.path.join(tmp, "projects", "project-a"))
            cfg = self._config(tmp, f"""
[profile_sources]
sites      = ["https://example.com/"]
local      = ["{tmp}/identity/"]
primary    = "{primary}"
precedence = ["local-primary", "local", "project", "site"]

[profile_sources.projects]
root    = "{tmp}/projects/"
allowed = ["project-a"]
""")
            code, parsed, _err, text = run(["config-show", "--config", cfg])
        self.assertEqual(code, 0)
        self.assertIsNotNone(parsed, f"stdout was not parseable JSON: {text!r}")
        self.assertEqual(
            [s["tier"] for s in parsed["sources"]],
            ["local-primary", "local", "project", "site"],
        )

    def test_an_unlisted_project_directory_never_appears(self):
        """The allow-list is a privacy control; this is its CLI-level proof."""
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "projects", "project-a"))
            os.makedirs(os.path.join(tmp, "projects", "client-work"))
            cfg = self._config(tmp, f"""
[profile_sources]
precedence = ["project"]

[profile_sources.projects]
root    = "{tmp}/projects/"
allowed = ["project-a"]
""")
            _code, parsed, _err, _text = run(["config-show", "--config", cfg])
        paths = [s["path"] for s in parsed["sources"]]
        self.assertEqual(len(paths), 1)
        self.assertNotIn("client-work", paths[0])

    def test_an_unknown_precedence_tier_is_a_named_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._config(tmp, '[profile_sources]\nprecedence = ["typo-tier"]\n')
            code, _parsed, err, _text = run(["config-show", "--config", cfg])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "PrecedenceError")


class TestArgparseFailuresAreJsonToo(unittest.TestCase):
    """`parse_args` raises SystemExit outside main()'s try, so a mistyped
    subcommand printed usage prose and exited 2 — breaking the JSON contract
    on one of the likelier mistakes a model makes."""

    def test_unknown_subcommand_is_a_json_refusal(self):
        code, _parsed, err, _text = run(["totally-fake-subcommand"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "UsageError")

    def test_missing_required_flag_is_a_json_refusal(self):
        code, _parsed, err, _text = run(["queue-list"])
        self.assertEqual(code, 1)
        self.assertIn("--queue", json.loads(err)["message"])


class TestQueueListUnpromoted(unittest.TestCase):
    """`iter_unpromoted` had zero callers; `--unpromoted` is the caller."""

    def test_rows_already_promoted_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = os.path.join(tmp, "queue.jsonl")
            rows = [
                {"company": "A", "title": "Eng", "url": "https://x/a", "promoted": True},
                {"company": "B", "title": "Eng", "url": "https://x/b"},
            ]
            with open(queue, "w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row) + "\n")
            _code, parsed, _err, _text = run(
                ["queue-list", "--queue", queue, "--unpromoted"]
            )
        self.assertEqual(parsed["count"], 1)
        self.assertEqual(parsed["rows"][0]["company"], "B")


class TestPromotePrepareValidatesBeforeBudgeting(unittest.TestCase):
    """Budgeting over the raw rows counted refusals against the ceiling.

    Measured here, 25 unscorable rows ahead of 50 good ones, `--limit 30`
    (jobsync costs 2 requests per job, so 30 requests buys 15 jobs):

        budget first    prepared= 0  refused=15 waiting=60 requests_needed=30
        validate first  prepared=15  refused=25 waiting=35 requests_needed=30

    The old order spent the entire window on rows it was about to refuse and
    promoted nothing at all, while 50 healthy rows waited for a budget
    nothing was going to spend.
    """

    def test_refused_rows_do_not_consume_the_request_budget(self):
        bad = [
            {"company": f"Bad{i}", "title": "Eng", "url": f"https://x/bad{i}"}
            for i in range(25)
        ]
        good = [
            {
                "companyName": f"Good{i}",
                "company": f"Good{i}",
                "jobTitle": "Engineer",
                "title": "Engineer",
                "url": f"https://x/good{i}",
                "jobUrl": f"https://x/good{i}",
                "jobDescription": "word " * 200,
                "workplaceType": "Remote",
                "fit_score": 80,
                "score_reasons": {"skill_match": "strong"},
                "work_authorization": "open",
                "suggested_variant": "genai_agents",
                "skills": ["python"],
            }
            for i in range(50)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rows.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(bad + good, f)
            _code, parsed, _err, _text = run(
                ["promote-prepare", "--rows", "@" + path, "--limit", "30"]
            )
        self.assertEqual(len(parsed["refused"]), 25)
        self.assertEqual(parsed["prepared"], 15)
        self.assertEqual(parsed["waiting"], 35)


class TestKeywordsReportFlag(unittest.TestCase):
    def test_top_zero_is_refused_even_when_the_jd_is_empty(self):
        """The guard sat below two early returns, so the paths most likely
        to be hit never reached it: `--top 0` on an empty JD exited 0 with a
        report."""
        with tempfile.TemporaryDirectory() as tmp:
            jd = os.path.join(tmp, "jd.txt")
            cv = os.path.join(tmp, "cv.txt")
            for path in (jd, cv):
                open(path, "w", encoding="utf-8").close()
            code, _parsed, err, _text = run(
                ["keywords-report", "--jd", jd, "--cv", cv, "--top", "0"]
            )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "KeywordsError")


def _greenhouse_job():
    return {
        "id": 1,
        "title": "Engineer",
        "company_name": "Acme",
        "absolute_url": "https://x/1",
        "location": {"name": "Remote"},
        "content": "<p>hi</p>",
    }


def _lever_job():
    return {
        "id": "a",
        "text": "Engineer",
        "hostedUrl": "https://x/a",
        "categories": {"location": "Remote"},
        "descriptionPlain": "hi",
    }


def _ashby_job():
    return {
        "id": "a",
        "title": "Engineer",
        "jobUrl": "https://x/a",
        "location": "Remote",
        "descriptionPlain": "hi",
        "isListed": True,
    }


if __name__ == "__main__":
    unittest.main()

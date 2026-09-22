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
import shutil
import sys
import tempfile
import unittest
import unittest.mock

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


class TestACleanBoardStillReturnsRows(unittest.TestCase):
    """The happy path had no test at all, so breaking it stayed green.

    `_Rows` used to be returned only when something was skipped:

        return rows if not skipped else _Rows(rows, skipped)

    Restoring that line leaves all 244 tests passing and turns every clean
    board — the overwhelmingly common case — into a refusal, because
    `jobhunter.py` reads `rows.skipped` unconditionally:

        {"error": "AttributeError",
         "message": "'list' object has no attribute 'skipped'"}

    Every other CLI test plants a stray entry first, so none of them ever
    exercised a payload with zero skipped postings.
    """

    def test_greenhouse(self):
        self._assert_clean("greenhouse", {"jobs": [_greenhouse_job()]}, [])

    def test_lever(self):
        self._assert_clean("lever", [_lever_job()], ["--company", "Acme"])

    def test_ashby(self):
        self._assert_clean("ashby", {"jobs": [_ashby_job()]}, ["--company", "Acme"])

    def _assert_clean(self, board, payload, extra):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "board.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            code, parsed, err, _text = run(
                ["ats-normalize", "--board", board, "--path", path] + extra
            )
        self.assertEqual(code, 0, f"{board} refused a clean board: {err}")
        self.assertEqual(len(parsed["rows"]), 1)
        self.assertEqual(parsed["skipped"], [])


class TestAtsFetchOnACleanBoard(unittest.TestCase):
    """`cmd_ats_fetch` reads `rows.skipped` on the same object
    `cmd_ats_normalize` does, so the two share the invariant — but only
    `ats-normalize` had a clean-board test, leaving the fetch path's happy
    case unexercised."""

    def test_emits_rows_and_an_empty_skipped_list(self):
        payload = json.dumps({"jobs": [_greenhouse_job()]}).encode()

        class FakeResponse:
            status = 200

            def __init__(self):
                self._body = io.BytesIO(payload)

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            def read(self, size=-1):
                return self._body.read(size)

        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "board.json")
            with unittest.mock.patch(
                "urllib.request.urlopen", return_value=FakeResponse()
            ):
                code, parsed, _err, text = run(
                    [
                        "ats-fetch", "--board", "greenhouse",
                        "--slug", "acme", "--dest", dest,
                    ]
                )
        self.assertEqual(code, 0)
        self.assertIsNotNone(parsed, f"stdout was not parseable JSON: {text!r}")
        self.assertEqual(len(parsed["rows"]), 1)
        self.assertEqual(parsed["skipped"], [])

    def test_the_fetch_log_stays_off_stdout(self):
        """A log line on stdout made `json.load` fail on a real fetch."""
        payload = json.dumps({"jobs": [_greenhouse_job()]}).encode()

        class FakeResponse:
            status = 200

            def __init__(self):
                self._body = io.BytesIO(payload)

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            def read(self, size=-1):
                return self._body.read(size)

        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "board.json")
            with unittest.mock.patch(
                "urllib.request.urlopen", return_value=FakeResponse()
            ):
                _code, _parsed, err, text = run(
                    [
                        "ats-fetch", "--board", "greenhouse",
                        "--slug", "acme", "--dest", dest,
                    ]
                )
        json.loads(text)  # raises if anything preceded the JSON
        self.assertIn("ats.fetch:", err)


class TestAScalarJobsKeyIsANamedRefusal(unittest.TestCase):
    """Lever checked its container type; Greenhouse and Ashby checked only
    that the key existed, so `{"jobs": 5}` reached the loop and surfaced
    `TypeError: 'int' object is not iterable` — a crash wearing a refusal's
    clothes, which the skills are told to report rather than retry."""

    def test_greenhouse(self):
        self._assert_named("greenhouse", {"jobs": 5}, [])

    def test_ashby(self):
        self._assert_named("ashby", {"jobs": 5}, ["--company", "Acme"])

    def _assert_named(self, board, payload, extra):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "board.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            code, _parsed, err, _text = run(
                ["ats-normalize", "--board", board, "--path", path] + extra
            )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "AtsError")
        self.assertIn("not a list of postings", json.loads(err)["message"])


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

    def test_each_listed_row_carries_its_row_key(self):
        """Two SKILL.md tell the model the key "comes back with it from
        queue-list". It did not — the rows were the raw JSONL objects, so the
        only route to a key was one `queue-key` subprocess per row."""
        with tempfile.TemporaryDirectory() as tmp:
            queue = os.path.join(tmp, "queue.jsonl")
            row = {"company": "A", "jobTitle": "Eng", "jobUrl": "https://x/a"}
            with open(queue, "w", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            _code, parsed, _err, _text = run(["queue-list", "--queue", queue])
            _c2, key_payload, _e2, _t2 = run(
                ["queue-key", "--row", json.dumps(row)]
            )
        self.assertIn("row_key", parsed["rows"][0])
        self.assertEqual(parsed["rows"][0]["row_key"], key_payload["row_key"])

    def test_listing_does_not_write_row_key_into_the_queue_file(self):
        """It is a view. Storing it would put a derived value in the file the
        key is derived FROM."""
        with tempfile.TemporaryDirectory() as tmp:
            queue = os.path.join(tmp, "queue.jsonl")
            row = {"company": "A", "jobTitle": "Eng", "jobUrl": "https://x/a"}
            with open(queue, "w", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            before = open(queue, "rb").read()
            run(["queue-list", "--queue", queue])
            after = open(queue, "rb").read()
        self.assertEqual(before, after)


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


class TestRenderDocx(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ajob2-cli-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write_markdown(self, text, name="cv.md"):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_it_renders_and_reports_the_output_blocks_and_notes(self):
        source = self.write_markdown("# Rin Halvorsen\n\nProduct engineer.\n")
        out = os.path.join(self.tmp, "cv.docx")
        code, parsed, _err, _text = run(["render-docx", "--in", source, "--out", out])
        self.assertEqual(code, 0)
        self.assertEqual(parsed["out"], out)
        self.assertEqual(parsed["blocks"], 2)
        self.assertEqual(parsed["notes"], [])
        self.assertTrue(os.path.exists(out))

    def test_an_unverified_claim_refuses_and_writes_no_file(self):
        source = self.write_markdown("# CV\n\n- revenue up 40% [verifikasi]\n")
        out = os.path.join(self.tmp, "cv.docx")
        code, parsed, err, _text = run(["render-docx", "--in", source, "--out", out])
        self.assertEqual(code, 1)
        self.assertIsNone(parsed)
        self.assertEqual(json.loads(err)["error"], "UnverifiedClaimError")
        # Asserted, not assumed: the whole point of the gate is the absence
        # of a file, and a warning that still writes one is not a gate.
        self.assertFalse(os.path.exists(out))

    def test_the_refusal_message_names_the_source_file_and_line(self):
        source = self.write_markdown("# CV\n\n- revenue up 40% [verifikasi]\n")
        out = os.path.join(self.tmp, "cv.docx")
        _code, _parsed, err, _text = run(["render-docx", "--in", source, "--out", out])
        self.assertIn("cv.md:3", json.loads(err)["message"])

    def test_allow_unverified_renders_and_reports_the_stripped_marker(self):
        source = self.write_markdown("# CV\n\n- revenue up 40% [verifikasi]\n")
        out = os.path.join(self.tmp, "cv.docx")
        code, parsed, err, _text = run(
            ["render-docx", "--in", source, "--out", out, "--allow-unverified"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(parsed["out"], out)
        self.assertTrue(os.path.exists(out))
        self.assertTrue(any("marker(s) removed" in n for n in parsed["notes"]))
        self.assertIn("marker(s) removed", err)

    def test_an_out_that_is_not_a_docx_is_refused(self):
        # `--out cover-letter.md` as a typo destroyed the draft cover letter.
        source = self.write_markdown("# CV\n\nProduct engineer.\n")
        victim = os.path.join(self.tmp, "cover-letter.md")
        with open(victim, "w", encoding="utf-8") as handle:
            handle.write("Dear hiring manager,\n")
        code, _parsed, err, _text = run(
            ["render-docx", "--in", source, "--out", victim]
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "DestinationError")
        with open(victim, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "Dear hiring manager,\n")

    def test_an_uppercase_docx_extension_is_accepted(self):
        source = self.write_markdown("# CV\n\nProduct engineer.\n")
        out = os.path.join(self.tmp, "CV.DOCX")
        code, _parsed, _err, _text = run(["render-docx", "--in", source, "--out", out])
        self.assertEqual(code, 0)

    def test_notes_reach_both_stdout_json_and_stderr(self):
        source = self.write_markdown(
            "# CV\n\n| Skill | Years |\n|---|---|\n| Python | 8 |\n"
        )
        out = os.path.join(self.tmp, "cv.docx")
        code, parsed, err, _text = run(["render-docx", "--in", source, "--out", out])
        self.assertEqual(code, 0)
        self.assertTrue(parsed["notes"])
        self.assertIn("render-docx: line 3: table flattened", err)

    def test_stdout_holds_one_json_document_and_nothing_else(self):
        source = self.write_markdown("# CV\n\nProduct engineer.\n")
        out = os.path.join(self.tmp, "cv.docx")
        _code, parsed, _err, text = run(["render-docx", "--in", source, "--out", out])
        self.assertIsNotNone(parsed)
        self.assertEqual(text.count("\n{"), 0)
        # The render's own observability line must not land on stdout.
        self.assertNotIn("docx.render:", text)

    def test_a_missing_in_flag_is_a_usage_error(self):
        out = os.path.join(self.tmp, "cv.docx")
        code, _parsed, err, _text = run(["render-docx", "--out", out])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "UsageError")

    def test_a_missing_out_flag_is_a_usage_error(self):
        source = self.write_markdown("# CV\n")
        code, _parsed, err, _text = run(["render-docx", "--in", source])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "UsageError")

    def test_out_equal_to_in_refuses_and_leaves_the_markdown_intact(self):
        source = self.write_markdown("# CV\n\nProduct engineer.\n")
        code, _parsed, err, _text = run(
            ["render-docx", "--in", source, "--out", source]
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "DestinationError")
        with open(source, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "# CV\n\nProduct engineer.\n")

    def test_out_equal_to_in_by_a_different_spelling_still_refuses(self):
        source = self.write_markdown("# CV\n\nProduct engineer.\n")
        indirect = os.path.join(self.tmp, ".", "cv.md")
        code, _parsed, err, _text = run(
            ["render-docx", "--in", source, "--out", indirect]
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "DestinationError")

    def test_out_differing_only_by_case_refuses_on_a_case_insensitive_filesystem(self):
        """macOS's default APFS is case-insensitive — this project's platform.

        Compared as strings, `cv.md` and `CV.MD` are two files; on disk they
        are one. The render overwrote the tailored markdown with a ZIP, and
        the source the whole `tailor` pipeline produced was gone with no
        backup and no warning.

        On a case-SENSITIVE filesystem the two really are different files and
        refusing would be wrong, so the assertion follows what the filesystem
        itself reports rather than demanding a refusal unconditionally.
        """
        source = self.write_markdown("# CV\n\nProduct engineer.\n")
        shouty = os.path.join(self.tmp, "CV.MD")
        case_insensitive = os.path.exists(shouty)

        code, _parsed, err, _text = run(
            ["render-docx", "--in", source, "--out", shouty]
        )
        if case_insensitive:
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(err)["error"], "DestinationError")
        else:
            self.assertEqual(code, 0)
        # Either way, the source markdown must still be markdown.
        with open(source, "rb") as handle:
            self.assertNotEqual(handle.read()[:2], b"PK")

    def test_the_same_file_helper_reports_a_hard_link_as_the_same_file(self):
        # The case-only test is a no-op on a case-sensitive filesystem, so
        # `samefile` semantics are asserted directly too, through a link,
        # which behaves the same everywhere.
        source = self.write_markdown("# CV\n")
        link = os.path.join(self.tmp, "linked.md")
        os.link(source, link)
        self.assertTrue(jobhunter._same_file(source, link))
        self.assertFalse(
            jobhunter._same_file(source, os.path.join(self.tmp, "absent.docx"))
        )

    def test_a_missing_output_directory_is_a_named_refusal(self):
        source = self.write_markdown("# CV\n")
        out = os.path.join(self.tmp, "nope", "cv.docx")
        code, _parsed, err, _text = run(["render-docx", "--in", source, "--out", out])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "DestinationError")

    def test_a_missing_input_file_is_a_named_refusal_not_a_traceback(self):
        out = os.path.join(self.tmp, "cv.docx")
        missing = os.path.join(self.tmp, "absent.md")
        code, _parsed, err, _text = run(
            ["render-docx", "--in", missing, "--out", out]
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "FileNotFoundError")

    def test_an_input_that_is_a_directory_is_a_named_refusal(self):
        out = os.path.join(self.tmp, "cv.docx")
        code, _parsed, err, _text = run(["render-docx", "--in", self.tmp, "--out", out])
        self.assertEqual(code, 1)
        self.assertIn(json.loads(err)["error"], ("IsADirectoryError", "PermissionError"))

    def test_an_empty_markdown_file_is_a_named_refusal(self):
        source = self.write_markdown("   \n")
        out = os.path.join(self.tmp, "cv.docx")
        code, _parsed, err, _text = run(["render-docx", "--in", source, "--out", out])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "EmptyDocumentError")
        self.assertFalse(os.path.exists(out))

    def test_a_relative_path_works_from_the_current_directory(self):
        source = self.write_markdown("# CV\n\nProduct engineer.\n")
        previous = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, previous)
        code, parsed, _err, _text = run(
            ["render-docx", "--in", "cv.md", "--out", "cv.docx"]
        )
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "cv.docx")))
        self.assertEqual(parsed["out"], "cv.docx")
        self.assertTrue(os.path.exists(source))


class TestRenderPdf(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ajob3-cli-pdf-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write_markdown(self, text, name="cv.md"):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_it_renders_and_reports_the_output_pages_blocks_and_notes(self):
        source = self.write_markdown("# Rin Halvorsen\n\nProduct engineer.\n")
        out = os.path.join(self.tmp, "cv.pdf")
        code, parsed, _err, _text = run(["render-pdf", "--in", source, "--out", out])
        self.assertEqual(code, 0)
        self.assertEqual(parsed["out"], out)
        self.assertEqual(set(parsed), {"out", "pages", "blocks", "notes", "bytes"})
        self.assertEqual(parsed["blocks"], 2)
        self.assertEqual(parsed["notes"], [])
        self.assertTrue(os.path.exists(out))

    def test_an_out_that_is_not_a_pdf_is_refused(self):
        # `--out cv.md` as a typo overwrites the tailored markdown itself.
        source = self.write_markdown("# CV\n\nProduct engineer.\n", name="source.md")
        victim = os.path.join(self.tmp, "cv.md")
        with open(victim, "w", encoding="utf-8") as handle:
            handle.write("tailored markdown\n")
        code, _parsed, err, _text = run(["render-pdf", "--in", source, "--out", victim])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "DestinationError")
        with open(victim, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "tailored markdown\n")

    def test_out_equal_to_in_refuses_and_leaves_the_markdown_intact(self):
        # Named `.pdf` so the suffix check passes and the same-file check
        # (not just the suffix check) is the one that actually refuses.
        source = self.write_markdown("# CV\n\nProduct engineer.\n", name="cv.pdf")
        code, _parsed, err, _text = run(["render-pdf", "--in", source, "--out", source])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "DestinationError")
        with open(source, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "# CV\n\nProduct engineer.\n")

    def test_an_uppercase_pdf_extension_is_accepted(self):
        source = self.write_markdown("# CV\n\nProduct engineer.\n")
        out = os.path.join(self.tmp, "CV.PDF")
        code, _parsed, _err, _text = run(["render-pdf", "--in", source, "--out", out])
        self.assertEqual(code, 0)

    def test_page_a4_produces_an_a4_mediabox(self):
        source = self.write_markdown("# CV\n\nProduct engineer.\n")
        out = os.path.join(self.tmp, "cv.pdf")
        code, _parsed, _err, _text = run(
            ["render-pdf", "--in", source, "--out", out, "--page", "a4"]
        )
        self.assertEqual(code, 0)
        with open(out, "rb") as handle:
            data = handle.read()
        self.assertIn(b"/MediaBox [0 0 595 842]", data)

    def test_an_unsupported_page_size_is_a_usage_error(self):
        source = self.write_markdown("# CV\n\nProduct engineer.\n")
        out = os.path.join(self.tmp, "cv.pdf")
        code, _parsed, err, _text = run(
            ["render-pdf", "--in", source, "--out", out, "--page", "b5"]
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "UsageError")

    def test_a_missing_input_file_is_a_named_refusal_not_a_traceback(self):
        out = os.path.join(self.tmp, "cv.pdf")
        missing = os.path.join(self.tmp, "absent.md")
        code, _parsed, err, _text = run(
            ["render-pdf", "--in", missing, "--out", out]
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "FileNotFoundError")

    def test_an_unverified_claim_refuses_and_writes_no_file(self):
        source = self.write_markdown("# CV\n\n- revenue up 40% [verifikasi]\n")
        out = os.path.join(self.tmp, "cv.pdf")
        code, parsed, err, _text = run(["render-pdf", "--in", source, "--out", out])
        self.assertEqual(code, 1)
        self.assertIsNone(parsed)
        self.assertEqual(json.loads(err)["error"], "UnverifiedClaimError")
        self.assertFalse(os.path.exists(out))

    def test_allow_unverified_renders_and_reports_the_stripped_marker(self):
        source = self.write_markdown("# CV\n\n- revenue up 40% [verifikasi]\n")
        out = os.path.join(self.tmp, "cv.pdf")
        code, parsed, err, _text = run(
            ["render-pdf", "--in", source, "--out", out, "--allow-unverified"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(parsed["out"], out)
        self.assertTrue(os.path.exists(out))
        self.assertTrue(any("marker(s) removed" in n for n in parsed["notes"]))
        self.assertIn("marker(s) removed", err)

    def test_an_unsupported_character_is_a_named_refusal(self):
        source = self.write_markdown("# CV\n\nRevenue grew → upward.\n")
        out = os.path.join(self.tmp, "cv.pdf")
        code, parsed, err, _text = run(["render-pdf", "--in", source, "--out", out])
        self.assertEqual(code, 1)
        self.assertIsNone(parsed)
        self.assertEqual(json.loads(err)["error"], "UnsupportedCharacterError")
        self.assertFalse(os.path.exists(out))

    def test_notes_reach_both_stdout_json_and_stderr(self):
        source = self.write_markdown(
            "# CV\n\n| Skill | Years |\n|---|---|\n| Python | 8 |\n"
        )
        out = os.path.join(self.tmp, "cv.pdf")
        code, parsed, err, _text = run(["render-pdf", "--in", source, "--out", out])
        self.assertEqual(code, 0)
        self.assertTrue(parsed["notes"])
        self.assertIn("render-pdf: line 3: table flattened", err)

    def test_stdout_holds_one_json_document_and_nothing_else(self):
        source = self.write_markdown("# CV\n\nProduct engineer.\n")
        out = os.path.join(self.tmp, "cv.pdf")
        _code, parsed, _err, text = run(["render-pdf", "--in", source, "--out", out])
        self.assertIsNotNone(parsed)
        self.assertEqual(text.count("\n{"), 0)
        # The render's own observability line must not land on stdout.
        self.assertNotIn("pdf.render:", text)

    def test_a_missing_in_flag_is_a_usage_error(self):
        out = os.path.join(self.tmp, "cv.pdf")
        code, _parsed, err, _text = run(["render-pdf", "--out", out])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "UsageError")

    def test_a_missing_out_flag_is_a_usage_error(self):
        source = self.write_markdown("# CV\n")
        code, _parsed, err, _text = run(["render-pdf", "--in", source])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "UsageError")

    def test_a_missing_output_directory_is_a_named_refusal(self):
        source = self.write_markdown("# CV\n")
        out = os.path.join(self.tmp, "nope", "cv.pdf")
        code, _parsed, err, _text = run(["render-pdf", "--in", source, "--out", out])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "DestinationError")


class TestTemplateCheckCv(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ajob4-cli-template-check-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, text, name="cv.md"):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_a_clean_cv_reports_ok_true(self):
        source = self.write(
            "# Rin Halvorsen\n\n"
            "Berlin, Germany · rin@example.com · +49 000 0000\n\n"
            "## Professional Summary\n\nBackend engineer.\n\n"
            "## Technical Skills\n\n- Python\n\n"
            "## Work Experience\n\n### Staff Engineer — Example Corp\n\n"
            "Jan 2022 – Present · Berlin, Germany\n\n"
            "- Cut latency by 40%\n\n"
            "## Education\n\nBSc, Example University, 2015\n"
        )
        code, parsed, _err, _text = run(
            ["template-check", "--cv", source, "--template", "technical"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            parsed,
            {"kind": "cv", "template": "technical", "findings": [], "ok": True},
        )

    def test_a_cv_with_findings_reports_ok_false_but_still_exits_0(self):
        source = self.write("Just prose, no name heading.\n")
        code, parsed, _err, _text = run(
            ["template-check", "--cv", source, "--template", "technical"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(parsed["kind"], "cv")
        self.assertFalse(parsed["ok"])
        self.assertTrue(parsed["findings"])
        self.assertIn("no-name", [f["rule"] for f in parsed["findings"]])


class TestTemplateCheckLetter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ajob4-cli-template-check-letter-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, text, name="cover-letter.md"):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def _valid_letter_body(self, words_per_paragraph=(85, 85, 85, 65)):
        # P1 opens with the company and role so `--company`/`--role` pass.
        p1 = "Acme's Engineer role is the reason I am reaching out today, " + " ".join(
            "word%d" % i for i in range(words_per_paragraph[0] - 11)
        )
        paragraphs = [p1] + [
            " ".join("word%d" % i for i in range(n)) for n in words_per_paragraph[1:]
        ]
        return (
            "# Rin Halvorsen\n\n"
            "Berlin, Germany · rin@example.com · +49 000 0000\n\n"
            "Dear Acme Hiring Team,\n\n"
            + "\n\n".join(paragraphs)
            + "\n\nSincerely,\n\nRin Halvorsen\n"
        )

    def test_a_clean_letter_reports_ok_true_and_level_reflects_the_flag(self):
        source = self.write(self._valid_letter_body())
        code, parsed, _err, _text = run(
            [
                "template-check", "--letter", source, "--level", "mid",
                "--company", "Acme", "--role", "Engineer",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(parsed["kind"], "letter")
        self.assertEqual(parsed["level"], "mid")
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["findings"], [])

    def test_both_cv_and_letter_flags_is_refused(self):
        cv = self.write("# X\n", name="cv.md")
        letter = self.write(self._valid_letter_body(), name="cover-letter.md")
        code, _parsed, err, _text = run(
            [
                "template-check", "--cv", cv, "--template", "technical",
                "--letter", letter, "--level", "mid",
            ]
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "TemplateError")

    def test_neither_cv_nor_letter_flag_is_refused(self):
        code, _parsed, err, _text = run(["template-check"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "TemplateError")

    def test_cv_without_template_is_refused(self):
        cv = self.write("# X\n", name="cv.md")
        code, _parsed, err, _text = run(["template-check", "--cv", cv])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "TemplateError")

    def test_letter_without_level_is_refused(self):
        letter = self.write(self._valid_letter_body())
        code, _parsed, err, _text = run(["template-check", "--letter", letter])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "TemplateError")

    def test_unknown_template_is_refused(self):
        cv = self.write("# X\n", name="cv.md")
        code, _parsed, err, _text = run(
            ["template-check", "--cv", cv, "--template", "does-not-exist"]
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "TemplateError")

    def test_unknown_level_is_refused(self):
        letter = self.write(self._valid_letter_body())
        code, _parsed, err, _text = run(
            ["template-check", "--letter", letter, "--level", "does-not-exist"]
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "TemplateError")

    def test_missing_cv_file_is_refused_and_names_the_path(self):
        missing = os.path.join(self.tmp, "absent.md")
        code, _parsed, err, _text = run(
            ["template-check", "--cv", missing, "--template", "technical"]
        )
        self.assertEqual(code, 1)
        payload = json.loads(err)
        self.assertEqual(payload["error"], "TemplateError")
        self.assertIn(missing, payload["message"])

    def test_missing_letter_file_is_refused_and_names_the_path(self):
        missing = os.path.join(self.tmp, "absent.md")
        code, _parsed, err, _text = run(
            ["template-check", "--letter", missing, "--level", "mid"]
        )
        self.assertEqual(code, 1)
        payload = json.loads(err)
        self.assertEqual(payload["error"], "TemplateError")
        self.assertIn(missing, payload["message"])


class TestTemplateCheckHelp(unittest.TestCase):
    def test_help_lists_the_subcommand(self):
        code, _parsed, _err, text = run(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("template-check", text)


if __name__ == "__main__":
    unittest.main()

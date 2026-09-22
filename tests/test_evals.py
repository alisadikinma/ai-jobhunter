"""Structural tests for the Phase G eval suites (docs/evals/).

These tests never judge whether a real model run against a fixture actually
produces the right `fit_score` or CV — that is what the eval files
themselves are for, run by a human or an agent against live Claude calls.
What is checked here is the *mechanical contract* the plan pins down: the
three eval files exist, each names at least 5 cases with explicit pass
criteria, the two named regression cases the plan calls out by name exist
in `scoring.md`, the salary-absent regression case also exists,
`profile.md` carries the `[verifikasi]` suppression case, and every fixture
file under `docs/evals/fixtures/` parses as JSON and is non-empty.
"""

import contextlib
import glob
import io
import json
import os
import sys
import re
import tempfile
import unittest
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVALS_DIR = os.path.join(REPO_ROOT, "docs", "evals")
FIXTURES_DIR = os.path.join(EVALS_DIR, "fixtures")

SCORING_MD = os.path.join(EVALS_DIR, "scoring.md")
TAILORING_MD = os.path.join(EVALS_DIR, "tailoring.md")
PROFILE_MD = os.path.join(EVALS_DIR, "profile.md")
DOCX_MD = os.path.join(EVALS_DIR, "docx-rendering.md")
SAMPLES_DIR = os.path.join(EVALS_DIR, "samples")

_CASE_HEADING_RE = re.compile(r"^###\s+Case\s+\d+.*$", re.MULTILINE)


def _read(path):
    # Deliberately a plain `open()`, not a helper that swallows the error —
    # the TDD step for this phase expects `FileNotFoundError` naming the
    # missing path when the eval file does not exist yet.
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _cases(text):
    """Return `(heading, body)` for every `### Case N ...` block in `text`."""
    headings = list(_CASE_HEADING_RE.finditer(text))
    cases = []
    for i, m in enumerate(headings):
        start = m.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        cases.append((m.group(0), text[start:end]))
    return cases


class TestEvalFilesExist(unittest.TestCase):
    def test_scoring_md_exists(self):
        self.assertTrue(os.path.isfile(SCORING_MD), f"missing {SCORING_MD}")

    def test_tailoring_md_exists(self):
        self.assertTrue(os.path.isfile(TAILORING_MD), f"missing {TAILORING_MD}")

    def test_profile_md_exists(self):
        self.assertTrue(os.path.isfile(PROFILE_MD), f"missing {PROFILE_MD}")


class TestEachEvalNamesAtLeastFiveCasesWithPassCriteria(unittest.TestCase):
    def _assert_min_cases_with_pass_criteria(self, path, minimum=5):
        text = _read(path)
        cases = _cases(text)
        self.assertGreaterEqual(
            len(cases),
            minimum,
            f"{path}: found {len(cases)} '### Case N' headings, need >= {minimum}",
        )
        for heading, body in cases:
            self.assertIn(
                "Pass criteria",
                body,
                f"{path}: case {heading!r} has no 'Pass criteria' section",
            )

    def test_scoring_md_has_min_cases(self):
        self._assert_min_cases_with_pass_criteria(SCORING_MD)

    def test_tailoring_md_has_min_cases(self):
        self._assert_min_cases_with_pass_criteria(TAILORING_MD)

    def test_profile_md_has_min_cases(self):
        self._assert_min_cases_with_pass_criteria(PROFILE_MD)


class TestTailoringNewJudgementCases(unittest.TestCase):
    """AJOB-3 Phase H: tailoring.md must carry a case for each of the three
    new judgements `skills/tailor/SKILL.md` now makes — a pasted JD, the
    blocking agreement gate, and a `gap` row never reaching rendered output.
    """

    def setUp(self):
        self.text = _read(TAILORING_MD)
        self.cases = _cases(self.text)

    def _case_headings_containing(self, phrase):
        return [h for h, _b in self.cases if phrase.lower() in h.lower()]

    def test_pasted_jd_case_present(self):
        self.assertTrue(
            self._case_headings_containing("pasted JD"),
            "no case heading in tailoring.md contains 'pasted JD'",
        )

    def test_agreement_gate_case_present(self):
        self.assertTrue(
            self._case_headings_containing("agreement gate"),
            "no case heading in tailoring.md contains 'agreement gate'",
        )

    def test_gap_never_rendered_case_present(self):
        self.assertTrue(
            self._case_headings_containing("gap never rendered"),
            "no case heading in tailoring.md contains 'gap never rendered'",
        )


class TestScoringRegressionCases(unittest.TestCase):
    """The plan's verification checklist names these regression cases
    explicitly; a scoring.md missing any of them is not the eval Phase G
    asked for, whatever else it contains."""

    def setUp(self):
        self.text = _read(SCORING_MD)
        self.cases = _cases(self.text)

    def _case_bodies_matching(self, *patterns):
        matches = []
        for heading, body in self.cases:
            block = heading + "\n" + body
            if all(re.search(p, block, re.IGNORECASE) for p in patterns):
                matches.append((heading, body))
        return matches

    def test_no_sponsorship_regression_case_expects_closed(self):
        matches = self._case_bodies_matching(
            r"REGRESSION", r"work_authorization", r"\bclosed\b"
        )
        self.assertTrue(
            matches,
            "no case in scoring.md is a named REGRESSION case asserting "
            "work_authorization == closed",
        )

    def test_model_research_regression_case_expects_low_role_fit(self):
        matches = self._case_bodies_matching(
            r"REGRESSION", r"(phd|ph\.d)", r"\blow\b"
        )
        self.assertTrue(
            matches,
            "no case in scoring.md is a named REGRESSION case asserting the "
            "PhD/model-research posting scores LOW on role fit",
        )

    def test_no_salary_regression_case_expects_absent_not_zero(self):
        matches = self._case_bodies_matching(
            r"REGRESSION", r"salary", r"absent", r"never.*\b0\b|\bnot\b.*\b0\b"
        )
        self.assertTrue(
            matches,
            "no case in scoring.md is a named REGRESSION case asserting the "
            "salary dimension is ABSENT (never 0) when the JD states no salary",
        )


class TestProfileVerifikasiSuppressionCase(unittest.TestCase):
    def test_verifikasi_never_rendered_case_present(self):
        text = _read(PROFILE_MD)
        cases = _cases(text)
        matches = [
            (h, b)
            for h, b in cases
            if "[verifikasi]" in (h + b) and re.search(r"never", h + b, re.IGNORECASE)
        ]
        self.assertTrue(
            matches,
            "profile.md has no case proving a [verifikasi] claim is "
            "suppressed from the rendered CV",
        )


class TestFixturesParseAndAreNonEmpty(unittest.TestCase):
    def test_at_least_six_fixture_files(self):
        paths = sorted(glob.glob(os.path.join(FIXTURES_DIR, "*.json")))
        self.assertGreaterEqual(
            len(paths), 6, f"found only {len(paths)} fixture files in {FIXTURES_DIR}"
        )

    def test_every_fixture_parses_and_is_non_empty(self):
        paths = sorted(glob.glob(os.path.join(FIXTURES_DIR, "*.json")))
        self.assertTrue(paths, f"no fixture files found under {FIXTURES_DIR}")
        for path in paths:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIsInstance(data, dict, f"{path}: top level is not a JSON object")
            # Contract spelling, not the snake_case these fixtures shipped
            # with — see TestFixturesMatchThePinnedRowContract for why.
            for field in ("source", "dateRetrieved", "company", "jobTitle", "jobDescription"):
                self.assertIn(field, data, f"{path}: missing {field!r}")
                self.assertTrue(
                    str(data[field]).strip(), f"{path}: {field!r} is empty"
                )
            self.assertGreater(
                len(data["jobDescription"]),
                100,
                f"{path}: job_description looks too short to be a real posting",
            )


class TestFixturesMatchThePinnedRowContract(unittest.TestCase):
    """The fixtures shipped with snake_case keys (`job_description`,
    `job_title`, `job_url`, `workplace_type`) while the pinned Scored-row
    contract — what `ats.normalize_*` emits and what `promote.to_add_job`
    reads — is camelCase.

    `docs/evals/tailoring.md` and `scoring.md` both say to run a skill
    against a fixture "as if it were the matching row in
    .jobhunter/queue/jobs.jsonl". Run that way, every fixture was a
    title-only row:

        refused [{"error": "TitleOnlyError",
                  "message": "Refusing to promote a title-only row ..."}]

    Nothing caught it because these evals are judgement evals that have
    never been executed; this test covers the part of them that IS
    deterministic — the shape of their inputs.
    """

    REQUIRED = ("company", "jobTitle", "jobUrl", "jobDescription")
    FORBIDDEN = (
        "job_description",
        "job_title",
        "job_url",
        "workplace_type",
        "job_type",
        "date_retrieved",
    )

    def _fixtures(self):
        pattern = os.path.join(os.path.dirname(SCORING_MD), "fixtures", "*.json")
        paths = sorted(glob.glob(pattern))
        self.assertTrue(paths, f"no fixtures found at {pattern}")
        return paths

    def test_every_fixture_carries_the_contract_fields(self):
        for path in self._fixtures():
            with open(path, "r", encoding="utf-8") as f:
                row = json.load(f)
            for key in self.REQUIRED:
                self.assertIn(key, row, f"{os.path.basename(path)} has no {key!r}")

    def test_no_fixture_uses_the_snake_case_spelling(self):
        for path in self._fixtures():
            with open(path, "r", encoding="utf-8") as f:
                row = json.load(f)
            for key in self.FORBIDDEN:
                self.assertNotIn(
                    key,
                    row,
                    f"{os.path.basename(path)} uses {key!r}; the pinned row "
                    "contract is camelCase, and a skill reading this fixture "
                    "as a queue row would not see the field at all",
                )

    def test_a_fixture_is_promotable_once_scored(self):
        """The end the prose actually promises: a fixture plus the scoring
        fields is a row `promote` accepts."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        import promote

        with open(self._fixtures()[0], "r", encoding="utf-8") as f:
            row = json.load(f)
        row.update(
            fit_score=80,
            score_reasons={"skill_match": "strong"},
            work_authorization="unclear",
            suggested_variant="genai_agents",
            skills=["python"],
        )
        self.assertIn(promote.match_quality(row), ("full", "provisional"))
        self.assertEqual(promote.to_add_job(row)["jobTitle"], row["jobTitle"])



class TestDocxRenderingEval(unittest.TestCase):
    """The one thing no program in this repository can check for itself.

    Every other check on a rendered `.docx` is a program reading a file a
    program wrote, which proves well-formedness and not openability. The
    deterministic half — that the eval document and its sample exist, and
    that a case is declared per target application — is asserted here. The
    judgement half belongs to a human with Word open.
    """

    APPLICATIONS = ("Microsoft Word", "Google Docs", "LibreOffice")

    def test_docx_rendering_md_exists(self):
        self.assertTrue(os.path.isfile(DOCX_MD), f"missing {DOCX_MD}")

    def test_it_declares_a_case_for_each_target_application(self):
        text = _read(DOCX_MD)
        for application in self.APPLICATIONS:
            self.assertIn(application, text)
        self.assertGreaterEqual(len(_cases(text)), len(self.APPLICATIONS))

    def test_every_case_names_the_file_to_open_and_what_a_pass_looks_like(self):
        for heading, body in _cases(_read(DOCX_MD)):
            self.assertIn(".docx", body, heading)
            self.assertIn("Pass:", body, heading)

    def test_a_sample_docx_is_committed(self):
        samples = glob.glob(os.path.join(SAMPLES_DIR, "*.docx"))
        self.assertTrue(samples, f"no .docx sample under {SAMPLES_DIR}")

    def test_every_committed_sample_is_a_valid_openable_archive(self):
        for sample in glob.glob(os.path.join(SAMPLES_DIR, "*.docx")):
            with zipfile.ZipFile(sample) as archive:
                self.assertIsNone(archive.testzip(), sample)
                self.assertIn("word/document.xml", archive.namelist(), sample)

    def test_the_sample_matches_what_the_current_code_renders(self):
        """Regenerating must reproduce the committed bytes exactly.

        The sample is the fixed artefact a human checked by hand. If the
        renderer changes and the sample is not regenerated, the manual pass
        recorded in the ledger refers to bytes nobody ships any more.
        """
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        import docx  # noqa: PLC0415 — imported here so the rest of this file

        source = os.path.join(REPO_ROOT, "tests", "fixtures", "tailored_cv.md")
        with open(source, encoding="utf-8") as handle:
            markdown = handle.read()
        with tempfile.TemporaryDirectory() as tmp:
            regenerated = os.path.join(tmp, "cv.docx")
            with contextlib.redirect_stderr(io.StringIO()):
                docx.render(markdown, regenerated, source="tailored_cv.md")
            with open(regenerated, "rb") as fresh:
                fresh_bytes = fresh.read()
        committed = os.path.join(SAMPLES_DIR, "tailored-cv-sample.docx")
        with open(committed, "rb") as handle:
            self.assertEqual(handle.read(), fresh_bytes)

    def test_the_manual_open_check_is_recorded_as_not_run(self):
        """The ledger must carry the debt, not a tick nobody earned.

        Scoped to the open-debt section on purpose. Searching the whole file
        for "NOT RUN" was vacuous: the string also appears twice inside the
        copied plan checklist, so deleting the one entry this test exists to
        protect left the suite green.
        """
        ledger = os.path.join(
            REPO_ROOT, ".gaspol", "progress", "PROGRESS-AJOB-2.md"
        )
        text = _read(ledger)
        # Anchored to a heading at the start of a line: the phrase also
        # appears INSIDE Phase F's checklist prose, and splitting on the
        # first occurrence read the checklist instead of the section.
        heading = re.search(r"^## Utang terbuka$", text, re.MULTILINE)
        self.assertIsNotNone(heading, "ledger has no '## Utang terbuka' section")
        section = text[heading.end() :].split("\n## ", 1)[0]
        self.assertIn("NOT RUN", section)
        # The ledger names the applications in its own shorthand ("Word /
        # Google Docs / LibreOffice"), so the debt is matched on the shortest
        # spelling that still identifies each one. The eval document itself
        # is held to the full names, by `test_it_declares_a_case_for_each_
        # target_application`.
        for application in ("Word", "Google Docs", "LibreOffice"):
            self.assertIn(application, section)


if __name__ == "__main__":
    unittest.main()

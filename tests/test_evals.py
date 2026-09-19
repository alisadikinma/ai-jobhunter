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

import glob
import json
import os
import sys
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVALS_DIR = os.path.join(REPO_ROOT, "docs", "evals")
FIXTURES_DIR = os.path.join(EVALS_DIR, "fixtures")

SCORING_MD = os.path.join(EVALS_DIR, "scoring.md")
TAILORING_MD = os.path.join(EVALS_DIR, "tailoring.md")
PROFILE_MD = os.path.join(EVALS_DIR, "profile.md")

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


if __name__ == "__main__":
    unittest.main()

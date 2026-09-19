import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import keywords  # noqa: E402

# A trimmed, verbatim excerpt of a real Greenhouse job description, obtained via:
#   python3 -c "import sys;sys.path.insert(0,'scripts');import ats;
#   rows=ats.normalize_greenhouse('tests/fixtures/greenhouse_acme.json');
#   print([r for r in rows if r['jobTitle']=='Abuse Investigator'][0]['jobDescription'][:1400])"
# Verified by direct token count (see scratch check during authoring): 202 tokens
# extracted, 124 survive stopword removal, "stripe" is the single most frequent
# survived term (4 occurrences), and "fraud" occurs twice ("product abuse and
# fraud", "complex patterns of fraud").
REAL_JD_EXCERPT = (
    "Who we are About Stripe Stripe is a financial infrastructure platform for "
    "businesses. Millions of companies - from the world’s largest enterprises "
    "to the most ambitious startups - use Stripe to accept payments, grow their "
    "revenue, and accelerate new business opportunities. Our mission is to "
    "increase the GDP of the internet, and we have a staggering amount of work "
    "ahead. That means you have an unprecedented opportunity to put the global "
    "economy within everyone's reach while doing the most important work of "
    "your career. About the team Abuse Operations is the front-line incident "
    "response and remediation function handling active product abuse and fraud "
    "impacting Stripe and its merchants. This multi-disciplinary group, "
    "spanning Incident Managers, Investigators, Forward Deployed Security "
    "Engineers, and Data Scientists, neutralizes active attacks, gathers "
    "requirements for operational tooling, and leads incidents. The team works "
    "directly with impacted merchants to resolve technical incidents and "
    "policy abuse rapidly. Operating primarily across Eastern, Pacific and "
    "Western European time zones, these team members regularly coordinate "
    "with global stakeholders across the world. What you’ll do You'll play a "
    "critical role in safeguarding our financial ecosystem by investigating "
    "high-risk accounts and identifying complex patterns of fraud during "
    "incidents. You will lead incident response for "
)
REAL_CV_EXCERPT = (
    "Experienced fraud and abuse investigator. Led incident response for "
    "card-testing and account-takeover incidents, working with global "
    "merchants and cross-functional security teams. Comfortable with "
    "ambiguity and high-risk account analysis."
)


class TestCoverageEmptyAndWhitespaceInput(unittest.TestCase):
    def test_empty_jd_returns_empty_report_with_reason(self):
        report = keywords.coverage("", "some CV text with real words")
        self.assertEqual(report["covered"], [])
        self.assertEqual(report["missing"], [])
        self.assertEqual(report["extracted_count"], 0)
        self.assertEqual(report["survived_count"], 0)
        self.assertTrue(report["reason"])

    def test_empty_cv_returns_empty_report_with_reason(self):
        report = keywords.coverage("some JD text with real words", "")
        self.assertEqual(report["covered"], [])
        self.assertEqual(report["missing"], [])
        self.assertTrue(report["reason"])

    def test_whitespace_only_jd_returns_empty_report(self):
        report = keywords.coverage("   \n\t  ", "some CV text")
        self.assertEqual(report["covered"], [])
        self.assertEqual(report["missing"], [])
        self.assertTrue(report["reason"])

    def test_whitespace_only_cv_returns_empty_report(self):
        report = keywords.coverage("some JD text", "   \n\t  ")
        self.assertEqual(report["covered"], [])
        self.assertEqual(report["missing"], [])
        self.assertTrue(report["reason"])

    def test_jd_with_no_extractable_words_never_divides_by_zero(self):
        # Non-empty, non-whitespace input that still tokenizes to zero words.
        report = keywords.coverage("!!! ??? ---", "python developer")
        self.assertEqual(report["covered"], [])
        self.assertEqual(report["missing"], [])
        self.assertEqual(report["extracted_count"], 0)
        self.assertEqual(report["survived_count"], 0)


class TestWholeTermMatchingNotSubstring(unittest.TestCase):
    def test_java_in_cv_does_not_mark_javascript_covered(self):
        report = keywords.coverage(
            "We need strong Java skills for this backend role.",
            "Proficient in JavaScript and TypeScript development.",
        )
        self.assertIn("java", report["missing"])
        self.assertNotIn("java", report["covered"])

    def test_javascript_in_cv_does_not_mark_java_covered(self):
        report = keywords.coverage(
            "We need strong JavaScript skills for frontend work.",
            "Experienced backend developer with deep Java expertise.",
        )
        self.assertIn("javascript", report["missing"])
        self.assertNotIn("javascript", report["covered"])


class TestCasingAndPunctuationDifferences(unittest.TestCase):
    def test_casing_differences_still_match(self):
        report = keywords.coverage(
            "Looking for a PYTHON developer with Python experience.",
            "I have five years of python programming experience.",
        )
        self.assertIn("python", report["covered"])

    def test_punctuation_differences_still_match(self):
        report = keywords.coverage(
            "Requires: Docker, Kubernetes, and CI/CD pipelines!",
            "Hands-on with docker kubernetes and CI CD pipelines.",
        )
        self.assertIn("docker", report["covered"])
        self.assertIn("kubernetes", report["covered"])
        self.assertIn("ci cd", report["covered"])


class TestHyphenation(unittest.TestCase):
    def test_hyphenated_term_recognized_as_one_term(self):
        report = keywords.coverage(
            "We value end-to-end ownership of projects.",
            "Demonstrated end-to-end ownership across teams.",
        )
        self.assertIn("end-to-end", report["covered"])


class TestRepeatedTermRanking(unittest.TestCase):
    def test_term_repeated_many_times_counts_once_but_ranks_first(self):
        report = keywords.coverage(
            "Python python PYTHON python required. Django required too.",
            "I have hands-on python and Django knowledge.",
        )
        self.assertEqual(report["covered"].count("python"), 1)
        self.assertLess(
            report["covered"].index("python"), report["covered"].index("django")
        )


class TestNonAsciiText(unittest.TestCase):
    def test_non_ascii_text_handled_without_crashing_or_mangling(self):
        report = keywords.coverage(
            "Kandidat wajib mahir cafe operations and 日本語 fluency.",
            "Pengalaman kerja di cafe dan mahir 日本語.",
        )
        self.assertIn("cafe", report["covered"])
        self.assertIn("日本語", report["covered"])


class TestLengthAsymmetry(unittest.TestCase):
    def test_cv_longer_than_jd(self):
        cv = ("A very long resume. " * 20) + (
            " I worked as a data analyst using SQL daily. "
        ) + ("Other unrelated paragraph text here. " * 20)
        report = keywords.coverage("Seeking a data analyst with SQL skills.", cv)
        self.assertIn("sql", report["covered"])
        self.assertIn("data analyst", report["covered"])

    def test_jd_longer_than_cv(self):
        jd = (
            "We need a candidate skilled in Kubernetes, Docker, Terraform, "
            "AWS, and Python, with strong communication skills."
        )
        report = keywords.coverage(jd, "Experienced Python developer.")
        self.assertIn("python", report["covered"])
        self.assertIn("kubernetes", report["missing"])
        self.assertIn("docker", report["missing"])


class TestRealJobDescriptionExcerpt(unittest.TestCase):
    """Uses a real Greenhouse posting fetched via ats.normalize_greenhouse
    (see the module docstring above for the exact command)."""

    def test_real_excerpt_extraction_and_coverage_counts(self):
        report = keywords.coverage(REAL_JD_EXCERPT, REAL_CV_EXCERPT)
        # Observed by direct tokenisation of this exact excerpt during authoring.
        self.assertEqual(report["extracted_count"], 202)
        self.assertEqual(report["survived_count"], 124)
        # "fraud" genuinely appears twice in this excerpt ("product abuse and
        # fraud", "complex patterns of fraud") and the CV states it explicitly.
        self.assertIn("fraud", report["covered"])
        self.assertIn("incident", report["covered"])
        self.assertIn("merchants", report["covered"])
        # "stripe" (the company name, 4 occurrences) is never mentioned in the
        # CV excerpt, so it must be reported as missing, not covered.
        self.assertIn("stripe", report["missing"])
        self.assertNotIn("stripe", report["covered"])


class TestRender(unittest.TestCase):
    def test_heading_states_keyword_overlap_not_ats_score(self):
        report = keywords.coverage("Python required for this role.", "Python experience.")
        body = keywords.render(report)
        heading = body.splitlines()[0]
        self.assertIn("keyword overlap", heading.lower())
        self.assertNotIn("ats", heading.lower())

    def test_render_states_extracted_and_survived_counts(self):
        report = keywords.coverage(REAL_JD_EXCERPT, REAL_CV_EXCERPT)
        body = keywords.render(report)
        self.assertIn(str(report["extracted_count"]), body)
        self.assertIn(str(report["survived_count"]), body)

    def test_render_of_empty_report_states_reason_without_crashing(self):
        report = keywords.coverage("", "cv text")
        body = keywords.render(report)
        self.assertIn(report["reason"], body)


class TestSymbolBearingTechnologyNames(unittest.TestCase):
    r"""`[^\W_]+` collapsed "C++" and "C#" to "c", so a CV mentioning a grade
    of C marked both covered — the false "covered" this module exists to
    prevent.
    """

    def test_cpp_and_csharp_are_not_covered_by_a_bare_c(self):
        report = keywords.coverage(
            "Strong C++ and C# systems programming required.",
            "I once got a grade of C in maths.",
        )
        self.assertNotIn("c++", report["covered"])
        self.assertNotIn("c#", report["covered"])
        self.assertIn("c++", report["missing"])
        self.assertIn("c#", report["missing"])

    def test_cpp_is_covered_when_the_cv_actually_says_cpp(self):
        report = keywords.coverage("C++ required.", "Ten years of C++.")
        self.assertIn("c++", report["covered"])

    def test_dotnet_is_not_covered_by_the_word_net(self):
        report = keywords.coverage(".NET experience required.", "Worked on a net profit model.")
        # Assert on the token the bug produced. Asserting ".net" was vacuous:
        # ".net" was never a token at all, so the test passed while ".NET"
        # was still collapsing to "net" and matching "net profit".
        self.assertNotIn("net", report["covered"])
        self.assertNotIn(".net", report["covered"])
        self.assertIn(".net", report["missing"])


class TestReportTruncation(unittest.TestCase):
    """A real posting yields hundreds of terms; an unbounded report is not read."""

    def _long_jd(self):
        return " ".join(f"term{i} skill{i} tool{i}" for i in range(200))

    def test_lists_are_truncated_to_top_n(self):
        report = keywords.coverage(self._long_jd(), "nothing matches here", top_n=10)
        self.assertEqual(len(report["missing"]), 10)
        self.assertGreater(report["missing_total"], 10)

    def test_heading_says_when_the_list_is_truncated(self):
        report = keywords.coverage(self._long_jd(), "nothing matches here", top_n=10)
        heading = [l for l in keywords.render(report).splitlines() if l.startswith("## Missing")][0]
        self.assertIn("of", heading)
        self.assertIn(str(report["missing_total"]), heading)

    def test_non_positive_top_n_is_an_error_not_everything(self):
        """`--top 0` silently returned all 688 terms — the opposite of the ask."""
        for bad in (0, -5):
            with self.assertRaises(keywords.KeywordsError):
                keywords.coverage(self._long_jd(), "nothing", top_n=bad)

    def test_top_n_none_returns_everything(self):
        report = keywords.coverage(self._long_jd(), "nothing", top_n=None)
        self.assertEqual(len(report["missing"]), report["missing_total"])


if __name__ == "__main__":
    unittest.main()

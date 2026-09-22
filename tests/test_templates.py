"""Tests for `scripts/templates.py` — CV template loader and `check_cv`.

`sys.path` is pointed at `scripts/` the same way every other test module in
this repository does it. That also settles a naming question the plan calls
out explicitly: this repository has a `templates/` directory at its root
(holding the actual `.md` template files) sitting right next to `scripts/`,
and a `scripts/templates.py` module. Because `scripts/` is inserted at the
front of `sys.path` (not the repo root), `import templates` resolves to the
*module*, never the directory — proven below rather than assumed.
"""

import os
import re
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import pdf  # noqa: E402
import templates  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CV_TEMPLATE_NAMES = ("hybrid", "leadership", "technical")

# A section-only heading: `## `, not `### ` (the experience-entry skeleton
# inside Work Experience, which is not a section of its own).
_SECTION_HEADING_RE = re.compile(r"^##(?!#)\s+(.*)$", re.M)


class TestModuleIdentity(unittest.TestCase):
    def test_templates_import_resolves_to_the_scripts_module_not_the_directory(self):
        # The repo also has a `templates/` directory (the template files
        # themselves) at the repo root. If `sys.path` ever put the repo root
        # ahead of `scripts/`, `import templates` would resolve to that
        # directory (a namespace package) instead of `scripts/templates.py`,
        # and every function below would silently vanish rather than fail
        # loudly. Pin it down explicitly.
        self.assertTrue(
            templates.__file__.replace(os.sep, "/").endswith("scripts/templates.py")
        )


class TestListCvTemplates(unittest.TestCase):
    def test_lists_all_three_sorted(self):
        self.assertEqual(templates.list_cv_templates(), ["hybrid", "leadership", "technical"])


class TestLoadCvTemplate(unittest.TestCase):
    def test_technical_first_section_is_professional_summary_aliased_summary(self):
        loaded = templates.load_cv_template("technical")
        self.assertEqual(
            loaded["sections"][0],
            {"name": "Professional Summary", "aliases": ["Summary"], "optional": False},
        )

    def test_all_three_load_without_error(self):
        for name in CV_TEMPLATE_NAMES:
            with self.subTest(name=name):
                loaded = templates.load_cv_template(name)
                self.assertEqual(loaded["name"], name)
                self.assertTrue(loaded["sections"])

    def test_leadership_board_positions_alias_and_optional(self):
        loaded = templates.load_cv_template("leadership")
        section = next(s for s in loaded["sections"] if s["name"] == "Board Positions")
        self.assertEqual(section["aliases"], ["Advisory Roles"])
        self.assertTrue(section["optional"])

    def test_hybrid_certifications_is_optional_with_no_aliases(self):
        loaded = templates.load_cv_template("hybrid")
        section = next(s for s in loaded["sections"] if s["name"] == "Certifications")
        self.assertEqual(section["aliases"], [])
        self.assertTrue(section["optional"])

    def test_technical_work_experience_is_not_optional(self):
        loaded = templates.load_cv_template("technical")
        section = next(s for s in loaded["sections"] if s["name"] == "Work Experience")
        self.assertFalse(section["optional"])

    def test_unknown_name_raises_template_error(self):
        with self.assertRaises(templates.TemplateError):
            templates.load_cv_template("does-not-exist")

    def test_file_without_comment_block_raises_and_names_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "broken.md")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("# Not a template\n\nJust prose.\n")
            with unittest.mock.patch.object(templates, "_CV_DIR", tmp):
                with self.assertRaises(templates.TemplateError) as caught:
                    templates.load_cv_template("broken")
            self.assertIn(path, str(caught.exception))

    def test_malformed_sections_line_empty_name_names_the_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "broken.md")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "<!-- gaspol-jobhunter cv-template\n"
                    "name: broken\n"
                    "sections:\n"
                    "- | Something\n"
                    "-->\n"
                    "# <Full name>\n"
                )
            with unittest.mock.patch.object(templates, "_CV_DIR", tmp):
                with self.assertRaises(templates.TemplateError) as caught:
                    templates.load_cv_template("broken")
            self.assertIn(":4:", str(caught.exception))


class TestTemplateFilesRenderCleanly(unittest.TestCase):
    """Every template's own file, taken exactly as it sits on disk, must
    render through `pdf.render` with no refusal and no leak of the comment
    block's own machine-readable text — the thing Phase A's multi-line
    comment strip exists to guarantee for exactly this file shape."""

    def test_each_template_renders_with_no_refusal_and_no_leaked_comment(self):
        for name in CV_TEMPLATE_NAMES:
            with self.subTest(name=name):
                path = os.path.join(REPO_ROOT, "templates", "cv", "%s.md" % name)
                with open(path, "r", encoding="utf-8") as handle:
                    markdown = handle.read()
                with tempfile.TemporaryDirectory() as tmp:
                    out = os.path.join(tmp, "%s.pdf" % name)
                    # No refusal is the assertion: `pdf.render` raises on an
                    # unverified marker, an unsupported character, or an
                    # empty document, and this call must not.
                    pdf.render(markdown, out)
                    with open(out, "rb") as fh:
                        data = fh.read()
                # The rendered PDF is a binary stream with escaped text
                # operators — decoding permissively is enough to grep for
                # the two machine-readable words that must never appear.
                text = data.decode("latin-1")
                self.assertNotIn("sections:", text)
                self.assertNotIn("cv-template", text)


class TestTemplateHeadingsMatchDefinition(unittest.TestCase):
    """The file's own `## ` headings, read straight off disk, must equal
    `load_cv_template(name)["sections"]`'s canonical names in the same
    order — the file and its machine-readable definition cannot drift."""

    def test_headings_equal_canonical_section_names_in_order(self):
        for name in CV_TEMPLATE_NAMES:
            with self.subTest(name=name):
                loaded = templates.load_cv_template(name)
                expected = [section["name"] for section in loaded["sections"]]
                path = os.path.join(REPO_ROOT, "templates", "cv", "%s.md" % name)
                with open(path, "r", encoding="utf-8") as handle:
                    body = handle.read()
                found = _SECTION_HEADING_RE.findall(body)
                self.assertEqual(found, expected)


_VALID_TECHNICAL_CV = """# Rin Halvorsen

Berlin, Germany · rin@example.com · +49 000 0000 · linkedin.com/in/rin

## Professional Summary

Backend engineer with 8 years shipping distributed systems at scale.

## Technical Skills

- Languages: Python, Go
- Frameworks: FastAPI, gRPC

## Work Experience

### Staff Engineer — Example Corp

Jan 2022 – Present · Berlin, Germany

- Cut p99 latency by 40% by rewriting the hot path in Go

## Education

BSc Computer Science, Example University, 2015

## Certifications

## Awards
"""


_VALID_HYBRID_CV = """# Rin Halvorsen

Berlin, Germany · rin@example.com · +49 000 0000 · linkedin.com/in/rin

## Professional Summary

Product-minded generalist with 6 years across ops and engineering.

## Core Skills

- Ops: SQL, Python

## Work Experience

### Ops Lead — Example Corp

Jan 2022 – Present · Berlin, Germany

- Reduced ticket backlog by 30% by rebuilding the triage pipeline

## Education

BA Economics, Example University, 2016
"""

_VALID_LEADERSHIP_CV = """# Rin Halvorsen

Berlin, Germany · rin@example.com · +49 000 0000 · linkedin.com/in/rin

## Executive Summary

VP Engineering with P&L responsibility for a 120-person org.

## Work Experience

### VP Engineering — Example Corp

Jan 2020 – Present · Berlin, Germany

- Grew ARR from $10M to $40M while cutting infrastructure spend 20%

## Education

MBA, Example University, 2012
"""


class TestCheckCvValidInput(unittest.TestCase):
    def test_a_valid_technical_cv_has_no_findings(self):
        self.assertEqual(templates.check_cv(_VALID_TECHNICAL_CV, "technical"), [])

    def test_a_valid_hybrid_cv_has_no_findings(self):
        self.assertEqual(templates.check_cv(_VALID_HYBRID_CV, "hybrid"), [])

    def test_a_valid_leadership_cv_has_no_findings(self):
        self.assertEqual(templates.check_cv(_VALID_LEADERSHIP_CV, "leadership"), [])


def _cv(headings):
    """Build a minimal technical-shaped CV: an H1, a contact line, then one
    `## <heading>` block per entry in `headings`, each with a blank line
    and one plain (non-bullet) paragraph. Returns `(markdown, heading_line)`
    where `heading_line[heading]` is that heading's 1-based line number —
    exact, not guessed, so tests can assert a finding's line precisely."""
    lines = ["# Rin Halvorsen", "", "Berlin, Germany"]
    heading_line = {}
    for heading in headings:
        lines.append("")
        heading_line[heading] = len(lines) + 1
        lines.append("## %s" % heading)
        lines.append("")
        lines.append("Placeholder body text.")
    return "\n".join(lines) + "\n", heading_line


def _rule_lines(findings, rule):
    return sorted(f["line"] for f in findings if f["rule"] == rule)


class TestCheckCvSectionRules(unittest.TestCase):
    def test_alias_heading_is_accepted(self):
        markdown, _ = _cv(["Professional Summary", "Technical Skills", "Experience"])
        findings = templates.check_cv(markdown, "technical")
        self.assertEqual(_rule_lines(findings, "unknown-section"), [])

    def test_heading_case_and_whitespace_variants_are_accepted(self):
        markdown, _ = _cv(["PROFESSIONAL    SUMMARY"])
        findings = templates.check_cv(markdown, "technical")
        self.assertEqual(_rule_lines(findings, "unknown-section"), [])

    def test_unknown_section(self):
        markdown, heading_line = _cv(["Hobbies"])
        findings = templates.check_cv(markdown, "technical")
        self.assertEqual(
            _rule_lines(findings, "unknown-section"), [heading_line["Hobbies"]]
        )

    def test_order_education_before_work_experience(self):
        markdown, heading_line = _cv(
            ["Professional Summary", "Education", "Work Experience"]
        )
        findings = templates.check_cv(markdown, "technical")
        self.assertEqual(
            _rule_lines(findings, "order"), [heading_line["Work Experience"]]
        )

    def test_duplicate_section(self):
        markdown, heading_line = _cv(["Professional Summary", "Professional Summary"])
        findings = templates.check_cv(markdown, "technical")
        duplicate_line = [
            index for index, line in enumerate(markdown.splitlines(), start=1)
            if line == "## Professional Summary"
        ][1]
        self.assertEqual(_rule_lines(findings, "duplicate-section"), [duplicate_line])

    def test_missing_section_no_education(self):
        markdown, _ = _cv(["Professional Summary", "Technical Skills", "Work Experience"])
        findings = templates.check_cv(markdown, "technical")
        missing = [f for f in findings if f["rule"] == "missing-section"]
        self.assertEqual(len(missing), 1)
        self.assertIn("Education", missing[0]["message"])
        self.assertEqual(missing[0]["line"], len(markdown.splitlines()) + 1)

    def test_optional_sections_omitted_produce_no_finding(self):
        markdown, _ = _cv(["Professional Summary", "Technical Skills", "Work Experience", "Education"])
        self.assertEqual(templates.check_cv(markdown, "technical"), [])


def _bullet_cv(bullet_text):
    """A minimal CV with exactly one bullet line, under `## Work
    Experience` at a fixed, known line number (7)."""
    return "# Rin Halvorsen\n\nBerlin, Germany\n\n## Work Experience\n\n%s\n" % bullet_text


class TestCheckCvPronounRule(unittest.TestCase):
    def test_i_led_is_flagged(self):
        findings = templates.check_cv(_bullet_cv("- I led the migration"), "technical")
        self.assertEqual(_rule_lines(findings, "pronoun"), [7])

    def test_my_team_is_flagged(self):
        findings = templates.check_cv(_bullet_cv("- Grew my team's throughput"), "technical")
        self.assertEqual(_rule_lines(findings, "pronoun"), [7])

    def test_we_built_is_flagged_case_insensitively(self):
        findings = templates.check_cv(_bullet_cv("- We built the pipeline"), "technical")
        self.assertEqual(_rule_lines(findings, "pronoun"), [7])

    def test_our_is_flagged(self):
        findings = templates.check_cv(_bullet_cv("- Owned our roadmap"), "technical")
        self.assertEqual(_rule_lines(findings, "pronoun"), [7])

    def test_ai_is_not_flagged(self):
        findings = templates.check_cv(
            _bullet_cv("- Deployed AI models to production"), "technical"
        )
        self.assertEqual(_rule_lines(findings, "pronoun"), [])

    def test_iot_is_not_flagged(self):
        findings = templates.check_cv(
            _bullet_cv("- Instrumented IoT devices for telemetry"), "technical"
        )
        self.assertEqual(_rule_lines(findings, "pronoun"), [])

    def test_i_slash_o_is_not_flagged(self):
        findings = templates.check_cv(
            _bullet_cv("- Wired I/O buffers for the driver"), "technical"
        )
        self.assertEqual(_rule_lines(findings, "pronoun"), [])

    def test_mine_is_not_flagged_word_boundary(self):
        findings = templates.check_cv(
            _bullet_cv("- Reduced downtime at Acme Mine Corp"), "technical"
        )
        self.assertEqual(_rule_lines(findings, "pronoun"), [])

    def test_pronoun_in_a_non_bullet_paragraph_is_not_flagged(self):
        markdown = "# Rin Halvorsen\n\nBerlin, Germany\n\n## Work Experience\n\nI led the migration.\n"
        findings = templates.check_cv(markdown, "technical")
        self.assertEqual(_rule_lines(findings, "pronoun"), [])


class TestCheckCvNameAndContact(unittest.TestCase):
    def test_no_name(self):
        markdown = "Just prose.\n\n## Work Experience\n\nBody\n"
        findings = templates.check_cv(markdown, "technical")
        self.assertEqual(_rule_lines(findings, "no-name"), [1])

    def test_no_contact_h1_followed_directly_by_heading(self):
        markdown = "# Rin Halvorsen\n\n## Work Experience\n\nBody\n"
        findings = templates.check_cv(markdown, "technical")
        self.assertEqual(_rule_lines(findings, "no-contact"), [3])

    def test_empty_markdown_is_no_name(self):
        # Empty input is also missing every required section, so `no-name`
        # is not the only finding — it is the one this test targets.
        findings = templates.check_cv("", "technical")
        self.assertEqual(_rule_lines(findings, "no-name"), [1])


class TestCheckCvCrlfAndSorting(unittest.TestCase):
    def test_crlf_input_is_handled_like_lf(self):
        markdown, _ = _cv(["Professional Summary", "Technical Skills", "Work Experience", "Education"])
        crlf = markdown.replace("\n", "\r\n")
        self.assertEqual(templates.check_cv(crlf, "technical"), [])

    def test_findings_are_sorted_by_line(self):
        # Missing-section findings land at `len(lines) + 1` — deliberately
        # the LAST line in the document — while a pronoun finding earlier
        # in the same CV sits at a small line number. Without the explicit
        # sort at the end of `check_cv`, the missing-section finding
        # (computed after the section scan, before the pronoun scan) would
        # sit ahead of it in the raw, unsorted append order.
        markdown = _bullet_cv("- I led the migration")  # Education is missing here
        findings = templates.check_cv(markdown, "technical")
        rules = [f["rule"] for f in findings]
        self.assertIn("pronoun", rules)
        self.assertIn("missing-section", rules)
        lines = [f["line"] for f in findings]
        self.assertEqual(lines, sorted(lines))
        self.assertLess(findings[0]["line"], findings[-1]["line"])


class TestCheckCvTemplatesPassTheirOwnCheck(unittest.TestCase):
    """The templates are the reference — if `check_cv` finds anything wrong
    with a template file checked against its own name, either the file or
    the rules have drifted from each other."""

    def test_each_template_has_no_findings_against_itself(self):
        for name in CV_TEMPLATE_NAMES:
            with self.subTest(name=name):
                path = os.path.join(REPO_ROOT, "templates", "cv", "%s.md" % name)
                with open(path, "r", encoding="utf-8") as handle:
                    markdown = handle.read()
                self.assertEqual(templates.check_cv(markdown, name), [])


class TestLetterLevels(unittest.TestCase):
    def test_parses_the_three_bands_from_the_shipped_file(self):
        self.assertEqual(
            templates.letter_levels(),
            {"entry": (200, 250), "mid": (250, 400), "executive": (400, 450)},
        )

    # Each refusal of the letter template's own comment block, so a broken
    # shipped file fails loudly instead of checking letters against nothing.
    def test_a_comment_without_levels_is_refused(self):
        text = "<!-- gaspol-jobhunter cover-letter\nsign-offs: Sincerely,\n-->\n# L\n"
        with self.assertRaisesRegex(templates.TemplateError, "no 'levels:' entries"):
            templates._parse_letter_template_text(text, "t.md")

    def test_a_comment_without_sign_offs_is_refused(self):
        text = "<!-- gaspol-jobhunter cover-letter\nlevels:\n- mid 250-400\n-->\n# L\n"
        with self.assertRaisesRegex(templates.TemplateError, "missing 'sign-offs:'"):
            templates._parse_letter_template_text(text, "t.md")

    def test_a_never_closed_comment_is_refused(self):
        text = "<!-- gaspol-jobhunter cover-letter\nlevels:\n- mid 250-400\n"
        with self.assertRaisesRegex(templates.TemplateError, "never closed"):
            templates._parse_letter_template_text(text, "t.md")


class TestLetterTemplateFileParsesAndRenders(unittest.TestCase):
    """The shipped file itself must parse (via `letter_levels`, already
    proven above) and render through `pdf.render` with no refusal — the
    same guarantee Phase B proved for the three CV templates."""

    def test_renders_with_no_refusal(self):
        path = os.path.join(REPO_ROOT, "templates", "cover-letter.md")
        with open(path, "r", encoding="utf-8") as handle:
            markdown = handle.read()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "cover-letter.pdf")
            pdf.render(markdown, out)  # raises on any refusal
            self.assertTrue(os.path.exists(out))


def _filler_words(n):
    """`n` distinct whitespace-separated word-like tokens."""
    return " ".join("alpha%d" % i for i in range(n))


def _paragraph(total_words, lead_text=""):
    """A paragraph of exactly `total_words` words. `lead_text` (itself made
    of whole words) is placed first and topped up with filler words to reach
    the count, so a test can pin exactly what P1 opens with while still
    controlling the total word count precisely."""
    lead_words = lead_text.split()
    filler_needed = total_words - len(lead_words)
    assert filler_needed >= 0, "lead_text has more words than total_words"
    filler = _filler_words(filler_needed)
    return (lead_text + " " + filler).strip()


def _letter(
    para_words,
    lead_texts=None,
    salutation="Dear Example Team Hiring Team,",
    sign_off="Sincerely,",
    name="Rin Halvorsen",
    subject=None,
):
    """Build a cover letter: H1 name, contact line, optional H2 subject
    (ignored by every rule), the salutation, `len(para_words)` body
    paragraphs (each exactly `para_words[i]` words, `lead_texts.get(i, "")`
    first), the sign-off, and the name again.

    Returns the markdown text only — callers that need exact finding lines
    build the pieces by hand instead (`_bullet_cv`'s pattern in the CV tests
    above), because the fixed preamble here already makes every line number
    predictable from the call's own arguments.
    """
    lead_texts = lead_texts or {}
    paragraphs = [
        _paragraph(n, lead_texts.get(i, "")) for i, n in enumerate(para_words)
    ]
    parts = ["# %s" % name, "", "Berlin, Germany · rin@example.com · +49 000 0000", ""]
    if subject is not None:
        parts.append(subject)
        parts.append("")
    parts.append(salutation)
    parts.append("")
    for paragraph in paragraphs:
        parts.append(paragraph)
        parts.append("")
    parts.append(sign_off)
    parts.append("")
    parts.append(name)
    return "\n".join(parts) + "\n"


def _letter_total_words(total, **kwargs):
    """A valid 4-paragraph letter whose body has exactly `total` words."""
    return _letter([total - 3, 1, 1, 1], **kwargs)


class TestCheckLetterValidInput(unittest.TestCase):
    def test_a_valid_letter_per_level_has_no_findings(self):
        band_midpoints = {"entry": 225, "mid": 325, "executive": 425}
        for level, total in band_midpoints.items():
            with self.subTest(level=level):
                markdown = _letter_total_words(total)
                self.assertEqual(templates.check_letter(markdown, level), [])

    def test_an_optional_h2_subject_line_before_the_salutation_is_ignored(self):
        markdown = _letter_total_words(225, subject="## Re: Backend Engineer at Acme")
        self.assertEqual(templates.check_letter(markdown, "entry"), [])


class TestCheckLetterWordCountBandEdges(unittest.TestCase):
    def test_entry_band_edges_inclusive(self):
        self.assertEqual(
            _rule_lines(templates.check_letter(_letter_total_words(200), "entry"), "word-count"),
            [],
        )
        self.assertEqual(
            _rule_lines(templates.check_letter(_letter_total_words(250), "entry"), "word-count"),
            [],
        )
        self.assertNotEqual(
            _rule_lines(templates.check_letter(_letter_total_words(199), "entry"), "word-count"),
            [],
        )
        self.assertNotEqual(
            _rule_lines(templates.check_letter(_letter_total_words(251), "entry"), "word-count"),
            [],
        )

    def test_mid_band_edges_inclusive(self):
        self.assertEqual(
            _rule_lines(templates.check_letter(_letter_total_words(250), "mid"), "word-count"),
            [],
        )
        self.assertEqual(
            _rule_lines(templates.check_letter(_letter_total_words(400), "mid"), "word-count"),
            [],
        )
        self.assertNotEqual(
            _rule_lines(templates.check_letter(_letter_total_words(249), "mid"), "word-count"),
            [],
        )
        self.assertNotEqual(
            _rule_lines(templates.check_letter(_letter_total_words(401), "mid"), "word-count"),
            [],
        )

    def test_executive_band_edges_inclusive(self):
        self.assertEqual(
            _rule_lines(
                templates.check_letter(_letter_total_words(400), "executive"), "word-count"
            ),
            [],
        )
        self.assertEqual(
            _rule_lines(
                templates.check_letter(_letter_total_words(450), "executive"), "word-count"
            ),
            [],
        )
        self.assertNotEqual(
            _rule_lines(
                templates.check_letter(_letter_total_words(399), "executive"), "word-count"
            ),
            [],
        )
        self.assertNotEqual(
            _rule_lines(
                templates.check_letter(_letter_total_words(451), "executive"), "word-count"
            ),
            [],
        )

    def test_word_count_message_states_the_count_and_the_band(self):
        findings = templates.check_letter(_letter_total_words(199), "entry")
        message = next(f["message"] for f in findings if f["rule"] == "word-count")
        self.assertIn("199", message)
        self.assertIn("200-250", message)


class TestCheckLetterParagraphs(unittest.TestCase):
    def test_three_paragraphs_is_flagged(self):
        markdown = _letter([80, 80, 65], salutation="Dear Example Team Hiring Team,")
        findings = templates.check_letter(markdown, "entry")
        self.assertIn("paragraphs", [f["rule"] for f in findings])

    def test_five_paragraphs_is_flagged(self):
        markdown = _letter([45, 45, 45, 45, 45])
        findings = templates.check_letter(markdown, "entry")
        self.assertIn("paragraphs", [f["rule"] for f in findings])

    def test_exactly_four_paragraphs_is_not_flagged(self):
        markdown = _letter_total_words(225)
        findings = templates.check_letter(markdown, "entry")
        self.assertNotIn("paragraphs", [f["rule"] for f in findings])


class TestCheckLetterSalutation(unittest.TestCase):
    def test_no_salutation(self):
        markdown = _letter_total_words(225, salutation="Hello there,")
        findings = templates.check_letter(markdown, "entry")
        self.assertIn("no-salutation", [f["rule"] for f in findings])

    def test_to_whom_it_may_concern_is_generic(self):
        markdown = _letter_total_words(225, salutation="To Whom It May Concern,")
        findings = templates.check_letter(markdown, "entry")
        self.assertIn("generic-salutation", [f["rule"] for f in findings])

    def test_dear_sir_or_madam_is_generic(self):
        markdown = _letter_total_words(225, salutation="Dear Sir or Madam,")
        findings = templates.check_letter(markdown, "entry")
        self.assertIn("generic-salutation", [f["rule"] for f in findings])

    def test_an_ordinary_salutation_is_not_generic(self):
        markdown = _letter_total_words(225, salutation="Dear Jane Doe,")
        findings = templates.check_letter(markdown, "entry")
        self.assertNotIn("generic-salutation", [f["rule"] for f in findings])


class TestCheckLetterSignOff(unittest.TestCase):
    def test_no_recognised_sign_off(self):
        markdown = _letter_total_words(225, sign_off="Cheers,")
        findings = templates.check_letter(markdown, "entry")
        self.assertIn("no-sign-off", [f["rule"] for f in findings])

    def test_each_sign_off_is_accepted(self):
        for sign_off in ("Sincerely,", "Best regards,", "Kind regards,"):
            with self.subTest(sign_off=sign_off):
                markdown = _letter_total_words(225, sign_off=sign_off)
                findings = templates.check_letter(markdown, "entry")
                self.assertNotIn("no-sign-off", [f["rule"] for f in findings])


class TestCheckLetterOpeningCompanyRole(unittest.TestCase):
    def test_company_named_in_p1_is_not_flagged(self):
        markdown = _letter(
            [50, 60, 60, 55], lead_texts={0: "Acme Corp is where I want to work."}
        )
        findings = templates.check_letter(markdown, "entry", company="Acme Corp")
        self.assertNotIn("opening-company", [f["rule"] for f in findings])

    def test_company_missing_from_p1_is_flagged(self):
        markdown = _letter_total_words(225)
        findings = templates.check_letter(markdown, "entry", company="Acme Corp")
        self.assertIn("opening-company", [f["rule"] for f in findings])

    def test_role_named_in_p1_is_not_flagged(self):
        markdown = _letter(
            [50, 60, 60, 55], lead_texts={0: "The Backend Engineer role excites me."}
        )
        findings = templates.check_letter(markdown, "entry", role="Backend Engineer")
        self.assertNotIn("opening-role", [f["rule"] for f in findings])

    def test_role_missing_from_p1_is_flagged(self):
        markdown = _letter_total_words(225)
        findings = templates.check_letter(markdown, "entry", role="Backend Engineer")
        self.assertIn("opening-role", [f["rule"] for f in findings])

    def test_company_and_role_are_not_checked_when_not_given(self):
        markdown = _letter_total_words(225)
        findings = templates.check_letter(markdown, "entry")
        rules = [f["rule"] for f in findings]
        self.assertNotIn("opening-company", rules)
        self.assertNotIn("opening-role", rules)


class TestCheckLetterWeakLanguage(unittest.TestCase):
    def test_weak_opening_is_flagged(self):
        markdown = _letter(
            [50, 60, 60, 55], lead_texts={0: "I am writing to apply for this role."}
        )
        findings = templates.check_letter(markdown, "entry")
        self.assertIn("weak-opening", [f["rule"] for f in findings])

    # Spec §6 says no body SENTENCE starts with it; checking only the start
    # of each paragraph let "Hello there. I am writing to apply" through
    # (plan-verifier round 1).
    def test_weak_opening_mid_paragraph_sentence_is_flagged(self):
        for lead in (
            "Hello there. I am writing to apply for this role.",
            "Is this the team? I am writing to apply.",
            "Great news! i am writing to apply.",
        ):
            markdown = _letter([50, 60, 60, 55], lead_texts={1: lead})
            findings = templates.check_letter(markdown, "entry")
            self.assertIn("weak-opening", [f["rule"] for f in findings], lead)

    def test_i_am_writing_inside_a_sentence_is_not_flagged(self):
        markdown = _letter(
            [50, 60, 60, 55],
            lead_texts={1: "The service I am writing about cut latency by half."},
        )
        findings = templates.check_letter(markdown, "entry")
        self.assertNotIn("weak-opening", [f["rule"] for f in findings])

    def test_weak_close_is_flagged(self):
        markdown = _letter(
            [50, 60, 60, 55], lead_texts={3: "I hope to hear from you soon."}
        )
        findings = templates.check_letter(markdown, "entry")
        self.assertIn("weak-close", [f["rule"] for f in findings])

    def test_neither_appears_in_a_clean_letter(self):
        markdown = _letter_total_words(225)
        findings = templates.check_letter(markdown, "entry")
        rules = [f["rule"] for f in findings]
        self.assertNotIn("weak-opening", rules)
        self.assertNotIn("weak-close", rules)


class TestCheckLetterUnknownLevel(unittest.TestCase):
    def test_unknown_level_raises_template_error(self):
        markdown = _letter_total_words(225)
        with self.assertRaises(templates.TemplateError):
            templates.check_letter(markdown, "does-not-exist")


class TestCheckLetterCrlf(unittest.TestCase):
    def test_crlf_input_is_handled_like_lf(self):
        markdown = _letter_total_words(225)
        crlf = markdown.replace("\n", "\r\n")
        self.assertEqual(templates.check_letter(crlf, "entry"), [])


if __name__ == "__main__":
    unittest.main()

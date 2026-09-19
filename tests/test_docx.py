"""Tests for `scripts/docx.py` — markdown to an ATS-readable `.docx`.

`sys.path` is pointed at `scripts/` the same way every other test module in
this repository does it, which also makes the local `docx` module win over a
`python-docx` install if one ever appears on the machine. This project is
standard-library only, so shadowing is the intended outcome, not an accident.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import docx  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
TAILORED_CV = os.path.join(FIXTURES, "tailored_cv.md")


def read_fixture(name):
    with open(name, encoding="utf-8") as handle:
        return handle.read()


class TestParseBlocksHappyPath(unittest.TestCase):
    def test_a_heading_and_a_paragraph(self):
        self.assertEqual(
            docx.parse_blocks("# Ali\n\nHello\n"),
            [
                {"kind": "heading", "level": 1, "text": "Ali"},
                {"kind": "paragraph", "text": "Hello"},
            ],
        )

    def test_inline_emphasis_markers_are_stripped_from_the_text(self):
        blocks = docx.parse_blocks("**Bold** and *italic* and `code`\n")
        self.assertEqual(
            blocks, [{"kind": "paragraph", "text": "Bold and italic and code"}]
        )

    def test_a_run_of_lines_is_one_paragraph(self):
        blocks = docx.parse_blocks("first line\nsecond line\n")
        self.assertEqual(
            blocks, [{"kind": "paragraph", "text": "first line second line"}]
        )

    def test_bullets_become_bullet_blocks(self):
        blocks = docx.parse_blocks("- one\n* two\n")
        self.assertEqual(
            blocks,
            [
                {"kind": "bullet", "text": "one"},
                {"kind": "bullet", "text": "two"},
            ],
        )

    def test_all_three_heading_levels_carry_their_level(self):
        blocks = docx.parse_blocks("# one\n\n## two\n\n### three\n")
        self.assertEqual([b["level"] for b in blocks], [1, 2, 3])


class TestParseBlocksEdgeCases(unittest.TestCase):
    """The ten cases enumerated in the plan, one test each."""

    def test_empty_string_yields_no_blocks(self):
        self.assertEqual(docx.parse_blocks(""), [])

    def test_whitespace_only_yields_no_blocks(self):
        self.assertEqual(docx.parse_blocks("   \n\t\n  \n"), [])

    def test_a_heading_with_no_text_is_dropped(self):
        self.assertEqual(docx.parse_blocks("##\n"), [])

    def test_a_heading_marker_with_only_spaces_after_it_is_dropped(self):
        self.assertEqual(docx.parse_blocks("###   \n"), [])

    def test_four_hashes_is_a_paragraph_not_a_level_four_heading(self):
        blocks = docx.parse_blocks("#### Deep\n")
        self.assertEqual(blocks, [{"kind": "paragraph", "text": "#### Deep"}])

    def test_a_bullet_with_no_text_is_dropped(self):
        self.assertEqual(docx.parse_blocks("-\n"), [])

    def test_crlf_line_endings_parse_the_same_as_lf(self):
        self.assertEqual(
            docx.parse_blocks("# Ali\r\n\r\nHello\r\n"),
            docx.parse_blocks("# Ali\n\nHello\n"),
        )

    def test_a_horizontal_rule_produces_no_block(self):
        blocks = docx.parse_blocks("before\n\n---\n\nafter\n")
        self.assertEqual(
            blocks,
            [
                {"kind": "paragraph", "text": "before"},
                {"kind": "paragraph", "text": "after"},
            ],
        )

    def test_two_blank_lines_between_paragraphs_do_not_emit_an_empty_block(self):
        blocks = docx.parse_blocks("one\n\n\ntwo\n")
        self.assertEqual(
            blocks,
            [
                {"kind": "paragraph", "text": "one"},
                {"kind": "paragraph", "text": "two"},
            ],
        )

    def test_five_hundred_blocks_all_survive_in_order(self):
        markdown = "\n\n".join("para %d" % i for i in range(500))
        blocks = docx.parse_blocks(markdown)
        self.assertEqual(len(blocks), 500)
        self.assertEqual(blocks[0]["text"], "para 0")
        self.assertEqual(blocks[-1]["text"], "para 499")

    def test_xml_significant_characters_are_left_untouched_here(self):
        # Escaping belongs to the writer. If the parser escaped too, the text
        # would be escaped twice and print "&amp;" to the reader.
        blocks = docx.parse_blocks("a & b < c > d\n")
        self.assertEqual(blocks, [{"kind": "paragraph", "text": "a & b < c > d"}])

    def test_none_is_treated_as_empty_rather_than_raising(self):
        self.assertEqual(docx.parse_blocks(None), [])

    def test_a_literal_asterisk_separator_is_not_read_as_italics(self):
        # "a * b * c" is a real thing to write. The naive italic pattern eats
        # both asterisks and the spaces around them.
        blocks = docx.parse_blocks("a * b * c\n")
        self.assertEqual(blocks, [{"kind": "paragraph", "text": "a * b * c"}])

    def test_a_wrapped_bullet_line_continues_the_bullet(self):
        blocks = docx.parse_blocks("- Led a team of 4 through a\n  vendor migration\n")
        self.assertEqual(
            blocks,
            [{"kind": "bullet", "text": "Led a team of 4 through a vendor migration"}],
        )

    def test_a_blank_line_ends_a_bullet_continuation(self):
        blocks = docx.parse_blocks("- bullet\n\n  indented prose\n")
        self.assertEqual(
            blocks,
            [
                {"kind": "bullet", "text": "bullet"},
                {"kind": "paragraph", "text": "indented prose"},
            ],
        )

    def test_an_unindented_line_after_a_bullet_is_its_own_paragraph(self):
        blocks = docx.parse_blocks("- bullet\nnext section\n")
        self.assertEqual(
            blocks,
            [
                {"kind": "bullet", "text": "bullet"},
                {"kind": "paragraph", "text": "next section"},
            ],
        )

    def test_an_indented_bullet_stays_a_bullet(self):
        # Read as a paragraph it would print its own "- " marker.
        blocks = docx.parse_blocks("  - nested\n")
        self.assertEqual(blocks, [{"kind": "bullet", "text": "nested"}])


class TestParseBlocksInvariantOverARealCV(unittest.TestCase):
    def test_only_the_three_contract_kinds_are_ever_emitted(self):
        blocks = docx.parse_blocks(read_fixture(TAILORED_CV))
        self.assertEqual(
            {b["kind"] for b in blocks}, {"heading", "paragraph", "bullet"}
        )

    def test_every_block_carries_non_empty_text(self):
        blocks = docx.parse_blocks(read_fixture(TAILORED_CV))
        self.assertTrue(blocks)
        for block in blocks:
            self.assertTrue(block["text"].strip(), block)

    def test_level_appears_on_headings_only(self):
        for block in docx.parse_blocks(read_fixture(TAILORED_CV)):
            if block["kind"] == "heading":
                self.assertIn(block["level"], (1, 2, 3))
            else:
                self.assertNotIn("level", block)

    def test_no_markdown_syntax_survives_into_any_block_text(self):
        text = " ".join(
            b["text"] for b in docx.parse_blocks(read_fixture(TAILORED_CV))
        )
        for marker in ("**", "`", "## ", "- "):
            self.assertNotIn(marker, text)


class TestAtsLintRefusesUnverifiedClaims(unittest.TestCase):
    def test_a_verifikasi_marker_is_one_finding_on_line_one(self):
        findings = docx.ats_lint("- revenue up 40% [verifikasi]\n")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["reason"], "unverified-claim")
        self.assertEqual(findings[0]["line"], 1)
        self.assertEqual(findings[0]["text"], "- revenue up 40% [verifikasi]")

    def test_an_assumption_marker_refuses_too(self):
        findings = docx.unverified_findings("- headcount doubled [Assumption]\n")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["reason"], "unverified-claim")

    def test_clean_markdown_produces_no_findings(self):
        self.assertEqual(docx.ats_lint(read_fixture(TAILORED_CV)), [])

    def test_the_line_number_is_the_real_one_in_a_multi_line_document(self):
        markdown = "\n".join(
            [
                "# Rin Halvorsen",
                "",
                "## Experience",
                "",
                "- shipped the thing",
                "- increased revenue 40% [verifikasi]",
                "- wrote the runbook",
            ]
        )
        findings = docx.unverified_findings(markdown)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["line"], 6)
        self.assertEqual(findings[0]["text"], "- increased revenue 40% [verifikasi]")


class TestAtsLintUnverifiedEdgeCases(unittest.TestCase):
    """The seven cases enumerated in the plan, one test each."""

    def test_a_marker_in_a_heading_refuses(self):
        findings = docx.unverified_findings("## Awards [verifikasi]\n")
        self.assertEqual([f["line"] for f in findings], [1])

    def test_a_marker_inside_a_fenced_code_block_still_refuses(self):
        # A CV has no reason to carry code fences. A marker inside one is far
        # more likely a real claim than a deliberate literal, and the safe
        # direction for a safety gate is to refuse and be argued with.
        markdown = "```\n- revenue up 40% [verifikasi]\n```\n"
        self.assertEqual(len(docx.unverified_findings(markdown)), 1)

    def test_an_uppercase_marker_matches(self):
        self.assertEqual(len(docx.unverified_findings("x [VERIFIKASI]\n")), 1)

    def test_a_mixed_case_marker_matches(self):
        self.assertEqual(len(docx.unverified_findings("x [Verifikasi]\n")), 1)

    def test_inner_spaces_are_not_a_match(self):
        # The convention is exact. Loosening it invites false positives, and a
        # gate that cries wolf is a gate people learn to pass --allow past.
        self.assertEqual(docx.unverified_findings("x [ Assumption ]\n"), [])

    def test_two_markers_on_one_line_are_one_finding(self):
        markdown = "grew 40% [verifikasi] and 2x headcount [Assumption]\n"
        self.assertEqual(len(docx.unverified_findings(markdown)), 1)

    def test_a_marker_on_the_last_line_without_a_trailing_newline(self):
        findings = docx.unverified_findings("line one\nlast claim [verifikasi]")
        self.assertEqual([f["line"] for f in findings], [2])

    def test_markdown_with_no_markers_yields_an_empty_list(self):
        self.assertEqual(docx.unverified_findings("- shipped the thing\n"), [])

    def test_a_marker_like_word_without_brackets_is_not_a_match(self):
        self.assertEqual(docx.unverified_findings("needs verifikasi later\n"), [])

    def test_empty_and_none_input_yield_no_findings(self):
        self.assertEqual(docx.ats_lint(""), [])
        self.assertEqual(docx.ats_lint(None), [])


class TestAtsLintReportsWhatItDoesNotRefuse(unittest.TestCase):
    def test_a_table_is_reported_once_at_its_header_line(self):
        markdown = "| Skill | Years |\n|---|---|\n| Python | 8 |\n| Go | 3 |\n"
        reasons = [f for f in docx.ats_lint(markdown) if f["reason"] == "table"]
        self.assertEqual([f["line"] for f in reasons], [1])

    def test_a_sentence_containing_a_literal_pipe_is_not_a_table(self):
        # Multi-line on purpose. A single line can never be a table — the
        # detector needs a following separator row — so a one-line case here
        # passes even if the separator requirement is deleted entirely.
        markdown = (
            "Ran the pipeline as `cat x | sort | uniq` every morning.\n"
            "It replaced a cron job nobody owned.\n"
        )
        self.assertEqual(
            [f for f in docx.ats_lint(markdown) if f["reason"] == "table"], []
        )

    def test_two_pipe_lines_in_a_row_without_a_separator_are_not_a_table(self):
        markdown = "Shell: `a | b`\nEditor: `c | d`\nnothing else\n"
        self.assertEqual(
            [f for f in docx.ats_lint(markdown) if f["reason"] == "table"], []
        )

    def test_the_separator_row_is_what_makes_a_table_a_table(self):
        with_sep = "| Skill | Years |\n|---|---|\n| Python | 8 |\n"
        without_sep = "| Skill | Years |\n| Python | 8 |\n| Go | 3 |\n"
        self.assertTrue([f for f in docx.ats_lint(with_sep) if f["reason"] == "table"])
        self.assertEqual(
            [f for f in docx.ats_lint(without_sep) if f["reason"] == "table"], []
        )

    def test_an_image_is_reported(self):
        findings = docx.ats_lint("![headshot](photo.png)\n")
        self.assertEqual([f["reason"] for f in findings], ["image"])

    def test_a_deeply_nested_bullet_is_reported(self):
        markdown = "- one\n  - two\n    - three\n"
        deep = [f for f in docx.ats_lint(markdown) if f["reason"] == "deep-nesting"]
        self.assertEqual([f["line"] for f in deep], [3])

    def test_one_level_of_nesting_is_not_reported_as_deep(self):
        deep = [
            f for f in docx.ats_lint("- one\n  - two\n") if f["reason"] == "deep-nesting"
        ]
        self.assertEqual(deep, [])

    def test_inline_html_is_reported(self):
        findings = docx.ats_lint("<b>Skills</b>\n")
        self.assertEqual([f["reason"] for f in findings], ["html"])

    def test_a_comparison_operator_is_not_reported_as_html(self):
        # `ats._TAG_RE` alone matches "< 200ms and >" here and would delete
        # the middle of the sentence during flattening.
        self.assertEqual(docx.ats_lint("p95 < 200ms and > 1k rps\n"), [])

    def test_none_of_the_repairable_reasons_refuse(self):
        markdown = (
            "| Skill | Years |\n|---|---|\n| Python | 8 |\n\n"
            "![headshot](photo.png)\n\n<b>bold</b>\n\n- one\n    - deep\n"
        )
        self.assertTrue(docx.ats_lint(markdown))
        self.assertEqual(docx.unverified_findings(markdown), [])

    def test_every_reason_is_one_of_the_five_in_the_contract(self):
        markdown = (
            "| Skill | Years |\n|---|---|\n| Python | 8 |\n\n"
            "![x](y.png)\n\n<b>b</b>\n\n- one\n    - deep\n\nclaim [verifikasi]\n"
        )
        self.assertEqual(
            {f["reason"] for f in docx.ats_lint(markdown)},
            {"table", "image", "html", "deep-nesting", "unverified-claim"},
        )

    def test_findings_come_back_ordered_by_line(self):
        markdown = "clean\n<b>b</b>\nclaim [verifikasi]\n"
        lines = [f["line"] for f in docx.ats_lint(markdown)]
        self.assertEqual(lines, sorted(lines))


class TestUnverifiedClaimErrorMessage(unittest.TestCase):
    def test_the_message_names_the_file_the_line_and_the_claim(self):
        findings = docx.unverified_findings("a\n- revenue 40% [verifikasi]\n")
        error = docx.UnverifiedClaimError(findings, "cv.md")
        self.assertIn('cv.md:2 — "- revenue 40% [verifikasi]"', str(error))

    def test_the_error_carries_its_findings(self):
        findings = docx.unverified_findings("- x [verifikasi]\n")
        error = docx.UnverifiedClaimError(findings, "cv.md")
        self.assertEqual(error.findings, findings)

    def test_the_message_says_how_to_proceed(self):
        error = docx.UnverifiedClaimError(
            docx.unverified_findings("- x [verifikasi]\n"), "cv.md"
        )
        self.assertIn("--allow-unverified", str(error))

    def test_it_is_a_docx_error(self):
        self.assertTrue(issubclass(docx.UnverifiedClaimError, docx.DocxError))


if __name__ == "__main__":
    unittest.main()

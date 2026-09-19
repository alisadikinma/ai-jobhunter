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


if __name__ == "__main__":
    unittest.main()

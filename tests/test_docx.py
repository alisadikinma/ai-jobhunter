"""Tests for `scripts/docx.py` — markdown to an ATS-readable `.docx`.

`sys.path` is pointed at `scripts/` the same way every other test module in
this repository does it, which also makes the local `docx` module win over a
`python-docx` install if one ever appears on the machine. This project is
standard-library only, so shadowing is the intended outcome, not an accident.
"""

import os
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import docx  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
TAILORED_CV = os.path.join(FIXTURES, "tailored_cv.md")
MESSY_CV = os.path.join(FIXTURES, "messy_cv.md")


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


class TestFlattenTables(unittest.TestCase):
    def test_a_table_becomes_one_line_per_body_row(self):
        flat, _notes = docx.flatten("| Skill | Years |\n|---|---|\n| Python | 8 |\n")
        self.assertNotIn("|", flat)
        self.assertIn("Skill: Python — 8", flat)

    def test_the_separator_row_never_survives(self):
        flat, _notes = docx.flatten("| A | B |\n|---|---|\n| 1 | 2 |\n")
        self.assertNotIn("---", flat)

    def test_a_one_column_table_keeps_its_header_as_the_label(self):
        flat, _notes = docx.flatten("| Skill |\n|---|\n| Python |\n")
        self.assertIn("Skill: Python", flat)
        self.assertNotIn("|", flat)

    def test_a_row_short_of_cells_is_kept_not_dropped(self):
        flat, _notes = docx.flatten("| Skill | Years |\n|---|---|\n| Python |\n")
        self.assertIn("Skill: Python", flat)

    def test_a_table_without_a_separator_row_is_left_alone(self):
        markdown = "| Skill | Years |\n| Python | 8 |\nplain line\n"
        flat, notes = docx.flatten(markdown)
        self.assertIn("| Skill | Years |", flat)
        self.assertEqual(notes, [])

    def test_an_empty_table_produces_no_rows_and_says_so(self):
        flat, notes = docx.flatten("| Skill | Years |\n|---|---|\n")
        self.assertNotIn("|", flat)
        self.assertTrue(any("no body rows" in note for note in notes))

    def test_a_row_of_entirely_empty_cells_still_leaves_a_line(self):
        flat, _notes = docx.flatten("| Skill | Years |\n|---|---|\n|  |  |\n")
        self.assertIn("Skill:", flat)

    def test_a_sentence_with_a_literal_pipe_survives_unflattened(self):
        markdown = "Ran `cat x | sort | uniq` daily.\nIt replaced a cron job.\n"
        flat, notes = docx.flatten(markdown)
        self.assertIn("cat x | sort | uniq", flat)
        self.assertEqual(notes, [])

    def test_each_row_becomes_its_own_block(self):
        # Emitted as bare lines, consecutive rows are one run of text and
        # `parse_blocks` joins them into a single run-on paragraph. A real
        # render of a three-row skills table came out as one sentence.
        markdown = (
            "| Skill | Years |\n|---|---|\n| Python | 8 |\n"
            "| Go | 3 |\n| Rust | 1 |\n"
        )
        flat, _notes = docx.flatten(markdown)
        blocks = docx.parse_blocks(flat)
        self.assertEqual(len(blocks), 3)
        self.assertEqual({b["kind"] for b in blocks}, {"bullet"})

    def test_a_table_note_names_the_original_line_number(self):
        markdown = "intro\n\n| Skill | Years |\n|---|---|\n| Python | 8 |\n"
        _flat, notes = docx.flatten(markdown)
        self.assertTrue(any(note.startswith("line 3:") for note in notes))


class TestFlattenImagesAndLinks(unittest.TestCase):
    def test_an_image_is_removed_and_its_source_noted(self):
        flat, notes = docx.flatten("![headshot](photos/rin.png)\n")
        self.assertNotIn("rin.png", flat)
        self.assertTrue(any("photos/rin.png" in note for note in notes))

    def test_an_image_with_no_alt_text_is_still_removed(self):
        flat, _notes = docx.flatten("![](photos/rin.png)\n")
        self.assertNotIn("rin.png", flat)

    def test_an_image_with_no_source_is_removed_and_noted(self):
        flat, notes = docx.flatten("![alt]()\n")
        self.assertNotIn("![", flat)
        self.assertTrue(any("no src" in note for note in notes))

    def test_a_link_becomes_text_then_url_in_parentheses(self):
        flat, _notes = docx.flatten("See [our blog](https://example.com/b)\n")
        self.assertIn("our blog (https://example.com/b)", flat)

    def test_a_link_whose_text_equals_its_url_is_emitted_once(self):
        flat, _notes = docx.flatten("[https://example.com](https://example.com)\n")
        self.assertEqual(flat.strip(), "https://example.com")

    def test_a_link_with_no_text_falls_back_to_the_url(self):
        flat, _notes = docx.flatten("[](https://example.com)\n")
        self.assertEqual(flat.strip(), "https://example.com")

    def test_a_reference_style_link_is_left_as_written_and_noted(self):
        flat, notes = docx.flatten("Spoke at [PyCon][pycon-ref] once\n")
        self.assertIn("[PyCon][pycon-ref]", flat)
        self.assertTrue(any("reference-style" in note for note in notes))

    def test_an_image_is_removed_before_it_can_be_read_as_a_link(self):
        flat, _notes = docx.flatten("![alt](x.png)\n")
        self.assertNotIn("alt", flat)


class TestFlattenNestingAndHtml(unittest.TestCase):
    def test_three_level_nesting_collapses_to_one(self):
        markdown = "- one\n  - two\n    - three\n        - four\n"
        flat, _notes = docx.flatten(markdown)
        for line in flat.splitlines():
            self.assertLessEqual(len(line) - len(line.lstrip()), 2, line)

    def test_one_level_of_nesting_is_left_alone(self):
        flat, notes = docx.flatten("- one\n  - two\n")
        self.assertEqual(flat, "- one\n  - two\n")
        self.assertEqual(notes, [])

    def test_inline_html_is_stripped(self):
        flat, notes = docx.flatten("<b>Product engineer</b>, Amsterdam\n")
        self.assertEqual(flat.strip(), "Product engineer, Amsterdam")
        self.assertTrue(any("html" in note for note in notes))

    def test_the_space_a_stripped_tag_leaves_before_a_comma_is_closed_up(self):
        # A tag becomes a space, so "</b>," becomes " ,". A CV reading
        # "engineer , Amsterdam" looks broken to the person who opens it.
        flat, _notes = docx.flatten("<b>engineer</b>, Amsterdam (NL)\n")
        self.assertNotIn(" ,", flat)
        self.assertIn("(NL)", flat)

    def test_a_short_html_line_does_not_become_the_na_sentinel(self):
        # `ats._clean_description` returns "N/A" below ten characters. Without
        # the pad, a heading like this one is replaced by a shrug.
        flat, _notes = docx.flatten("<b>Skills</b>\n")
        self.assertEqual(flat.strip(), "Skills")

    def test_an_html_line_that_is_a_bullet_keeps_its_indent(self):
        flat, _notes = docx.flatten("  - <b>nested</b> point\n")
        self.assertTrue(flat.startswith("  - "), repr(flat))

    def test_a_comparison_operator_sentence_is_untouched(self):
        markdown = "Keeps p95 < 200ms and > 1k rps.\n"
        flat, notes = docx.flatten(markdown)
        self.assertEqual(flat, markdown)
        self.assertEqual(notes, [])

    def test_no_nul_padding_ever_reaches_the_output(self):
        flat, _notes = docx.flatten("<b>x</b>\n")
        self.assertNotIn("\x00", flat)


class TestFlattenOverARealMessyCV(unittest.TestCase):
    def setUp(self):
        self.flat, self.notes = docx.flatten(read_fixture(MESSY_CV))

    def test_the_phase_a_invariant_holds_on_flattened_output(self):
        blocks = docx.parse_blocks(self.flat)
        self.assertEqual(
            {b["kind"] for b in blocks}, {"heading", "paragraph", "bullet"}
        )

    def test_no_table_pipes_survive(self):
        self.assertNotIn("| Python |", self.flat)
        self.assertIn("Skill: Python — 8 — 2026", self.flat)

    def test_the_three_skill_rows_stay_three_blocks(self):
        rows = [
            b
            for b in docx.parse_blocks(self.flat)
            if b["text"].startswith("Skill: ")
        ]
        self.assertEqual(len(rows), 3)

    def test_the_literal_pipe_sentence_survives(self):
        self.assertIn("cat ledger | sort | uniq -c", self.flat)

    def test_the_comparison_sentence_keeps_both_operators(self):
        self.assertIn("< 200ms", self.flat)
        self.assertIn("> 1k rps", self.flat)

    def test_no_image_survives(self):
        self.assertNotIn("rin.png", self.flat)

    def test_flattening_leaves_nothing_for_the_linter_to_repair(self):
        repairable = [
            f
            for f in docx.ats_lint(self.flat)
            if f["reason"] in ("table", "image", "deep-nesting", "html")
        ]
        self.assertEqual(repairable, [])

    def test_notes_are_ordered_by_the_line_they_name(self):
        # Tables are found in a first pass over the whole file, so without
        # sorting the table note jumps ahead of notes about earlier lines.
        numbers = [int(note.split()[1].rstrip(":")) for note in self.notes]
        self.assertEqual(numbers, sorted(numbers))

    def test_every_note_names_a_line_number(self):
        self.assertTrue(self.notes)
        for note in self.notes:
            self.assertTrue(note.startswith("line "), note)

    def test_flatten_never_refuses(self):
        # Even markdown carrying every repairable construct at once returns
        # normally. Refusing is `ats_lint`'s job alone.
        flat, notes = docx.flatten(read_fixture(MESSY_CV) + "\nclaim [verifikasi]\n")
        self.assertTrue(flat)
        self.assertTrue(notes)

    def test_empty_and_none_input_flatten_to_empty(self):
        self.assertEqual(docx.flatten(""), ("", []))
        self.assertEqual(docx.flatten(None), ("", []))


class TestHtmlStrippingIsNotReimplemented(unittest.TestCase):
    def test_the_module_delegates_to_ats_clean_description(self):
        source = read_fixture(os.path.join(FIXTURES, "..", "..", "scripts", "docx.py"))
        self.assertIn("ats._clean_description", source)

    def test_there_is_no_second_tag_substitution_in_the_module(self):
        # A second stripper would drift from `ats`'s, and the two would
        # disagree about what an ATS sees.
        source = read_fixture(os.path.join(FIXTURES, "..", "..", "scripts", "docx.py"))
        self.assertNotIn("_TAG_RE.sub", source)
        self.assertNotIn("html.unescape", source)


THE_FIVE_PARTS = [
    "[Content_Types].xml",
    "_rels/.rels",
    "word/document.xml",
    "word/_rels/document.xml.rels",
    "word/styles.xml",
]


class DocxTempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ajob2-docx-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def out(self, name="cv.docx"):
        return os.path.join(self.tmp, name)

    def document_xml(self, path):
        with zipfile.ZipFile(path) as archive:
            return archive.read("word/document.xml").decode("utf-8")


class TestRenderWritesTheFiveParts(DocxTempDirCase):
    def test_the_archive_holds_exactly_the_five_parts(self):
        path = self.out()
        docx.render("# Ali\n", path)
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(sorted(archive.namelist()), sorted(THE_FIVE_PARTS))

    def test_the_archive_is_a_valid_zip(self):
        path = self.out()
        docx.render(read_fixture(TAILORED_CV), path)
        with zipfile.ZipFile(path) as archive:
            self.assertIsNone(archive.testzip())

    def test_document_xml_is_well_formed(self):
        path = self.out()
        docx.render(read_fixture(TAILORED_CV), path)
        # A well-formedness check the writer cannot fake by construction.
        ElementTree.fromstring(self.document_xml(path))

    def test_styles_xml_is_well_formed_and_carries_every_style_id(self):
        path = self.out()
        docx.render(read_fixture(TAILORED_CV), path)
        with zipfile.ZipFile(path) as archive:
            styles = archive.read("word/styles.xml").decode("utf-8")
        ElementTree.fromstring(styles)
        for style_id in ("Heading1", "Heading2", "Heading3", "Normal", "ListParagraph"):
            self.assertIn('w:styleId="%s"' % style_id, styles)

    def test_every_paragraph_preserves_whitespace(self):
        # Without xml:space="preserve" Word eats leading and trailing spaces
        # and two bullets can merge visually.
        path = self.out()
        docx.render(read_fixture(TAILORED_CV), path)
        body = self.document_xml(path)
        self.assertEqual(body.count("<w:t"), body.count('xml:space="preserve"'))

    def test_headings_carry_their_style_id(self):
        path = self.out()
        docx.render("# One\n\n## Two\n\n### Three\n", path)
        body = self.document_xml(path)
        for style_id in ("Heading1", "Heading2", "Heading3"):
            self.assertIn('w:pStyle w:val="%s"' % style_id, body)

    def test_a_bullet_carries_a_literal_glyph(self):
        # No numbering.xml exists, so the glyph is the bullet. It is also
        # plain text, which is what a resume parser reads most reliably.
        path = self.out()
        docx.render("- one\n", path)
        self.assertIn("\u2022 one", self.document_xml(path))

    def test_rendering_the_same_markdown_twice_produces_identical_bytes(self):
        first, second = self.out("a.docx"), self.out("b.docx")
        docx.render(read_fixture(TAILORED_CV), first)
        docx.render(read_fixture(TAILORED_CV), second)
        with open(first, "rb") as one, open(second, "rb") as two:
            self.assertEqual(one.read(), two.read())

    def test_the_result_reports_blocks_notes_and_bytes(self):
        path = self.out()
        result = docx.render(read_fixture(MESSY_CV), path)
        self.assertEqual(result["out"], path)
        self.assertGreater(result["blocks"], 0)
        self.assertGreater(result["bytes"], 0)
        self.assertTrue(result["notes"])


class TestRenderRefusals(DocxTempDirCase):
    def test_an_unverified_claim_refuses_and_writes_nothing(self):
        path = self.out()
        with self.assertRaises(docx.UnverifiedClaimError):
            docx.render("# CV\n\n- revenue up 40% [verifikasi]\n", path)
        self.assertFalse(os.path.exists(path))

    def test_allow_unverified_renders_the_same_markdown(self):
        path = self.out()
        docx.render(
            "# CV\n\n- revenue up 40% [verifikasi]\n", path, allow_unverified=True
        )
        self.assertTrue(os.path.exists(path))
        self.assertIn("[verifikasi]", self.document_xml(path))

    def test_the_refusal_names_the_source_label(self):
        path = self.out()
        with self.assertRaises(docx.UnverifiedClaimError) as caught:
            docx.render("- x [verifikasi]\n", path, source="cv.md")
        self.assertIn("cv.md:1", str(caught.exception))

    def test_the_refusal_falls_back_to_the_output_filename(self):
        path = self.out("tailored.docx")
        with self.assertRaises(docx.UnverifiedClaimError) as caught:
            docx.render("- x [verifikasi]\n", path)
        self.assertIn("tailored.docx:1", str(caught.exception))

    def test_empty_markdown_refuses(self):
        path = self.out()
        with self.assertRaises(docx.EmptyDocumentError):
            docx.render("", path)
        self.assertFalse(os.path.exists(path))

    def test_whitespace_only_markdown_refuses(self):
        path = self.out()
        with self.assertRaises(docx.EmptyDocumentError):
            docx.render("   \n\t\n", path)
        self.assertFalse(os.path.exists(path))

    def test_markdown_that_flattens_to_nothing_refuses(self):
        path = self.out()
        with self.assertRaises(docx.EmptyDocumentError):
            docx.render("![headshot](photo.png)\n", path)
        self.assertFalse(os.path.exists(path))

    def test_a_missing_destination_directory_is_a_named_refusal(self):
        path = os.path.join(self.tmp, "nope", "cv.docx")
        with self.assertRaises(docx.DestinationError):
            docx.render("# Ali\n", path)

    def test_an_unwritable_destination_directory_is_a_named_refusal(self):
        locked = os.path.join(self.tmp, "locked")
        os.mkdir(locked, 0o500)
        self.addCleanup(os.chmod, locked, 0o700)
        try:
            with self.assertRaises(docx.DestinationError):
                docx.render("# Ali\n", os.path.join(locked, "cv.docx"))
        except AssertionError:
            if os.geteuid() == 0:
                self.skipTest("running as root: directory permissions do not apply")
            raise

    def test_a_failed_render_leaves_no_temp_file_behind(self):
        path = os.path.join(self.tmp, "nope", "cv.docx")
        with self.assertRaises(docx.DestinationError):
            docx.render("# Ali\n", path)
        self.assertEqual(os.listdir(self.tmp), [])

    def test_every_refusal_is_a_docx_error(self):
        for cls in (
            docx.UnverifiedClaimError,
            docx.EmptyDocumentError,
            docx.DestinationError,
        ):
            self.assertTrue(issubclass(cls, docx.DocxError))


class TestRenderTextFidelity(DocxTempDirCase):
    def test_ampersand_and_angle_brackets_round_trip_exactly(self):
        # Proves the escaping order. Escaping "&" last would produce
        # "&amp;lt;" and the reader would see the entity on the page.
        path = self.out()
        docx.render("a & b < c\n", path)
        body = self.document_xml(path)
        self.assertIn("a &amp; b &lt; c", body)
        root = ElementTree.fromstring(body)
        texts = [
            node.text
            for node in root.iter(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
            )
        ]
        self.assertIn("a & b < c", texts)

    def test_a_literal_entity_in_the_source_is_not_unescaped(self):
        path = self.out()
        docx.render("AT&T and R&D\n", path)
        self.assertIn("AT&amp;T and R&amp;D", self.document_xml(path))

    def test_non_ascii_survives(self):
        path = self.out()
        docx.render("# Renée — 日本語 — Ångström\n", path)
        body = self.document_xml(path)
        for fragment in ("Renée", "—", "日本語", "Ångström"):
            self.assertIn(fragment, body)

    def test_a_single_heading_and_nothing_else_renders(self):
        path = self.out()
        result = docx.render("# Ali Sadikin\n", path)
        self.assertEqual(result["blocks"], 1)
        self.assertIn("Ali Sadikin", self.document_xml(path))

    def test_five_hundred_blocks_all_reach_the_document(self):
        path = self.out()
        markdown = "\n\n".join("para %d" % i for i in range(500))
        result = docx.render(markdown, path)
        self.assertEqual(result["blocks"], 500)
        self.assertEqual(self.document_xml(path).count("<w:p>"), 500)

    def test_no_markdown_syntax_reaches_the_document(self):
        path = self.out()
        docx.render(read_fixture(TAILORED_CV), path)
        root = ElementTree.fromstring(self.document_xml(path))
        text = " ".join(
            node.text or ""
            for node in root.iter(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
            )
        )
        for marker in ("**", "`", "## ", "](", "|---"):
            self.assertNotIn(marker, text)

    def test_a_control_character_never_reaches_the_xml(self):
        # XML 1.0 forbids them: one stray byte makes the file unopenable
        # rather than merely ugly.
        path = self.out()
        docx.render("# Ali\x07 Sadikin\n", path)
        body = self.document_xml(path)
        self.assertNotIn("\x07", body)
        ElementTree.fromstring(body)

    def test_the_messy_cv_renders_end_to_end(self):
        path = self.out()
        result = docx.render(read_fixture(MESSY_CV), path)
        with zipfile.ZipFile(path) as archive:
            self.assertIsNone(archive.testzip())
        ElementTree.fromstring(self.document_xml(path))
        self.assertGreater(result["blocks"], 10)


if __name__ == "__main__":
    unittest.main()

"""Tests for `scripts/docx.py` — markdown to an ATS-readable `.docx`.

`sys.path` is pointed at `scripts/` the same way every other test module in
this repository does it, which also makes the local `docx` module win over a
`python-docx` install if one ever appears on the machine. This project is
standard-library only, so shadowing is the intended outcome, not an accident.
"""

import contextlib
import io
import os
import re
import shutil
import sys
import tempfile
import unittest
import unicodedata
import unittest.mock
import xml.etree.ElementTree as ElementTree
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import ats  # noqa: E402
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

    def test_emphasis_is_not_stripped_inside_a_code_span(self):
        # A CV naming `__init__` means it literally, and markdown agrees:
        # emphasis does not apply inside a code span. Stripping everywhere
        # turned `__init__` into `init`.
        blocks = docx.parse_blocks("- ran `__init__` and `my_var` daily\n")
        self.assertEqual(blocks[0]["text"], "ran __init__ and my_var daily")

    def test_a_shell_pipeline_in_a_code_span_survives_intact(self):
        blocks = docx.parse_blocks("- shell: `cat a | sed -e *x*`\n")
        self.assertEqual(blocks[0]["text"], "shell: cat a | sed -e *x*")

    def test_underscore_emphasis_outside_a_code_span_is_stripped(self):
        blocks = docx.parse_blocks("- __Bold__ and _italic_ text\n")
        self.assertEqual(blocks[0]["text"], "Bold and italic text")

    def test_an_identifier_with_inner_underscores_is_left_alone(self):
        blocks = docx.parse_blocks("- maintained my_var_name across services\n")
        self.assertEqual(blocks[0]["text"], "maintained my_var_name across services")

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


class TestTheGateSurvivesLaterTransformations(unittest.TestCase):
    """Markers that reassemble themselves downstream of the check.

    Every one of these shipped a claim into a rendered CV while
    `unverified_findings` reported clean, because `strip_inline` and the html
    cleaner run AFTER the gate did. The gate now lints the projection of the
    line as it will finally read, so removing characters can only make a
    marker more visible, never less.
    """

    def test_emphasis_around_the_marker_does_not_hide_it(self):
        findings = docx.unverified_findings("- Grew ARR to $9M [**verifikasi**]\n")
        self.assertEqual([f["line"] for f in findings], [1])

    def test_a_code_span_around_the_marker_does_not_hide_it(self):
        self.assertEqual(len(docx.unverified_findings("- x [`verifikasi`]\n")), 1)

    def test_italics_around_the_marker_do_not_hide_it(self):
        self.assertEqual(len(docx.unverified_findings("- x [*verifikasi*]\n")), 1)

    def test_html_entities_spelling_the_brackets_do_not_hide_it(self):
        markdown = "- <b>Impact</b> revenue &#91;verifikasi&#93;\n"
        self.assertEqual(len(docx.unverified_findings(markdown)), 1)

    def test_double_escaped_entities_do_not_hide_it(self):
        # "&amp;#91;" decodes to "&#91;" and only then to "[". One pass would
        # leave the second spelling readable.
        markdown = "- <b>x</b> &amp;#91;verifikasi&amp;#93;\n"
        self.assertEqual(len(docx.unverified_findings(markdown)), 1)

    def test_tags_are_removed_with_no_separator(self):
        # The docstring calls this deliberate, and nothing pinned it: with
        # the tag replaced by a space instead, "[<i></i>verifikasi]" becomes
        # "[ verifikasi]" and the whole suite stayed green.
        self.assertEqual(
            docx._unmask("- x [verif<i>ikasi</i>]"), "- x [verifikasi]"
        )

    def test_a_tag_splitting_the_marker_does_not_hide_it(self):
        self.assertEqual(len(docx.unverified_findings("- x [verif<i>ikasi</i>]\n")), 1)

    def test_underscore_emphasis_around_the_marker_does_not_hide_it(self):
        # Found by probing the gate with fifteen spellings after the first
        # round of fixes. Models write `__bold__` at least as often as `**`.
        self.assertEqual(len(docx.unverified_findings("- x [__verifikasi__]\n")), 1)
        self.assertEqual(len(docx.unverified_findings("- x [_verifikasi_]\n")), 1)

    def test_a_zero_width_character_inside_the_marker_does_not_hide_it(self):
        # Renders as nothing, so it reads to a human as the marker while
        # matching no pattern at all.
        self.assertEqual(
            len(docx.unverified_findings("- x [verifi\u200bkasi]\n")), 1
        )

    def test_a_bidi_control_character_does_not_hide_it(self):
        self.assertEqual(
            len(docx.unverified_findings("- x [verifikasi\u202e]\n")), 1
        )

    def test_a_marker_inside_a_table_cell_does_not_hide_it(self):
        markdown = "| Skill | Note |\n|---|---|\n| Python | grew 40% [verifikasi] |\n"
        self.assertEqual(len(docx.unverified_findings(markdown)), 1)

    def test_every_character_the_writer_deletes_is_invisible_to_the_gate(self):
        """The structural guard. Two character sets drifted, and the gap was
        a hole through both layers.

        `escape` deletes XML-illegal control characters, and it runs AFTER
        the last check, so "[veri\\x01fikasi]" matched nothing, the writer
        removed the \\x01, and a clean "[verifikasi]" appeared in the shipped
        document. Every character the writer removes must already be gone
        from the text the gate reads.
        """
        missed = [
            hex(code)
            for code in range(0x11000)
            if docx._ILLEGAL_XML_RE.match(chr(code))
            and docx._remove_invisible(chr(code)) != ""
        ]
        self.assertEqual(missed, [])

    # Unicode's Default_Ignorable_Code_Point ranges, transcribed from the
    # UCD. This list is the ORACLE: it comes from the standard, not from
    # `docx._INVISIBLE_CATEGORIES`, so it can disagree with the code.
    #
    # The test it replaced swept the codepoints whose category the code
    # itself removes, which is the implementation's predicate restated. It
    # passed while 267 named codepoints put a live marker into a document:
    # widening the code could not fail it, and narrowing the code was the
    # only thing it could see. A guard that takes its oracle from the code it
    # guards cannot tell you the code's definition is too small.
    DEFAULT_IGNORABLE = (
        (0x00AD, 0x00AD),
        (0x034F, 0x034F),
        (0x061C, 0x061C),
        (0x115F, 0x1160),
        (0x17B4, 0x17B5),
        (0x180B, 0x180F),
        (0x200B, 0x200F),
        (0x202A, 0x202E),
        (0x2060, 0x206F),
        (0x3164, 0x3164),
        (0xFE00, 0xFE0F),
        (0xFEFF, 0xFEFF),
        (0xFFA0, 0xFFA0),
        (0xFFF0, 0xFFF8),
        (0x13430, 0x1343F),
        (0x1BCA0, 0x1BCA3),
        (0x1D173, 0x1D17A),
        (0xE0000, 0xE0FFF),
    )

    def test_no_default_ignorable_codepoint_can_hide_inside_the_marker(self):
        missed = [
            hex(code)
            for first, last in self.DEFAULT_IGNORABLE
            for code in range(first, last + 1)
            if not docx.unverified_findings("- ARR [veri%sfikasi]" % chr(code))
        ]
        self.assertEqual(missed, [])

    def test_the_variation_selectors_are_caught(self):
        # Named separately because three documents once claimed these were
        # covered while all sixteen shipped a readable marker. They are
        # category Mn, which the old Cc/Cf definition never looked at.
        for code in list(range(0xFE00, 0xFE10)) + [0xE0100, 0xE01EF]:
            with self.subTest(code=hex(code)):
                markdown = "- ARR [veri%sfikasi]\n" % chr(code)
                self.assertEqual(len(docx.unverified_findings(markdown)), 1)

    def test_a_combining_mark_that_composes_into_a_letter_does_not_hide_it(self):
        """NFKC does not only decompose — it composes, and composition hides.

        "i" plus U+0301 becomes "í", a letter, and the mark is gone before
        anything can strip it. The docstring claimed a transformation that
        removes characters can only make a marker MORE visible; NFKC is not
        such a transformation. Marks are now removed before normalising too.
        """
        for mark in ("\u0300", "\u0301", "\u0308", "\u0323", "\u0340", "\u0341"):
            with self.subTest(mark=repr(mark)):
                markdown = "- ARR [ver i%sfikasi]\n".replace(" ", "")  % mark
                self.assertEqual(len(docx.unverified_findings(markdown)), 1)

    def test_an_enclosing_mark_does_not_hide_it(self):
        # U+20DD rings a letter, and Calibri has no glyph for it at all.
        self.assertEqual(
            len(docx.unverified_findings("- ARR [veri\u20ddfikasi]\n")), 1
        )

    def test_a_space_that_is_not_a_space_does_not_hide_it(self):
        # NFKC folds all of these to U+0020, so each lands where a plain
        # space lands. U+200A is about half a point wide in Calibri.
        for space in ("\u00a0", "\u2000", "\u200a", "\u202f", "\u205f", "\u3000"):
            with self.subTest(space=repr(space)):
                markdown = "- ARR [%sverifikasi]\n" % space
                self.assertEqual(len(docx.unverified_findings(markdown)), 1)

    def test_the_hangul_fillers_are_caught(self):
        for code in (0x115F, 0x1160, 0x3164, 0xFFA0):
            with self.subTest(code=hex(code)):
                markdown = "- ARR [veri%sfikasi]\n" % chr(code)
                self.assertEqual(len(docx.unverified_findings(markdown)), 1)

    def test_a_combining_accent_still_reaches_the_document(self):
        # The projection removes marks; the document must not. A CV writing
        # "e" plus a combining acute has to print "é".
        blocks = docx.parse_blocks("- Rene\u0301e shipped the migration\n")
        self.assertEqual(blocks[0]["text"], "Rene\u0301e shipped the migration")

    def test_an_invisible_codepoint_outside_the_bmp_is_caught_too(self):
        for code in (0xE0001, 0xE0020, 0x1D173):
            with self.subTest(code=hex(code)):
                markdown = "- ARR [veri%sfikasi]\n" % chr(code)
                self.assertEqual(len(docx.unverified_findings(markdown)), 1)

    def test_a_control_character_inside_the_marker_does_not_hide_it(self):
        for code in ("\x01", "\x02", "\x1f", "\x7f"):
            with self.subTest(code=repr(code)):
                markdown = "- ARR [veri%sfikasi]\n" % code
                self.assertEqual(len(docx.unverified_findings(markdown)), 1)

    def test_a_soft_hyphen_inside_the_marker_does_not_hide_it(self):
        # Invisible in Word, so the line reads as the marker on the page.
        self.assertEqual(
            len(docx.unverified_findings("- ARR [veri\u00adfikasi]\n")), 1
        )

    def test_fullwidth_forms_of_the_marker_do_not_hide_it(self):
        # NFKC folds these; they are indistinguishable from the marker.
        self.assertEqual(
            len(docx.unverified_findings("- ARR \uff3bverifikasi\uff3d\n")), 1
        )
        self.assertEqual(
            len(docx.unverified_findings("- ARR [\uff56erifikasi]\n")), 1
        )

    def test_a_marker_split_by_a_line_wrap_does_not_hide_it(self):
        """The continuation rule joins a wrapped line with a space.

        `- ARR [veri\\n  fikasi]` became the single block "ARR [veri fikasi]"
        — the claim shipped, with the marker broken only by a space that the
        gate had never seen, because the gate read two separate lines.
        """
        markdown = "# CV\n\n- ARR [veri\n  fikasi]\n"
        self.assertEqual(len(docx.unverified_findings(markdown)), 0)
        # Not caught per line, by construction — caught once the blocks are
        # the text that will actually be written.
        path = os.path.join(tempfile.mkdtemp(), "cv.docx")
        with self.assertRaises(docx.UnverifiedClaimError):
            with contextlib.redirect_stderr(io.StringIO()):
                docx.render(markdown, path)
        self.assertFalse(os.path.exists(path))

    def test_a_tag_holding_spaces_does_not_split_the_marker_past_the_gate(self):
        # "[veri<span>  </span>fikasi]" — the html cleaner collapses the tag
        # and its spaces to one space, after the gate ran.
        self.assertEqual(
            len(docx.unverified_findings("- ARR [veri<span>  </span>fikasi]\n")), 1
        )

    def test_a_marker_spelled_out_letter_by_letter_is_caught(self):
        self.assertEqual(len(docx.unverified_findings("- ARR [v e r i f i k a s i]\n")), 1)

    def test_a_marker_split_by_a_wrap_after_the_bracket_is_caught(self):
        """The pure-ASCII leak. No invisible characters, no attack.

        The author types "[Assumption: FY24 baseline]". The line wraps after
        the bracket, `parse_blocks` joins the continuation with a space, and
        what reaches the page is "[ Assumption: FY24 baseline]".
        """
        markdown = "# CV\n\nCut spend 35% [\nAssumption: FY24 baseline]\n"
        path = os.path.join(tempfile.mkdtemp(), "cv.docx")
        with self.assertRaises(docx.UnverifiedClaimError):
            with contextlib.redirect_stderr(io.StringIO()):
                docx.render(markdown, path)
        self.assertFalse(os.path.exists(path))

    def test_a_bullet_wrapped_after_the_bracket_is_caught_too(self):
        markdown = "# CV\n\n- Grew ARR to $9M\n  [\n  verifikasi]\n"
        path = os.path.join(tempfile.mkdtemp(), "cv.docx")
        with self.assertRaises(docx.UnverifiedClaimError):
            with contextlib.redirect_stderr(io.StringIO()):
                docx.render(markdown, path)
        self.assertFalse(os.path.exists(path))

    def test_the_loose_pattern_does_not_fire_on_ordinary_bracketed_prose(self):
        # Measured before widening the pattern, not assumed: allowing a space
        # after "[" added no new false positive over this corpus.
        for line in (
            "- delivered [very informal kasi] sessions",
            "- ran [a verification step] daily",
            "- shipped [v2] of the API",
            "- see [notes] for the full figure",
            "- reviewed [ a verification process ] quarterly",
            "- cited [Smith 2024] in the paper",
            "- built [ the assumption engine ] for pricing",
            "- measured p95 [ < 200ms ] under load",
            "- tagged releases [ v1.2.3 ]",
        ):
            with self.subTest(line=line):
                self.assertEqual(docx.unverified_findings(line + "\n"), [])

    def test_a_homoglyph_is_a_known_and_stated_limit(self):
        # Cyrillic "а" for Latin "a". Closing this needs a confusables table,
        # which is not in the standard library, and it is not something
        # anybody writes by accident. Pinned so the limit is a decision on
        # record rather than a surprise.
        self.assertEqual(docx.unverified_findings("- x [verifik\u0430si]\n"), [])

    def test_the_finding_still_names_the_original_line_and_text(self):
        # The projection is for detection only. What the author is shown must
        # be the line they wrote, at the number they wrote it on.
        markdown = "# CV\n\n- Grew ARR [**verifikasi**]\n"
        finding = docx.unverified_findings(markdown)[0]
        self.assertEqual(finding["line"], 3)
        self.assertEqual(finding["text"], "- Grew ARR [**verifikasi**]")

    def test_an_assumption_marker_carrying_a_reason_is_matched(self):
        # "[Assumption: figure from memory]" is far likelier to be written
        # than the bare marker, and it is the outward document being linted.
        markdown = "- Grew ARR to $9M [Assumption: figure from memory]\n"
        self.assertEqual(len(docx.unverified_findings(markdown)), 1)

    def test_a_verifikasi_marker_carrying_a_note_is_matched(self):
        self.assertEqual(
            len(docx.unverified_findings("- x [verifikasi nanti]\n")), 1
        )

    def test_a_bracketed_word_that_is_not_a_marker_is_still_not_matched(self):
        self.assertEqual(docx.unverified_findings("- shipped [v2] of the API\n"), [])


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

    def test_inner_spaces_are_a_match_since_a_wrap_can_create_them(self):
        # This assertion used to be its inverse. The convention was treated
        # as exact until a line wrapped right after "[" produced
        # "[ Assumption: FY24 baseline]" — the space put there by the wrap,
        # not by the author — and the marker shipped. Owner decision,
        # 2026-09-19; plan Phase B amended to match.
        self.assertEqual(len(docx.unverified_findings("x [ Assumption ]\n")), 1)

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
        self.assertIn("Skill: Python — Years: 8", flat)

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

    def test_an_empty_first_cell_does_not_steal_the_next_cell_label(self):
        # "Skill: 5" would have the CV assert that "5" is a skill. The label
        # is the header of the first cell that actually holds something.
        flat, _notes = docx.flatten("| Skill | Years |\n|---|---|\n|  | 5 |\n")
        self.assertIn("Years: 5", flat)
        self.assertNotIn("Skill: 5", flat)

    def test_a_filled_first_cell_still_uses_the_first_header(self):
        flat, _notes = docx.flatten("| Skill | Years |\n|---|---|\n| Python | 8 |\n")
        self.assertIn("Skill: Python — Years: 8", flat)

    def test_every_cell_keeps_its_own_header(self):
        # Labelling only the first cell left "Skill: Python — 8 — 2026", so
        # an ATS read two numbers with nothing saying what they measured.
        flat, _notes = docx.flatten(
            "| Skill | Years | Last used |\n|---|---|---|\n| Python | 8 | 2026 |\n"
        )
        self.assertIn("Skill: Python — Years: 8 — Last used: 2026", flat)

    def test_a_row_with_more_cells_than_headers_keeps_them_all(self):
        # The header padding is what stops `zip` truncating at the headers.
        # Removing it left the suite green while "extra" vanished from the
        # document — the docstring only ever mentioned SHORT rows.
        flat, _notes = docx.flatten(
            "| Skill | Years |\n|---|---|\n| Rust | 3 | 2022 | extra |\n"
        )
        self.assertIn("extra", flat)
        self.assertIn("2022", flat)

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

    def test_a_gfm_separator_with_one_dash_is_a_table(self):
        """GFM requires one dash per cell; this demanded three.

        `| :-: |` — the ordinary way to centre a column, and what a model
        writes — was not a table at all: `find_tables` skipped it, `flatten`
        never touched it, and every row collapsed into one paragraph with
        the raw pipes still in it. The fix shipped without this test.
        """
        for separator in ("| :-: | ---: |", "|--|--|", "| - | - |", "|-|-|"):
            with self.subTest(separator=separator):
                markdown = "| Skill | Years |\n%s\n| Python | 8 |\n" % separator
                flat, notes = docx.flatten(markdown)
                self.assertNotIn("|", flat, separator)
                self.assertIn("Skill: Python", flat)
                self.assertTrue(notes, "a table was flattened with no note")

    def test_a_horizontal_rule_is_still_not_a_table_separator(self):
        # The looser pattern also matches a bare "---", which is a rule and,
        # under a line holding a pipe, a setext underline. The pipe
        # requirement on the separator line is what keeps them apart.
        flat, notes = docx.flatten("Ran `a | b` daily\n---\nNext section\n")
        self.assertEqual(notes, [])
        self.assertIn("a | b", flat)

    def test_an_escaped_pipe_stays_inside_its_cell(self):
        """Splitting on it made two cells and put " — " inside a sentence.

        The cell "used `a \\| b` pipelines" became "used `a \\" and "b
        pipelines", the second unlabelled, with the cell joiner sitting in
        the middle of the candidate's own words.
        """
        markdown = (
            "| Tool | Notes |\n| --- | --- |\n"
            "| awk | used `a \\| b` pipelines |\n"
        )
        flat, _notes = docx.flatten(markdown)
        self.assertIn("used `a | b` pipelines", flat)
        self.assertNotIn("\\", flat)

    def test_an_escaped_pipe_at_the_end_of_a_row_is_not_an_outer_pipe(self):
        markdown = "| Expr |\n| --- |\n| a \\| |\n"
        flat, _notes = docx.flatten(markdown)
        self.assertIn("Expr: a |", flat)

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

    def test_a_reference_style_link_is_resolved_from_its_definition(self):
        markdown = "Spoke at [PyCon][pycon] once\n\n[pycon]: https://pycon.org\n"
        flat, notes = docx.flatten(markdown)
        self.assertIn("PyCon (https://pycon.org)", flat)
        self.assertNotIn("[pycon]", flat)
        self.assertTrue(any("resolved" in note for note in notes))

    def test_a_reference_link_with_no_definition_keeps_its_text(self):
        # Printing "[PyCon][pycon-ref]" on the page helps nobody. The text
        # survives, the brackets do not, and the note says the url was lost.
        flat, notes = docx.flatten("Spoke at [PyCon][pycon-ref] once\n")
        self.assertEqual(flat.strip(), "Spoke at PyCon once")
        self.assertTrue(any("no definition" in note for note in notes))

    def test_a_reference_definition_is_dropped_and_its_url_noted(self):
        flat, notes = docx.flatten("text\n\n[1]: https://example.com/report\n")
        self.assertNotIn("https://example.com/report", flat)
        self.assertTrue(
            any("https://example.com/report" in note for note in notes)
        )

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

    def test_the_note_names_the_tags_it_removed(self):
        # "<team lead>" is indistinguishable from a tag and is deleted. The
        # operator has to be able to see that the sentence lost those words.
        _flat, notes = docx.flatten("Acted as <team lead> for the group\n")
        self.assertTrue(any("<team lead>" in note for note in notes), notes)

    def test_a_short_html_line_does_not_become_the_na_sentinel(self):
        # `ats._clean_description` returns "N/A" below ten characters. Without
        # the pad, a heading like this one is replaced by a shrug.
        flat, _notes = docx.flatten("<b>Skills</b>\n")
        self.assertEqual(flat.strip(), "Skills")

    def test_an_html_line_that_is_a_bullet_keeps_its_indent(self):
        flat, _notes = docx.flatten("  - <b>nested</b> point\n")
        self.assertTrue(flat.startswith("  - "), repr(flat))

    def test_an_entity_spelled_comparison_next_to_a_tag_survives(self):
        """The candidate's own numbers, deleted, with the note saying tags.

        `ats._clean_description` unescapes to a fixed point and only THEN
        strips tags, so `&lt;` became a raw `<` after the sentinels had gone
        in, and `<[^>]+>` ate the rest of the sentence. "kept spend &lt; $2M
        while headcount &gt; 40" reached the page as "kept spend 40" — a CV
        asserting something its author never wrote.
        """
        cases = {
            "<b>Budget</b>: kept spend &lt; $2M while headcount &gt; 40.":
                "Budget: kept spend < $2M while headcount > 40.",
            "Kept p95 <b>&lt; 200ms</b> and 1k rps.":
                "Kept p95 < 200ms and 1k rps.",
            "<b>Scale</b>: served &lt;1M&gt; daily active users.":
                "Scale: served <1M> daily active users.",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                flat, _notes = docx.flatten(source + "\n")
                self.assertEqual(flat.strip(), expected)

    def test_entities_are_decoded_even_with_no_tag_on_the_line(self):
        # Whether "AT&amp;T" printed correctly used to depend on whether an
        # unrelated <b> happened to sit on the same line.
        flat, notes = docx.flatten("Worked at AT&amp;T on R&amp;D.\n")
        self.assertEqual(flat.strip(), "Worked at AT&T on R&D.")
        self.assertTrue(any("entities decoded" in note for note in notes))

    def test_decoding_entities_is_reported_on_stderr_per_spec_five(self):
        # Spec 5: everything outside the subset is flattened or dropped
        # WITH a line on stderr. A silent rewrite breaks that contract.
        _flat, notes = docx.flatten("Kept p95 &lt; 200ms.\n")
        self.assertTrue(notes, "an entity was decoded with no note")

    def test_a_line_with_neither_tag_nor_entity_is_left_exactly_alone(self):
        source = "Keeps p95 < 200ms and > 1k rps.\n"
        flat, notes = docx.flatten(source)
        self.assertEqual(flat, source)
        self.assertEqual(notes, [])

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
        self.assertIn("Skill: Python — Years: 8 — Last used: 2026", self.flat)

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
    """Behavioural, not textual.

    The first version of this guard asserted the literal token `_TAG_RE.sub`
    was absent from the module source. A real second stripper — a fresh
    `re.compile(r"<[^>]+>")` under any other name — left the whole suite
    green. That is this repository's documented recurring defect: a guard
    that checks a spelling instead of the property it claims to enforce.

    These replace it by making the delegation observable. If the module ever
    stops routing html through `ats._clean_description`, the substituted
    function's output stops appearing in the result, and these fail.
    """

    def test_flatten_routes_html_through_ats_clean_description(self):
        marker = "SENTINEL-FROM-THE-SUBSTITUTE" + "x" * 10

        def substitute(raw):
            return marker

        with unittest.mock.patch.object(ats, "_clean_description", substitute):
            flat, _notes = docx.flatten("<b>Skills</b>\n")
        self.assertIn(marker, flat)

    def test_strip_html_routes_through_ats_clean_description(self):
        seen = []
        original = ats._clean_description

        def spy(raw):
            seen.append(raw)
            return original(raw)

        with unittest.mock.patch.object(ats, "_clean_description", spy):
            docx.strip_html("<b>Product engineer</b>, Amsterdam")
        self.assertTrue(seen, "strip_html never called ats._clean_description")

    def test_a_line_without_html_is_not_sent_through_the_cleaner_at_all(self):
        # Delegating is right; delegating a line that has no tag is not. The
        # cleaner collapses whitespace and unescapes entities, and an
        # ordinary CV line should reach the document exactly as written.
        seen = []
        original = ats._clean_description

        def spy(raw):
            seen.append(raw)
            return original(raw)

        with unittest.mock.patch.object(ats, "_clean_description", spy):
            docx.flatten("Keeps p95 < 200ms and > 1k rps.\n")
        self.assertEqual(seen, [])


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
        # `render` writes one observability line to stderr on success. Left
        # uncaptured it litters the suite's own output, which is the wart
        # `ats.fetch`'s bare prints left behind before AJOB-1 removed them.
        self.stderr = io.StringIO()
        redirect = contextlib.redirect_stderr(self.stderr)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

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

    def test_page_margins_carry_every_attribute_the_schema_requires(self):
        """`CT_PageMar` declares all seven `use="required"`.

        Emitting only the four margins made every rendered document — and the
        committed eval sample, the artefact the manual open-check exists to
        exercise — fail ISO/IEC 29500 validation. Asserted by attribute name
        so the check needs no vendored schema.
        """
        path = self.out()
        docx.render("# Ali\n", path)
        margins = re.search(r"<w:pgMar[^>]*/>", self.document_xml(path))
        self.assertIsNotNone(margins, "no w:pgMar in the document")
        self.assertEqual(
            sorted(re.findall(r"w:(\w+)=", margins.group(0))),
            ["bottom", "footer", "gutter", "header", "left", "right", "top"],
        )

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

    def test_the_observability_line_names_blocks_notes_and_bytes(self):
        path = self.out()
        result = docx.render(read_fixture(MESSY_CV), path)
        self.assertIn(
            "docx.render: blocks=%d notes=%d bytes=%d"
            % (result["blocks"], len(result["notes"]), result["bytes"]),
            self.stderr.getvalue(),
        )

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

    def test_allow_unverified_renders_but_strips_the_marker(self):
        # The override is a decision to send the claim, never a decision to
        # print the word "[verifikasi]" on a page an employer reads.
        path = self.out()
        result = docx.render(
            "# CV\n\n- revenue up 40% [verifikasi]\n", path, allow_unverified=True
        )
        self.assertTrue(os.path.exists(path))
        body = self.document_xml(path)
        self.assertNotIn("[verifikasi]", body)
        self.assertIn("revenue up 40%", body)
        self.assertTrue(
            any("marker(s) removed" in note for note in result["notes"]),
            result["notes"],
        )

    def test_the_marker_removal_leaves_no_double_space_or_floating_comma(self):
        path = self.out()
        docx.render(
            "# CV\n\n- Grew ARR [verifikasi], then doubled it\n",
            path,
            allow_unverified=True,
        )
        body = self.document_xml(path)
        self.assertIn("Grew ARR, then doubled it", body)

    def test_the_override_strips_every_spelling_the_gate_catches(self):
        """Substituting on the raw text covered only the literal spellings.

        A marker written as html entities survived the strip, printed
        "verifikasi" onto the page, and reported nothing in `notes` — the
        override went silent, which is the one thing it promised not to do.
        """
        spellings = {
            "bare": "- Grew ARR [verifikasi]",
            "bold": "- Grew ARR [**verifikasi**]",
            "underscore": "- Grew ARR [__verifikasi__]",
            "code span": "- Grew ARR [`verifikasi`]",
            "with reason": "- Grew ARR [Assumption: from memory]",
            "entities": "- Grew ARR &#91;verifikasi&#93;",
            "double entities": "- Grew ARR &amp;#91;verifikasi&amp;#93;",
            "hex entity": "- Grew ARR &#x5B;verifikasi&#x5D;",
            "control char": "- Grew ARR [veri\x01fikasi]",
            "zero width": "- Grew ARR [veri\u200bfikasi]",
            "fullwidth": "- Grew ARR \uff3bverifikasi\uff3d",
        }
        for name, line in spellings.items():
            with self.subTest(spelling=name):
                path = self.out("%s.docx" % name.replace(" ", "-"))
                result = docx.render(
                    "# CV\n\n%s\n" % line, path, allow_unverified=True
                )
                body = self.document_xml(path)
                self.assertNotIn("verifikasi", body.lower(), name)
                self.assertNotIn("assumption", body.lower(), name)
                self.assertIn("Grew ARR", body, name)
                self.assertTrue(
                    any("marker(s) removed" in note for note in result["notes"]),
                    "%s: the override was silent" % name,
                )

    def test_a_bullet_that_held_only_a_marker_does_not_leave_an_orphan(self):
        # The strip empties the block, and an empty ListParagraph renders as
        # a lone bullet glyph with nothing beside it.
        path = self.out()
        result = docx.render(
            "# CV\n\n- [verifikasi]\n- Grew ARR to $9M\n",
            path,
            allow_unverified=True,
        )
        texts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", self.document_xml(path))
        self.assertEqual(texts, ["CV", "\u2022 Grew ARR to $9M"])
        self.assertTrue(
            any("nothing but a marker" in note for note in result["notes"])
        )

    def test_a_document_of_nothing_but_markers_refuses(self):
        # The emptiness check runs after the strip, so this cannot write a
        # blank page under the override.
        path = self.out()
        with self.assertRaises(docx.EmptyDocumentError):
            docx.render("- [verifikasi]\n", path, allow_unverified=True)
        self.assertFalse(os.path.exists(path))

    def test_an_override_that_removed_nothing_adds_no_note(self):
        path = self.out()
        result = docx.render("# CV\n\n- clean claim\n", path, allow_unverified=True)
        self.assertEqual(result["notes"], [])

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
        # The destination must fail at `os.replace`, not before it. Pointing
        # at a missing directory made this test vacuous: `render` refused at
        # the `isdir` check, no temp file was ever created, and deleting
        # either `_remove_quietly` call left the whole suite green. A
        # directory sitting at the --out path gets all the way into
        # `_write_archive` and fails on the rename.
        path = os.path.join(self.tmp, "cv.docx")
        os.mkdir(path)
        with self.assertRaises(docx.DestinationError):
            docx.render("# Ali\n", path)
        leftovers = [name for name in os.listdir(self.tmp) if name != "cv.docx"]
        self.assertEqual(leftovers, [], "a .docx.tmp was left behind")

    def test_a_render_that_fails_at_the_rename_leaves_the_destination_alone(self):
        path = os.path.join(self.tmp, "cv.docx")
        os.mkdir(path)
        with self.assertRaises(docx.DestinationError):
            docx.render("# Ali\n", path)
        self.assertTrue(os.path.isdir(path))

    def test_a_line_breaking_character_is_caught_when_the_blocks_rejoin(self):
        """`splitlines` breaks on more than \\n.

        A vertical tab, a form feed, a file separator or U+0085 inside the
        marker puts it in two pieces before any line exists, so no per-line
        check can see it. `render` joins the rendered blocks with no
        separator as well as with newlines, which puts it back together.
        """
        for code in (0x0A, 0x0B, 0x0C, 0x0D, 0x1C, 0x1D, 0x1E, 0x85):
            with self.subTest(code=hex(code)):
                path = self.out("break-%x.docx" % code)
                markdown = "# CV\n\n- ARR [veri%sfikasi]\n" % chr(code)
                with self.assertRaises(docx.UnverifiedClaimError):
                    docx.render(markdown, path)
                self.assertFalse(os.path.exists(path))

    def test_ordinary_adjacent_blocks_do_not_raise_a_false_alarm(self):
        # The no-separator join is only safe because it takes one block
        # ending mid-marker and the next beginning mid-marker to fool it.
        path = self.out()
        docx.render(read_fixture(TAILORED_CV), path)
        self.assertTrue(os.path.exists(path))

    def test_the_second_gate_holds_when_the_first_one_is_blinded(self):
        """The belt, tested without the braces.

        `_unmask` catches every bypass known today, which makes the final
        pass over the rendered text unfalsifiable by ordinary input — delete
        it and the suite stays green. So blind the first layer deliberately
        and check the second still refuses. Without this, the defence in
        depth is one refactor from being deleted as dead code.
        """
        path = self.out()
        with unittest.mock.patch.object(docx, "_unmask", lambda line: line):
            with self.assertRaises(docx.UnverifiedClaimError) as caught:
                docx.render("# CV\n\n- Grew ARR [**verifikasi**]\n", path)
        self.assertIn("survived into the rendered text", str(caught.exception))
        self.assertFalse(os.path.exists(path))

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
        # The messy fixture, not the clean one: `](` and `|---` never appear
        # in tailored_cv.md, so two of these five assertions could not fail
        # against it.
        path = self.out()
        docx.render(read_fixture(MESSY_CV), path)
        root = ElementTree.fromstring(self.document_xml(path))
        text = " ".join(
            node.text or ""
            for node in root.iter(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
            )
        )
        for marker in ("**", "`", "## ", "](", "|---"):
            self.assertNotIn(marker, text)

    def test_no_codepoint_can_make_the_document_unparseable(self):
        """The direction nothing pinned.

        The subset test protects the GATE: everything the writer deletes is
        already gone from what the gate reads. XML validity needs the other
        direction — everything XML forbids must be deleted — and nothing
        checked it. A single U+FFFF in ordinary CV text produced a file no
        parser could open, and `render-docx` reported success with a
        plausible byte count.
        """
        forbidden = (
            "\x00", "\x08", "\x0b", "\x0c", "\x1f",
            "\ufffe", "\uffff",
        )
        for ch in forbidden:
            with self.subTest(ch=repr(ch)):
                path = self.out("x%x.docx" % ord(ch))
                docx.render("# CV\n\n- Grew ARR to $9M%s in 18 months\n" % ch, path)
                ElementTree.fromstring(self.document_xml(path))

    def test_a_noncharacter_that_xml_permits_still_round_trips(self):
        # U+FDD0 is a noncharacter but legal in XML content. Deleting it
        # would be over-reach; keeping it must not break the parse.
        path = self.out()
        docx.render("# CV\n\n- Grew ARR\ufdd0 sharply\n", path)
        ElementTree.fromstring(self.document_xml(path))

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



class TestEverySupportedConstructIsReportedPerSpecFive(unittest.TestCase):
    """Spec 5: anything outside the subset is flattened or dropped WITH a
    line on stderr.

    Eleven constructs were transformed with an empty `notes` list, while
    `skills/tailor/SKILL.md` told the model to report what changed. Four of
    them destroyed content in ordinary CVs; the rest printed raw markdown
    onto the page, which also fails the Phase F eval's "no markdown syntax
    is visible".
    """

    CONSTRUCTS = {
        "ordered list": "1. Cut p95 latency.\n2. Led migration.\n",
        "plus bullet": "+ Shipped billing v2\n",
        "setext h1": "Ali Sadikin\n===========\n",
        "setext h2": "Experience\n----------\n",
        "blockquote": "> Ali rebuilt our billing pipeline.\n",
        "fenced code": "```python\ndef solve(x):\n    return x\n```\n",
        "indented code": "Ran it:\n\n    def solve(x):\n\nNext.\n",
        "task list": "- [x] Shipped billing v2\n",
        "footnote definition": "[^1]: Source: internal dashboard\n",
        "reference definition": "text\n\n[1]: https://example.com\n",
        "bracketed link text": "See [ref [1]](https://example.com)\n",
    }

    def rendered_text(self, markdown):
        flat, notes = docx.flatten(markdown)
        blocks = docx.parse_blocks(flat)
        return " ".join(b["text"] for b in blocks), notes

    def test_no_construct_leaves_raw_markdown_in_the_document(self):
        leaks = ("```", "[^", "](", "|---", "[x]", "[ ]", "===")
        for name, markdown in self.CONSTRUCTS.items():
            with self.subTest(construct=name):
                text, _notes = self.rendered_text(markdown)
                for leak in leaks:
                    self.assertNotIn(leak, text, "%s leaked %r" % (name, leak))
                self.assertFalse(
                    text.lstrip().startswith(">"), "%s leaked a quote marker" % name
                )

    def test_every_construct_that_changes_is_reported(self):
        # The four that are handled entirely inside `parse_blocks` change
        # block STRUCTURE rather than text, and are covered by the
        # structural tests below; the rest must each produce a note.
        noted = (
            "blockquote",
            "fenced code",
            "indented code",
            "footnote definition",
            "reference definition",
        )
        for name in noted:
            with self.subTest(construct=name):
                _text, notes = self.rendered_text(self.CONSTRUCTS[name])
                self.assertTrue(notes, "%s was transformed silently" % name)

    def test_an_ordered_list_is_one_block_per_item_with_its_number(self):
        blocks = docx.parse_blocks(
            docx.flatten("1. Cut p95 latency.\n2. Led migration.\n3. Mentored 6.\n")[0]
        )
        self.assertEqual(len(blocks), 3)
        self.assertEqual(blocks[0]["text"], "1. Cut p95 latency.")
        self.assertEqual(blocks[2]["text"], "3. Mentored 6.")

    def test_a_setext_underline_becomes_a_heading_not_a_suffix(self):
        blocks = docx.parse_blocks(docx.flatten("Ali Sadikin\n===========\n")[0])
        self.assertEqual(
            blocks, [{"kind": "heading", "level": 1, "text": "Ali Sadikin"}]
        )

    def test_a_dashed_setext_underline_keeps_the_heading(self):
        blocks = docx.parse_blocks(docx.flatten("Experience\n----------\n")[0])
        self.assertEqual(
            blocks, [{"kind": "heading", "level": 2, "text": "Experience"}]
        )

    def test_a_rule_with_nothing_above_it_is_still_a_rule(self):
        blocks = docx.parse_blocks(docx.flatten("before\n\n---\n\nafter\n")[0])
        self.assertEqual([b["kind"] for b in blocks], ["paragraph", "paragraph"])

    def test_a_task_checkbox_does_not_print(self):
        blocks = docx.parse_blocks(
            docx.flatten("- [x] Shipped v2\n- [ ] Migrate v3\n")[0]
        )
        self.assertEqual(
            [b["text"] for b in blocks], ["Shipped v2", "Migrate v3"]
        )

    def test_a_plus_marker_is_a_bullet(self):
        blocks = docx.parse_blocks(docx.flatten("+ Shipped billing v2\n")[0])
        self.assertEqual(blocks, [{"kind": "bullet", "text": "Shipped billing v2"}])

    def test_fenced_code_keeps_its_lines_apart(self):
        flat, _notes = docx.flatten("```\ndef solve(x):\n    return x\n```\n")
        self.assertNotIn("`", flat)
        self.assertEqual(len(docx.parse_blocks(flat)), 2)

    def test_a_blockquote_keeps_its_words(self):
        text, _notes = self.rendered_text("> Ali rebuilt our billing pipeline.\n")
        self.assertEqual(text, "Ali rebuilt our billing pipeline.")

    def test_a_footnote_definition_keeps_the_sentence(self):
        text, _notes = self.rendered_text("[^1]: Source: internal dashboard\n")
        self.assertEqual(text, "Source: internal dashboard")

    def test_a_link_whose_text_holds_brackets_is_rewritten(self):
        text, _notes = self.rendered_text("See [ref [1]](https://example.com)\n")
        self.assertEqual(text, "See ref [1] (https://example.com)")

    def test_a_wrapped_bullet_is_still_a_continuation_not_code(self):
        # Four-space indentation under a list item is a wrapped bullet, and
        # only the absence of a list item above makes it a code block.
        blocks = docx.parse_blocks(
            docx.flatten("- Led a team of 4 through a\n    vendor migration\n")[0]
        )
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["kind"], "bullet")


if __name__ == "__main__":
    unittest.main()

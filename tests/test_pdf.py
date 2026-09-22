"""Tests for `scripts/pdf.py` — markdown to a hand-written PDF 1.4.

`sys.path` is pointed at `scripts/` the same way every other test module in
this repository does it. Standard-library only, so shadowing a pip-installed
`pdf` module (there is none) is not a concern, but the convention is kept for
consistency with `tests/test_docx.py`.
"""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import pdf  # noqa: E402


class TestTextWidthHappyPath(unittest.TestCase):
    def test_a_at_1000pt_is_667(self):
        self.assertEqual(pdf.text_width("A", 1000, False), 667)


# The pinned values from the plan's Contracts § Widths section. Scaling to
# 1000pt makes `text_width` return the raw AFM advance width unchanged
# (width * 1000 / 1000), so these assert the fetched table directly rather
# than through any arithmetic that could hide a wrong number.
class TestWidthTablesArePinned(unittest.TestCase):
    def test_helvetica_pinned_values(self):
        cases = {
            " ": 278,
            "A": 667,
            "a": 556,
            "W": 944,
            "i": 222,
            "m": 833,
            "•": 350,  # bullet, WinAnsi byte 0x95
        }
        for char, width in cases.items():
            with self.subTest(char=repr(char)):
                self.assertEqual(pdf.text_width(char, 1000, False), width)

    def test_helvetica_bold_pinned_values(self):
        cases = {" ": 278, "A": 722, "a": 556, "i": 278, "m": 889}
        for char, width in cases.items():
            with self.subTest(char=repr(char)):
                self.assertEqual(pdf.text_width(char, 1000, True), width)

    def test_both_tables_have_224_entries(self):
        self.assertEqual(len(pdf.HELVETICA_WIDTHS), 224)
        self.assertEqual(len(pdf.HELVETICA_BOLD_WIDTHS), 224)


class TestEncode(unittest.TestCase):
    def test_winansi_characters_encode(self):
        # é (eacute), · (periodcentered), – (endash), — (emdash),
        # • (bullet) — every one of them a real WinAnsi byte, not ASCII.
        self.assertEqual(
            pdf.encode("é · – — •"),
            "é · – — •".encode("cp1252"),
        )

    def test_a_tab_becomes_a_space(self):
        self.assertEqual(pdf.encode("\t"), b" ")

    def test_a_control_character_becomes_a_space(self):
        self.assertEqual(pdf.encode("a\x01b"), b"a b")

    def test_unmappable_characters_raise(self):
        for char in ("→", "中", "\U0001f600"):  # →, 中, 😀
            with self.subTest(char=repr(char)):
                with self.assertRaises(UnicodeEncodeError):
                    pdf.encode(char)


class TestWrap(unittest.TestCase):
    def test_empty_text_returns_no_lines(self):
        self.assertEqual(pdf.wrap("", 10, False, 400), [])

    def test_whitespace_only_text_returns_no_lines(self):
        self.assertEqual(pdf.wrap("   \t  ", 10, False, 400), [])

    def test_one_short_word_is_one_line(self):
        self.assertEqual(pdf.wrap("hello", 10, False, 400), ["hello"])

    def test_text_exactly_max_width_stays_on_one_line(self):
        width = pdf.text_width("hello world", 10, False)
        self.assertEqual(pdf.wrap("hello world", 10, False, width), ["hello world"])

    def test_one_point_more_forces_a_second_line(self):
        # Two equal words whose combined width is just over the width of one
        # of them: the second word cannot join the first line.
        one_word_width = pdf.text_width("hello", 10, False)
        self.assertEqual(
            pdf.wrap("hello hello", 10, False, one_word_width),
            ["hello", "hello"],
        )

    def test_a_long_word_with_no_spaces_is_hard_split(self):
        word = "x" * 200
        lines = pdf.wrap(word, 10, False, 40)
        self.assertTrue(len(lines) > 1)
        for line in lines:
            self.assertLessEqual(pdf.text_width(line, 10, False), 40 + 0.01)
        self.assertEqual("".join(lines), word)

    def test_multiple_spaces_collapse_to_one(self):
        self.assertEqual(
            pdf.wrap("hello    world", 10, False, 4000), ["hello world"]
        )

    def test_wrap_never_returns_an_empty_list_for_non_empty_text(self):
        self.assertNotEqual(pdf.wrap("x", 10, False, 1), [])

    def test_property_no_line_exceeds_max_width_and_words_round_trip(self):
        # Words are generated short enough (<= 8 chars from a small alphabet)
        # that no single word can exceed `max_width` on its own — the
        # hard-split path is exercised separately above, by an explicit case,
        # because a hard-split line has no space to rejoin with, which would
        # break the `" ".join(lines) == normalised text` half of this
        # property. This still runs the greedy wrap over 500 varied inputs.
        rng = random.Random(0)
        alphabet = "abcdefghij"
        size, bold, max_width = 10, False, 60
        for _ in range(500):
            word_count = rng.randint(0, 8)
            words = [
                "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 8)))
                for _ in range(word_count)
            ]
            # Multiple spaces between words too, to exercise collapsing — but
            # never zero, which would merge two words into one and make the
            # round-trip assertion below fail for a reason that has nothing
            # to do with `wrap`.
            spaced = (" " * rng.randint(1, 3)).join(words) if words else ""
            lines = pdf.wrap(spaced, size, bold, max_width)
            for line in lines:
                self.assertLessEqual(pdf.text_width(line, size, bold), max_width + 0.01)
            self.assertEqual(" ".join(lines), " ".join(words))


if __name__ == "__main__":
    unittest.main()

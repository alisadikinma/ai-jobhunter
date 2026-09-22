"""Tests for `scripts/pdf.py` — markdown to a hand-written PDF 1.4.

`sys.path` is pointed at `scripts/` the same way every other test module in
this repository does it. Standard-library only, so shadowing a pip-installed
`pdf` module (there is none) is not a concern, but the convention is kept for
consistency with `tests/test_docx.py`.
"""

import contextlib
import io
import os
import random
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import docx  # noqa: E402
import pdf  # noqa: E402


# --- a test-only PDF reader ------------------------------------------------
#
# Just enough of PDF 1.4 to check `pdf.py`'s OWN writer against itself: the
# xref table's offsets, each stream's declared `/Length`, and the ordered
# text of every `(...) Tj` operator. Not a general parser — it assumes the
# exact object shapes `_build_pdf_bytes` emits (verbatim `"<n> 0 obj"`,
# `<< /Length N >>\nstream\n...endstream`, one `Tj` per content line) and
# raises `AssertionError` rather than degrading gracefully if that shape
# ever changes, which is exactly what a test for the writer should do.

_XREF_ENTRY_RE = re.compile(rb"^(\d{10}) (\d{5}) ([nf]) $")
_STREAM_RE = re.compile(rb"<< /Length (\d+) >>\nstream\n")
_TJ_LINE_RE = re.compile(rb"\((.*)\) Tj ET$", re.M)
_OCTAL_ESCAPE_RE = re.compile(rb"[0-7]{1,3}")


def _unescape_pdf_literal(raw):
    """The inverse of `pdf._pdf_literal`: escaped bytes back to a `str`."""
    out = bytearray()
    i = 0
    while i < len(raw):
        byte = raw[i]
        if byte == 0x5C:  # backslash
            nxt = raw[i + 1 : i + 2]
            if nxt in (b"\\", b"(", b")"):
                out.append(nxt[0])
                i += 2
                continue
            digits = _OCTAL_ESCAPE_RE.match(raw, i + 1)
            if digits:
                out.append(int(digits.group(), 8) & 0xFF)
                i = digits.end()
                continue
            i += 1  # an escape this reader does not know; skip the backslash
            continue
        out.append(byte)
        i += 1
    return bytes(out).decode("cp1252")


def read_pdf(data):
    """Parse a `pdf.render` output enough to assert its structure and text.

    Returns a dict: `offsets` (object number -> byte offset, from the xref
    table), `stream_lengths` (list of `(declared, actual)` pairs — equal iff
    `/Length` is honest), and `texts` (every `Tj` string, in file order,
    decoded back to `str`).
    """
    assert data.startswith(b"%PDF-1.4\n"), data[:20]
    assert data.endswith(b"%%EOF\n"), data[-20:]

    startxref_at = data.rfind(b"startxref")
    assert startxref_at != -1
    match = re.search(rb"startxref\s+(\d+)", data[startxref_at:])
    xref_offset = int(match.group(1))
    assert data[xref_offset : xref_offset + 4] == b"xref", data[xref_offset : xref_offset + 20]

    trailer_at = data.find(b"trailer", xref_offset)
    assert trailer_at != -1
    xref_lines = data[xref_offset:trailer_at].splitlines()
    assert xref_lines[0] == b"xref"
    start, count = (int(x) for x in xref_lines[1].split())
    # `xref_lines[0]` is `"xref"`, `xref_lines[1]` is the `"0 N"` subsection
    # header, and `xref_lines[2 + i]` is the entry for object `start + i` —
    # entry 0 (`i == 0`) is always the free-list head, never a real object.
    offsets = {}
    for i in range(1, count):
        entry = xref_lines[2 + i]
        m = _XREF_ENTRY_RE.match(entry)
        assert m, entry
        offsets[start + i] = int(m.group(1))

    for number, offset in offsets.items():
        marker = ("%d 0 obj" % number).encode("ascii")
        assert data[offset : offset + len(marker)] == marker, (
            number,
            offset,
            data[offset : offset + 20],
        )

    stream_lengths = []
    texts = []
    for stream_match in _STREAM_RE.finditer(data):
        declared = int(stream_match.group(1))
        start = stream_match.end()
        stream_data = data[start : start + declared]
        stream_lengths.append((declared, len(stream_data)))
        assert data[start + declared : start + declared + 9] == b"endstream", (
            declared,
            data[start + declared : start + declared + 20],
        )
        for tj in _TJ_LINE_RE.finditer(stream_data):
            texts.append(_unescape_pdf_literal(tj.group(1)))

    return {"offsets": offsets, "stream_lengths": stream_lengths, "texts": texts}


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

    def test_superscript_digit_widths_pinned(self):
        # 0xB2 (twosuperior), 0xB3 (threesuperior), 0xB9 (onesuperior) — the
        # AGLFN glyph-name mapping the tables were generated from has no
        # entry for these three codepoints, so the generator silently left
        # them at 0. The Adobe Core14 AFM (Helvetica.afm / Helvetica-Bold.afm)
        # gives WX 333 for all three, in both weights.
        cases = {"²": 333, "³": 333, "¹": 333}
        for char, width in cases.items():
            with self.subTest(char=repr(char), bold=False):
                self.assertEqual(pdf.text_width(char, 1000, False), width)
            with self.subTest(char=repr(char), bold=True):
                self.assertEqual(pdf.text_width(char, 1000, True), width)

    def test_every_encodable_cp1252_byte_has_a_positive_width(self):
        # Every byte 0x20-0xFF that cp1252 actually decodes to a character
        # has a real glyph in Helvetica except 0x7F (DEL), which `encode`
        # turns into a space before it ever reaches the width table and so
        # is legitimately never looked up as a printable character.
        for byte in range(0x20, 0x100):
            if byte == 0x7F:
                continue
            try:
                char = bytes([byte]).decode("cp1252")
            except UnicodeDecodeError:
                continue  # one of the 5 WinAnsi bytes with no cp1252 mapping
            with self.subTest(byte=hex(byte), char=repr(char)):
                self.assertGreater(pdf.text_width(char, 1000, False), 0)
                self.assertGreater(pdf.text_width(char, 1000, True), 0)


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

    def test_del_becomes_a_space(self):
        # 0x7F (DEL) is not `ord < 0x20`, so it slipped past the control-char
        # replacement and reached `cp1252` as a raw, invisible control byte.
        self.assertEqual(pdf.encode("a\x7fb"), b"a b")

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


class PdfTempDirCase(unittest.TestCase):
    """The `docx.DocxTempDirCase` pattern (`tests/test_docx.py`), for PDF."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ajob3-pdf-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # `render` writes one observability line to stderr on success.
        self.stderr = io.StringIO()
        redirect = contextlib.redirect_stderr(self.stderr)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def out(self, name="cv.pdf"):
        return os.path.join(self.tmp, name)

    def tmp_files(self):
        return sorted(os.listdir(self.tmp))


class TestRenderProducesAValidPdf(PdfTempDirCase):
    def test_header_and_eof(self):
        path = self.out()
        pdf.render("# T\n\nBody\n", path)
        data = open(path, "rb").read()
        self.assertTrue(data.startswith(b"%PDF-1.4"))
        self.assertTrue(data.endswith(b"%%EOF\n"))


class TestPageSizes(PdfTempDirCase):
    def test_letter_media_box(self):
        path = self.out()
        pdf.render("# T\n\nBody\n", path, page="letter")
        data = open(path, "rb").read()
        self.assertIn(b"/MediaBox [0 0 612 792]", data)

    def test_a4_media_box(self):
        path = self.out()
        pdf.render("# T\n\nBody\n", path, page="a4")
        data = open(path, "rb").read()
        self.assertIn(b"/MediaBox [0 0 595 842]", data)


class TestTextOrderAndRoundTrip(PdfTempDirCase):
    def test_text_order_matches_block_order(self):
        path = self.out()
        pdf.render(
            "# Rin Halvorsen\n\n- Grew ARR\n- Shipped the thing\n\n## Skills\n\nPython\n",
            path,
        )
        parsed = read_pdf(open(path, "rb").read())
        self.assertEqual(
            parsed["texts"],
            [
                "Rin Halvorsen",
                pdf.BULLET_CHAR,
                "Grew ARR",
                pdf.BULLET_CHAR,
                "Shipped the thing",
                "Skills",
                "Python",
            ],
        )

    def test_parens_and_backslash_round_trip(self):
        path = self.out()
        pdf.render("# CV\n\nUsed (parens) and a back\\\\slash\n", path)
        parsed = read_pdf(open(path, "rb").read())
        self.assertIn("Used (parens) and a back\\slash", parsed["texts"])

    def test_eacute_round_trips_via_octal_351(self):
        path = self.out()
        pdf.render("# CV\n\nCafé\n", path)
        data = open(path, "rb").read()
        self.assertIn(rb"Caf\351", data)
        parsed = read_pdf(data)
        self.assertIn("Café", parsed["texts"])


class TestManyPages(PdfTempDirCase):
    def test_300_bullets_spans_multiple_pages_and_count_matches(self):
        markdown = "# CV\n\n" + "".join("- bullet number %d\n" % i for i in range(300))
        path = self.out()
        result = pdf.render(markdown, path)
        self.assertGreater(result["pages"], 1)
        data = open(path, "rb").read()
        count_match = re.search(rb"/Count (\d+)", data)
        self.assertEqual(int(count_match.group(1)), result["pages"])
        parsed = read_pdf(data)
        # Exactly one object per page carries `/Contents` — `/Type /Page`
        # also matches the `/Pages` object's `/Type /Pages` substring-wise,
        # so `/Contents` is the unambiguous per-page marker. Each object's
        # own slice ends at its OWN `endobj`, found by searching forward
        # from its start — a fixed lookahead window instead over-reads into
        # the following object for a short content stream and double-counts.
        contents_objects = []
        for number, start in parsed["offsets"].items():
            end = data.index(b"\nendobj\n", start)
            if b"/Contents " in data[start:end]:
                contents_objects.append(number)
        self.assertEqual(len(contents_objects), result["pages"])


class TestBulletIndent(unittest.TestCase):
    def test_glyph_at_margin_continuation_at_margin_plus_indent(self):
        long_text = " ".join(["word"] * 40)
        blocks = [{"kind": "bullet", "text": long_text}]
        pages = pdf.layout(blocks, "letter")
        ops = pages[0]
        glyph_ops = [op for op in ops if op[4] == pdf.BULLET_CHAR]
        self.assertEqual(len(glyph_ops), 1)
        self.assertEqual(glyph_ops[0][0], pdf.MARGIN)
        text_ops = [op for op in ops if op[4] != pdf.BULLET_CHAR]
        self.assertGreaterEqual(len(text_ops), 2, "test needs the bullet to wrap")
        for op in text_ops:
            self.assertEqual(op[0], pdf.MARGIN + pdf.BULLET_INDENT)


class TestTitle(PdfTempDirCase):
    def test_title_equals_first_heading(self):
        path = self.out()
        pdf.render("# Rin Halvorsen\n\n## Skills\n\nPython\n", path)
        data = open(path, "rb").read()
        self.assertIn(b"/Title (Rin Halvorsen)", data)

    def test_no_title_when_there_is_no_heading(self):
        path = self.out()
        pdf.render("Just a paragraph, no heading.\n", path)
        data = open(path, "rb").read()
        self.assertNotIn(b"/Title", data)


class TestDeterministicOutput(PdfTempDirCase):
    def test_same_input_twice_is_byte_identical(self):
        markdown = "# Rin Halvorsen\n\n- Grew ARR\n- Shipped the thing\n"
        first = self.out("first.pdf")
        second = self.out("second.pdf")
        pdf.render(markdown, first)
        pdf.render(markdown, second)
        self.assertEqual(open(first, "rb").read(), open(second, "rb").read())


class TestHeadingNeverLastLineOfAPage(unittest.TestCase):
    def test_a_dangling_heading_moves_to_the_next_page(self):
        # Constructed, not guessed: a filler paragraph (one hard-split word,
        # so its exact line count is exact — no word-wrap boundary guessing)
        # sized so that after it, the heading below would fit ALONE on page
        # 1 but placing it there would leave the following paragraph's
        # first line short of `MARGIN`. `layout` must then push the whole
        # heading to page 2, where a full fresh page trivially fits both.
        page = "letter"
        width, height = pdf.PAGE_SIZES[page]
        max_width = width - 2 * pdf.MARGIN
        char_width = pdf.text_width("x", 10.5, False)
        per_line = int(max_width // char_width)

        heading_leading = pdf.SIZES[("heading", 1)][0] * pdf.LEADING
        heading_space_after = pdf.SPACE_AFTER["heading"]
        para_leading = pdf.SIZES[("paragraph", None)][0] * pdf.LEADING
        para_space_after = pdf.SPACE_AFTER["paragraph"]
        top = height - pdf.MARGIN

        n = 1
        filler_text = None
        while n < 200:
            y_after_filler = top - (n * para_leading + para_space_after)
            fits_alone = (y_after_filler - heading_leading) >= pdf.MARGIN
            fits_with_next = (
                y_after_filler - heading_leading - heading_space_after - para_leading
            ) >= pdf.MARGIN
            if fits_alone and not fits_with_next:
                filler_text = "x" * (per_line * n)
                break
            n += 1
        self.assertIsNotNone(filler_text, "could not construct the scenario")

        blocks = [
            {"kind": "paragraph", "text": filler_text},
            {"kind": "heading", "level": 1, "text": "Section"},
            {"kind": "paragraph", "text": "Body"},
        ]
        pages = pdf.layout(blocks, page)
        self.assertGreaterEqual(len(pages), 2)
        page1_texts = [op[4] for op in pages[0]]
        page2_texts = [op[4] for op in pages[1]]
        self.assertNotIn("Section", page1_texts)
        self.assertIn("Section", page2_texts)
        self.assertIn("Body", page2_texts)


class TestRefusalsLeaveNoFileAndNoTempFile(PdfTempDirCase):
    def test_unverified_claim_refuses(self):
        path = self.out()
        with self.assertRaises(docx.UnverifiedClaimError):
            pdf.render("- x [verifikasi]\n", path)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.tmp_files(), [])

    def test_empty_markdown_refuses(self):
        path = self.out()
        with self.assertRaises(docx.EmptyDocumentError):
            pdf.render("", path)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.tmp_files(), [])

    def test_missing_directory_refuses(self):
        path = os.path.join(self.tmp, "nonexistent-subdir", "cv.pdf")
        with self.assertRaises(docx.DestinationError):
            pdf.render("# CV\n\nBody\n", path)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.tmp_files(), [])

    def test_unsupported_character_names_codepoint_and_line(self):
        path = self.out()
        with self.assertRaises(pdf.UnsupportedCharacterError) as caught:
            pdf.render("a → b\n中\n", path)
        message = str(caught.exception)
        self.assertIn("U+2192", message)
        self.assertIn("line 1", message)
        self.assertIn("U+4E2D", message)
        self.assertIn("line 2", message)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.tmp_files(), [])


class TestUnsupportedCharacterLineNumberAfterFlatten(PdfTempDirCase):
    def test_an_entity_decoded_char_reports_its_own_source_line(self):
        # `&rarr;` is not the arrow character itself — `docx.prepare` (via
        # `flatten`/`strip_html`) decodes the entity into `→` before `pdf.py`
        # ever sees the block text, so a raw search of `markdown.splitlines()`
        # for `→` finds nothing and used to fall back to a hardcoded line 1,
        # no matter which line the entity was actually on.
        path = self.out()
        markdown = "# CV\n\nfiller\nfiller\nx &rarr; y\n"
        with self.assertRaises(pdf.UnsupportedCharacterError) as caught:
            pdf.render(markdown, path)
        message = str(caught.exception)
        self.assertIn("line 5", message)
        self.assertNotIn("line 1'", message)

    def test_a_character_findable_nowhere_reports_a_question_mark(self):
        # Constructed so the offending character never appears in the
        # markdown source at all, not even after entity decoding — this can
        # only happen if a future transform invents a brand new character
        # `flatten` produces from something unrelated. Since no fixture like
        # that exists today, this patches `_find_unsupported_characters`'s
        # own helper to simulate one: search must fail honestly, never guess.
        with unittest.mock.patch("pdf._line_for_char", return_value=None):
            path = self.out()
            with self.assertRaises(pdf.UnsupportedCharacterError) as caught:
                pdf.render("x → y\n", path)
            self.assertIn("line ?", str(caught.exception))


class TestGateParityWithDocx(PdfTempDirCase):
    """Every marker spelling `docx.py`'s gate catches, refused identically.

    Copied from `tests/test_docx.py`,
    `TestUnverifiedOverride.test_the_override_strips_every_spelling_the_gate_catches`
    (around line 1258) — that dict is a local variable in a test method, not
    something the `docx` module exposes, so there is nothing to import.
    """

    SPELLINGS = {
        "bare": "- Grew ARR [verifikasi]",
        "bold": "- Grew ARR [**verifikasi**]",
        "underscore": "- Grew ARR [__verifikasi__]",
        "code span": "- Grew ARR [`verifikasi`]",
        "with reason": "- Grew ARR [Assumption: from memory]",
        "entities": "- Grew ARR &#91;verifikasi&#93;",
        "double entities": "- Grew ARR &amp;#91;verifikasi&amp;#93;",
        "hex entity": "- Grew ARR &#x5B;verifikasi&#x5D;",
        "control char": "- Grew ARR [veri\x01fikasi]",
        "zero width": "- Grew ARR [veri​fikasi]",
        "fullwidth": "- Grew ARR ［verifikasi］",
    }

    def test_pdf_refuses_every_spelling_docx_refuses(self):
        for name, line in self.SPELLINGS.items():
            markdown = "# CV\n\n%s\n" % line
            safe_name = name.replace(" ", "-")
            with self.subTest(spelling=name):
                with self.assertRaises(docx.UnverifiedClaimError):
                    docx.render(markdown, self.out("docx-%s.docx" % safe_name))
                with self.assertRaises(docx.UnverifiedClaimError):
                    pdf.render(markdown, self.out("pdf-%s.pdf" % safe_name))


class TestFailedWriteLeavesNoFileAndNoTempFile(PdfTempDirCase):
    def test_a_failed_replace_leaves_no_file_and_no_temp_file(self):
        path = self.out()
        with unittest.mock.patch("pdf.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(docx.DestinationError):
                pdf.render("# CV\n\nHello\n", path)
        self.assertFalse(os.path.exists(path))
        leftover = [name for name in self.tmp_files() if name.endswith(".pdf.tmp")]
        self.assertEqual(leftover, [])


if __name__ == "__main__":
    unittest.main()


class TestOutputPermissions(unittest.TestCase):
    """`mkstemp` creates at 0600 and `os.replace` carries that mode onto the
    destination. Found by running the real flow: every CV came out readable
    by its owner only, which an upload helper running as another user, or a
    shared folder, cannot open."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.old_umask = os.umask(0o022)
        self.addCleanup(os.umask, self.old_umask)

    def _mode(self, path):
        return os.stat(path).st_mode & 0o777

    def test_a_new_pdf_gets_the_mode_open_would_give_it(self):
        out = os.path.join(self.dir, "cv.pdf")
        pdf.render("# T\n\nBody\n", out)
        self.assertEqual(self._mode(out), 0o644)

    def test_the_umask_is_honoured_not_overridden(self):
        os.umask(0o077)
        out = os.path.join(self.dir, "cv.pdf")
        pdf.render("# T\n\nBody\n", out)
        self.assertEqual(self._mode(out), 0o600)

    def test_a_re_render_keeps_the_existing_files_mode(self):
        out = os.path.join(self.dir, "cv.pdf")
        pdf.render("# T\n\nBody\n", out)
        os.chmod(out, 0o640)
        pdf.render("# T\n\nBody again\n", out)
        self.assertEqual(self._mode(out), 0o640)

    def test_docx_follows_the_same_rule(self):
        out = os.path.join(self.dir, "cv.docx")
        docx.render("# T\n\nBody\n", out)
        self.assertEqual(self._mode(out), 0o644)

"""Turn a tailored CV or cover letter into a hand-written PDF 1.4.

AJOB-3 reversed AJOB-2's "DOCX only" decision: tailored output ships as PDF,
not `.docx`. This module writes the PDF bytes by hand with `zipfile`'s
sibling-in-spirit stdlib tools — no `reportlab`, no pip — because the project
stays standard-library only. It reuses `docx.prepare()` for the markdown gate
(lint, refuse, repair, parse) so a candidate's CV is refused identically by
both renderers; only the page layout and the byte format differ.

Three layers, in the order `render` calls them:

- `encode` / `text_width` / `wrap`  — text primitives: WinAnsi encoding,
  Helvetica advance widths, greedy line wrapping. Pure functions, no PDF
  knowledge.
- `layout`   — places wrapped lines on pages, top to bottom, respecting
  margins and page breaks. Pure function: blocks in, page geometry out.
- the writer — turns page geometry into the actual PDF 1.4 byte stream:
  objects, content streams, xref table, trailer.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import docx  # noqa: E402 — `docx.prepare()` is the shared markdown gate


class PdfError(Exception):
    """Base for every refusal this module raises."""


class UnsupportedCharacterError(PdfError):
    """A character in the markdown has no Helvetica/WinAnsi glyph.

    Helvetica is a Core14 font with a single-byte WinAnsi encoding: there is
    no fallback glyph and no second font to switch to. Substituting "?" would
    ship a CV that silently lies about what the candidate wrote, so this
    stops the render before any byte is written, and names every distinct
    offending character and where it first appears — never just the first
    one, because fixing one only to hit the next on the next run is the
    annoying way to find out there were three.
    """


# --- text primitives -------------------------------------------------------
#
# Widths are Adobe Core14 AFM advance widths (1/1000 em), indexed by
# `byte - 32` for WinAnsiEncoding byte codes 32-255 (224 entries each).
#
# Source: `Helvetica.afm` / `Helvetica-Bold.afm` from the pdfkit repository
# (https://github.com/foliojs/pdfkit, MIT), which ships the same
# freely-redistributable Adobe Core14 metrics reportlab and pdf.js carry.
# Fetched 2026-09-22 from:
#   https://raw.githubusercontent.com/foliojs/pdfkit/master/lib/font/data/Helvetica.afm
#   https://raw.githubusercontent.com/foliojs/pdfkit/master/lib/font/data/Helvetica-Bold.afm
#
# The AFM's own `C <code>` column is StandardEncoding, not WinAnsi, so the
# table below was built by glyph NAME, not by AFM code: for each WinAnsi byte
# 32-255, `bytes([b]).decode("cp1252")` gives the Unicode character, which is
# mapped to its Adobe glyph name via the Adobe Glyph List for New Fonts
# (https://github.com/adobe-type-tools/agl-aglfn, also fetched 2026-09-22),
# and that name is looked up in the AFM's `WX` column. The five WinAnsi bytes
# with no cp1252 mapping (0x81, 0x8D, 0x8F, 0x90, 0x9D) get width 0 — `encode`
# raises before either table is consulted for them anyway, since the cp1252
# codec itself refuses to encode them. Byte 0xA0 (no-break space) takes the
# "space" width and 0xAD (soft hyphen) takes the "hyphen" width, per the PDF
# spec's WinAnsiEncoding table, neither of which the cp1252 decode step
# reaches on its own.
#
# Every one of the pinned values below (space 278, A 667/722, a 556/556,
# W 944, i 222/278, m 833/889, bullet 0x95 350) came out of that fetch
# unchanged — nothing here was typed from memory.
HELVETICA_WIDTHS = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584, 0,
    556, 0, 222, 556, 333, 1000, 556, 556, 333, 1000, 667, 333, 1000, 0, 611, 0,
    0, 222, 222, 333, 333, 350, 556, 1000, 333, 1000, 500, 333, 944, 0, 500, 667,
    278, 333, 556, 556, 556, 556, 260, 556, 333, 737, 370, 556, 584, 333, 737, 333,
    400, 584, 0, 0, 333, 556, 537, 278, 333, 0, 365, 556, 834, 834, 834, 611,
    667, 667, 667, 667, 667, 667, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278,
    722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611,
    556, 556, 556, 556, 556, 556, 889, 500, 556, 556, 556, 556, 278, 278, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 584, 611, 556, 556, 556, 556, 500, 556, 500,
)

HELVETICA_BOLD_WIDTHS = (
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
    975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
    333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
    611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584, 0,
    556, 0, 278, 556, 500, 1000, 556, 556, 333, 1000, 667, 333, 1000, 0, 611, 0,
    0, 278, 278, 500, 500, 350, 556, 1000, 333, 1000, 556, 333, 944, 0, 500, 667,
    278, 333, 556, 556, 556, 556, 280, 556, 333, 737, 370, 556, 584, 333, 737, 333,
    400, 584, 0, 0, 333, 611, 556, 278, 333, 0, 365, 556, 834, 834, 834, 611,
    722, 722, 722, 722, 722, 722, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278,
    722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611,
    556, 556, 556, 556, 556, 556, 889, 556, 556, 556, 556, 556, 278, 278, 278, 278,
    611, 611, 611, 611, 611, 611, 611, 584, 611, 611, 611, 611, 611, 556, 611, 556,
)


def encode(text):
    """`text` as WinAnsi (cp1252) bytes, the encoding every object below assumes.

    Every character with `ord < 0x20` becomes a space first — a raw control
    character in a content stream is either illegal or reinterpreted by the
    viewer, and a CV line quietly losing its tab-turned-nothing is worse than
    the same line with a space in its place. What is left is handed straight
    to the `cp1252` codec, whose `UnicodeEncodeError` on an unmapped
    character (`→`, `中`, `😀`, ...) is the signal `render` turns into
    `UnsupportedCharacterError` once it also knows which markdown line the
    character came from.
    """
    text = "".join(" " if ord(ch) < 0x20 else ch for ch in text)
    return text.encode("cp1252")


def text_width(text, size, bold):
    """The advance width of `text` set in Helvetica at `size` points.

    Each byte's 1/1000-em width is looked up in the table for the requested
    weight and scaled by `size`; summing 1/1000-em units first and scaling
    once, rather than scaling per character, is both cheaper and exactly what
    the PDF spec's own formula does.
    """
    table = HELVETICA_BOLD_WIDTHS if bold else HELVETICA_WIDTHS
    total = sum(table[byte - 32] for byte in encode(text))
    return total * size / 1000


def wrap(text, size, bold, max_width):
    """`text` as a list of lines, none wider than `max_width` at `size` points.

    Greedy: words are added to the current line while it still fits, on the
    single space `" ".join` would use. A word that alone is wider than
    `max_width` cannot be helped by breaking elsewhere in the line, so it is
    hard-split character by character — the only case where a "line" is not
    a run of whole words. Whitespace runs collapse to one space, the way
    `str.split()` with no argument already does, which is also why
    `""` and an all-whitespace string both return `[]`: there are no words to
    place.
    """
    words = text.split()
    if not words:
        return []

    lines = []
    current = ""
    for word in words:
        if text_width(word, size, bold) > max_width:
            # No split point inside a line of whole words helps here; the
            # only way to keep every line within `max_width` is to give this
            # one word its own line(s), one character at a time.
            if current:
                lines.append(current)
                current = ""
            chunk = ""
            for char in word:
                candidate = chunk + char
                if chunk and text_width(candidate, size, bold) > max_width:
                    lines.append(chunk)
                    chunk = char
                else:
                    chunk = candidate
            current = chunk
            continue

        candidate = "%s %s" % (current, word) if current else word
        if text_width(candidate, size, bold) <= max_width + 0.01:
            current = candidate
        else:
            lines.append(current)
            current = word

    if current:
        lines.append(current)
    return lines

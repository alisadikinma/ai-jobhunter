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
import tempfile

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

    def __init__(self, findings, label="<markdown>"):
        self.findings = list(findings)
        self.label = label
        detail = "; ".join(
            "U+%04X '%s' on line %d" % (f["codepoint"], f["char"], f["line"])
            for f in self.findings
        )
        super().__init__(
            "refused to render %s: %d character(s) have no Helvetica/WinAnsi "
            "glyph and would be substituted or dropped by the PDF writer. "
            "%s" % (label, len(self.findings), detail)
        )


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
# AGLFN maps a Unicode CODEPOINT to a glyph name, and it has no entries for
# U+00B2/B3/B9 (superscript two/three/one) at all — those three codepoints
# are absent from AGLFN outright, not merely mismatched, so the by-name
# lookup above silently produced 0 for WinAnsi bytes 0xB2, 0xB3, 0xB9
# (`²`, `³`, `¹`). They were re-checked directly against the AFM's own glyph
# names (`twosuperior`, `threesuperior`, `onesuperior` — present in the AFM
# even though AGLFN doesn't carry them) and hand-patched to the AFM's WX 333
# for all three, in both weights.
#
# Every one of the pinned values below (space 278, A 667/722, a 556/556,
# W 944, i 222/278, m 833/889, bullet 0x95 350, superscripts 0xB2/B3/B9 333)
# came out of that fetch unchanged — nothing here was typed from memory.
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
    400, 584, 333, 333, 333, 556, 537, 278, 333, 333, 365, 556, 834, 834, 834, 611,
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
    400, 584, 333, 333, 333, 611, 556, 278, 333, 333, 365, 556, 834, 834, 834, 611,
    722, 722, 722, 722, 722, 722, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278,
    722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611,
    556, 556, 556, 556, 556, 556, 889, 556, 556, 556, 556, 556, 278, 278, 278, 278,
    611, 611, 611, 611, 611, 611, 611, 584, 611, 611, 611, 611, 611, 556, 611, 556,
)


def encode(text):
    """`text` as WinAnsi (cp1252) bytes, the encoding every object below assumes.

    Every character with `ord < 0x20`, plus `0x7F` (DEL), becomes a space
    first — a raw control character in a content stream is either illegal or
    reinterpreted by the viewer, and a CV line quietly losing its
    tab-turned-nothing is worse than the same line with a space in its
    place. DEL is not `< 0x20` but is exactly as much a control character:
    `cp1252` happily encodes it (it round-trips to U+007F), so without this
    it would reach the content stream as an invisible byte instead of being
    caught here. What is left is handed straight to the `cp1252` codec,
    whose `UnicodeEncodeError` on an unmapped character (`→`, `中`, `😀`,
    ...) is the signal `render` turns into `UnsupportedCharacterError` once
    it also knows which markdown line the character came from.
    """
    text = "".join(" " if ord(ch) < 0x20 or ord(ch) == 0x7F else ch for ch in text)
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


# --- layout ------------------------------------------------------------
#
# Page geometry, fixed rather than configurable — the same reasoning as
# `docx.STYLES`: every layout knob is a new way to produce a CV that looks
# fine on screen and reads wrong to a parser, or in this case simply falls
# off the page.

PAGE_SIZES = {"letter": (612, 792), "a4": (595, 842)}  # points
MARGIN = 54  # 0.75 in
SIZES = {
    ("heading", 1): (16, True),
    ("heading", 2): (12, True),
    ("heading", 3): (11, True),
    ("paragraph", None): (10.5, False),
    ("bullet", None): (10.5, False),
}  # (pt, bold)
LEADING = 1.25  # line height = size * LEADING
SPACE_AFTER = {"heading": 6, "paragraph": 6, "bullet": 2}  # points
BULLET_INDENT = 14  # text indent for bullets; glyph drawn at MARGIN
BULLET_CHAR = "•"  # the glyph itself; `docx.BULLET_GLYPH` also has the
# trailing space baked in because OOXML has no separate indent mechanism —
# here the indent IS the mechanism, so the glyph is drawn alone.


def _prepare_lines(blocks, max_width):
    """Each block's wrapped lines plus the metrics `layout` places them with.

    A bullet's continuation lines sit `BULLET_INDENT` narrower than a
    paragraph's, so its wrap width has to account for that before `wrap`
    ever runs — wrapping at the full column width and re-wrapping later
    would be both slower and a second place to get the indent wrong.
    """
    prepared = []
    for block in blocks:
        kind = block["kind"]
        size, bold = SIZES[(kind, block.get("level"))]
        text_max_width = max_width - BULLET_INDENT if kind == "bullet" else max_width
        prepared.append(
            {
                "kind": kind,
                "lines": wrap(block["text"], size, bold, text_max_width),
                "size": size,
                "bold": bold,
                "font": "F2" if bold else "F1",
                "leading": size * LEADING,
                "space_after": SPACE_AFTER[kind],
            }
        )
    return prepared


def layout(blocks, page):
    """`blocks` placed on `page`-sized pages, top-down from `height - MARGIN`.

    Returns one list of `(x, y, font, size, text)` per page — `font` is
    `"F1"`/`"F2"`, matching the `/Resources` keys the writer emits, and
    `text` is the original (not yet WinAnsi-encoded or escaped) string, so
    the writer is the only place that has to think about bytes at all.

    A bullet contributes two draw calls on its first line's baseline — the
    glyph at `x=MARGIN` and the text at `x=MARGIN + BULLET_INDENT` — and one
    per continuation line, text only, at the same indent.

    A heading is never rendered as the last thing on a page: before its
    first line is placed, this checks whether the heading AND the first
    line of the block after it both still fit; if not, the whole heading —
    not just the overflowing part — starts the next page instead. Nothing
    else gets this lookahead: an ordinary paragraph or bullet is allowed to
    split across a page break mid-block, which reads fine, but a heading
    with its own body stranded on the next page reads like a printing
    error.
    """
    width, height = PAGE_SIZES[page]
    max_width = width - 2 * MARGIN
    prepared = _prepare_lines(blocks, max_width)

    pages = [[]]
    y = height - MARGIN
    top_of_page = y

    def start_new_page():
        nonlocal y
        pages.append([])
        y = top_of_page

    for index, block in enumerate(prepared):
        lines = block["lines"]
        if not lines:
            continue
        leading = block["leading"]
        size = block["size"]
        font = block["font"]
        kind = block["kind"]
        space_after = block["space_after"]
        indent_x = MARGIN + BULLET_INDENT if kind == "bullet" else MARGIN

        if kind == "heading" and index + 1 < len(prepared):
            next_lines = prepared[index + 1]["lines"]
            if next_lines:
                after_heading = y - len(lines) * leading - space_after
                next_baseline = after_heading - prepared[index + 1]["leading"]
                # `y != top_of_page` guards against looping forever on a
                # heading so tall (or a page so short) that it can never
                # satisfy this rule even starting fresh — moving it again
                # would just repeat the same arithmetic on an identical
                # blank page. Better to let it dangle once than spin.
                if next_baseline < MARGIN and y != top_of_page:
                    start_new_page()

        for line_index, line in enumerate(lines):
            if y < MARGIN:
                start_new_page()
            if kind == "bullet" and line_index == 0:
                pages[-1].append((MARGIN, y, font, size, BULLET_CHAR))
            pages[-1].append((indent_x, y, font, size, line))
            y -= leading

        y -= space_after

    return pages


# --- the PDF 1.4 writer --------------------------------------------------
#
# Written by hand: five kinds of object (Catalog, Pages, two Fonts, Info),
# one Page + one content-stream object per page, an xref table and a
# trailer. No compression, no object streams, no cross-reference streams —
# PDF 1.4 is old enough that every reader still understands the plain
# version, and a hand-rolled writer has enough moving parts already without
# also reimplementing Flate.

_LITERAL_ESCAPE = {0x28: b"\\(", 0x29: b"\\)", 0x5C: b"\\\\"}


def _pdf_literal(text):
    """`text` as the bytes that belong between `(` and `)` in a content stream.

    `encode(text)` gives WinAnsi bytes; `(`, `)` and `\\` are escaped because
    they are the literal string's own delimiters and escape character, and
    every byte `>= 0x80` is written `\\ddd` (three octal digits) so the
    content stream itself stays ASCII — a raw high bit in a PDF string is
    legal, but some readers still choke on it, and octal costs nothing here.
    """
    out = bytearray()
    for byte in encode(text):
        if byte in _LITERAL_ESCAPE:
            out.extend(_LITERAL_ESCAPE[byte])
        elif byte >= 0x80:
            out.extend(("\\%03o" % byte).encode("ascii"))
        else:
            out.append(byte)
    return bytes(out)


def _fmt_num(value):
    """A PDF number for `value` — no trailing `.0`, no float noise."""
    if float(value).is_integer():
        return str(int(value))
    return ("%.4f" % value).rstrip("0").rstrip(".")


def _object_bytes(number, body):
    return b"%d 0 obj\n" % number + body + b"\nendobj\n"


def _content_stream(page_ops):
    lines = []
    for x, y, font, size, text in page_ops:
        lines.append(
            b"BT /"
            + font.encode("ascii")
            + b" "
            + _fmt_num(size).encode("ascii")
            + b" Tf "
            + _fmt_num(x).encode("ascii")
            + b" "
            + _fmt_num(y).encode("ascii")
            + b" Td ("
            + _pdf_literal(text)
            + b") Tj ET\n"
        )
    return b"".join(lines)


def _first_heading_text(blocks):
    for block in blocks:
        if block["kind"] == "heading":
            return block["text"]
    return None


def _build_pdf_bytes(blocks, pages, page_size):
    """The complete PDF 1.4 byte stream for `pages` (from `layout`).

    Object numbers are fixed by the Contracts section, not merely
    convenient: 1 Catalog, 2 Pages, 3 Font F1, 4 Font F2, 5 Info, then one
    `Page`/`Contents` pair per page starting at 6. Deterministic throughout
    — no timestamp anywhere — so the same markdown renders byte-identical
    PDFs, which is what makes a committed fixture diffable instead of
    merely trusted.
    """
    width, height = PAGE_SIZES[page_size]
    page_numbers = [6 + 2 * i for i in range(len(pages))]
    contents_numbers = [7 + 2 * i for i in range(len(pages))]
    total_objects = 5 + 2 * len(pages)

    objects = {}
    kids = " ".join("%d 0 R" % n for n in page_numbers)
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = (
        "<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(pages))
    ).encode("ascii")
    objects[3] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )
    objects[4] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
        b"/Encoding /WinAnsiEncoding >>"
    )
    info = b"/Producer (ai-jobhunter)"
    title = _first_heading_text(blocks)
    if title is not None:
        info += b" /Title (" + _pdf_literal(title) + b")"
    objects[5] = b"<< " + info + b" >>"

    for page_number, contents_number, page_ops in zip(
        page_numbers, contents_numbers, pages
    ):
        objects[page_number] = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %s %s] "
            "/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
            "/Contents %d 0 R >>"
            % (_fmt_num(width), _fmt_num(height), contents_number)
        ).encode("ascii")
        stream = _content_stream(page_ops)
        objects[contents_number] = (
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream"
        )

    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    parts = [header]
    offsets = {}
    cursor = len(header)
    for number in range(1, total_objects + 1):
        offsets[number] = cursor
        chunk = _object_bytes(number, objects[number])
        parts.append(chunk)
        cursor += len(chunk)

    xref_offset = cursor
    xref_parts = [b"xref\n", b"0 %d\n" % (total_objects + 1), b"0000000000 65535 f \n"]
    for number in range(1, total_objects + 1):
        xref_parts.append(b"%010d 00000 n \n" % offsets[number])
    parts.extend(xref_parts)

    parts.append(
        b"trailer\n<< /Size %d /Root 1 0 R /Info 5 0 R >>\nstartxref\n%d\n"
        % (total_objects + 1, xref_offset)
    )
    parts.append(b"%%EOF\n")
    return b"".join(parts)


def _find_unsupported_characters(blocks, markdown):
    """Every distinct character in `blocks` that Helvetica/WinAnsi has no glyph for.

    Checked across ALL blocks before anything is written, and each distinct
    character is reported once — the alternative, stopping at the first
    offender, means the candidate fixes one character, reruns, and hits the
    next one; nothing here is expensive enough to make that worth doing.
    """
    seen = {}
    for block in blocks:
        for char in block["text"]:
            if char in seen:
                continue
            try:
                encode(char)
            except UnicodeEncodeError:
                seen[char] = True
    if not seen:
        return []

    # The line is the character's first occurrence in the ORIGINAL markdown,
    # not in the flattened/rewritten block text `prepare` produced — that is
    # the text the candidate can actually go find and fix.
    lines = markdown.splitlines()
    findings = []
    for char in seen:
        line_number = 1
        for number, line in enumerate(lines, start=1):
            if char in line:
                line_number = number
                break
        findings.append({"char": char, "codepoint": ord(char), "line": line_number})
    return findings


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


def render(markdown, path, allow_unverified=False, source=None, page="letter"):
    """Write `markdown` to `path` as a hand-written PDF 1.4.

    Same order as `docx.render`, and for the same reason: lint, refuse,
    repair and parse before anything touches the filesystem, so a refused
    render leaves no file at all. The two renderers share the first three
    of those steps outright, through `docx.prepare` — this module's own
    contribution starts at the encode check.

    Returns `{"out", "pages", "blocks", "notes", "bytes"}`. Raises
    `docx.UnverifiedClaimError` unless `allow_unverified`,
    `docx.EmptyDocumentError` when there is nothing to write,
    `UnsupportedCharacterError` when a character has no Helvetica/WinAnsi
    glyph, and `docx.DestinationError` when the destination cannot be
    written.
    """
    label = source or os.path.basename(path) or "<markdown>"

    blocks, notes = docx.prepare(markdown, label, allow_unverified)

    unsupported = _find_unsupported_characters(blocks, markdown)
    if unsupported:
        raise UnsupportedCharacterError(unsupported, label)

    pages = layout(blocks, page)

    directory = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(directory):
        raise docx.DestinationError(
            "cannot write %s: the directory %s does not exist" % (path, directory)
        )

    try:
        handle, temporary = tempfile.mkstemp(suffix=".pdf.tmp", dir=directory)
        os.close(handle)
    except OSError as error:
        raise docx.DestinationError("cannot write %s: %s" % (path, error)) from error

    try:
        data = _build_pdf_bytes(blocks, pages, page)
        with open(temporary, "wb") as f:
            f.write(data)
        size = os.path.getsize(temporary)
        # Same 0600 trap and the same fix as the docx writer.
        os.chmod(temporary, docx.output_mode(path))
        os.replace(temporary, path)
    except OSError as error:
        _remove_quietly(temporary)
        raise docx.DestinationError("cannot write %s: %s" % (path, error)) from error
    except Exception:
        _remove_quietly(temporary)
        raise

    print(
        "pdf.render: pages=%d blocks=%d notes=%d bytes=%d"
        % (len(pages), len(blocks), len(notes), size),
        file=sys.stderr,
    )
    return {"out": path, "pages": len(pages), "blocks": len(blocks), "notes": notes, "bytes": size}

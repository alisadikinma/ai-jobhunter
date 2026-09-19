"""Turn a tailored CV or cover letter into a `.docx` an ATS can actually read.

`tailor` stops at markdown, and nobody can attach a `.md` to a Workday form.
This module writes the OOXML by hand with `zipfile` and string templates,
because this project is standard-library only — no `python-docx`, no pip.

The document it writes is deliberately plain: single column, no tables, no
images, no header or footer content. Every one of those is a construct that a
resume parser either drops silently or scrambles, and a CV that renders
beautifully and parses into empty fields has failed at the only job it has.

Three functions, in the order `render` calls them:

- `ats_lint`   — finds what must not ship and what parses badly. Refuses only
                 on an unverified claim.
- `flatten`    — rewrites what parses badly into something that parses. Never
                 refuses; a construct it cannot fix is passed through, noted.
- `parse_blocks` — the supported markdown subset, as a flat block list.
"""

import html
import os
import re
import sys
import tempfile
import unicodedata
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ats  # noqa: E402


class DocxError(Exception):
    """Base for every refusal this module raises."""


class UnverifiedClaimError(DocxError):
    """The markdown still carries a claim the candidate never checked.

    Raised before a single byte is written. `README.md` promises that such a
    claim never reaches an outward document; until this existed the promise
    rested on model prose while the repository's other guarantees were
    properties of the code. Rendering is the last moment before a file exists
    on disk, so this is where the asymmetry closes.
    """

    def __init__(self, findings, source="<markdown>"):
        self.findings = list(findings)
        self.source = source
        detail = "; ".join(
            '%s:%d — "%s"' % (source, f["line"], f["text"]) for f in self.findings
        )
        super().__init__(
            "refused to render: %d unverified claim(s) still in the markdown. "
            "Verify the claim and remove the marker, or pass --allow-unverified "
            "to render it anyway. %s" % (len(self.findings), detail)
        )


# --- the markdown subset -------------------------------------------------
#
# Deliberately small. Every construct this recognises maps onto exactly one
# paragraph style in the table below; anything else becomes a paragraph, which
# is the one outcome that can never corrupt a document.

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_EMPTY_HEADING_RE = re.compile(r"^#{1,3}\s*$")
# Leading whitespace is accepted although `flatten` already brings every
# bullet to column 0. A nested bullet that somehow reached here and was read
# as a paragraph would print its own "- " marker into the document, which is
# exactly the leaked-markdown failure the eval cases look for.
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")
_EMPTY_BULLET_RE = re.compile(r"^\s*[-*]\s*$")

# A horizontal rule is a separator, not content. Rendered as text it would put
# a literal "---" in the middle of a CV.
_RULE_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")

# Inline emphasis is stripped, never rendered: Word carries weight in the run
# properties, so leaving the asterisks in would print them.
#
# Both emphasis patterns require a non-space character just inside the
# markers. Without that, the sentence "a * b * c" — a literal asterisk used as
# a separator, which real CVs do contain — would be read as italic text and
# silently lose both asterisks.
_BOLD_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.S)
_ITALIC_RE = re.compile(r"\*(?=\S)([^*]+?)(?<=\S)\*")
_CODE_RE = re.compile(r"`([^`]+)`")

# Underscore emphasis, which models write at least as often as the asterisk
# form. Both patterns refuse to start or end next to a word character, so
# `my_var_name` and `__init__` keep their underscores — a CV naming a Python
# dunder should not have it silently rewritten.
_BOLD_UNDERSCORE_RE = re.compile(
    r"(?<![A-Za-z0-9_])__(?=\S)(.+?)(?<=\S)__(?![A-Za-z0-9_])", re.S
)
_ITALIC_UNDERSCORE_RE = re.compile(
    r"(?<![A-Za-z0-9_])_(?=\S)([^_]+?)(?<=\S)_(?![A-Za-z0-9_])"
)

# Characters that are not there as far as a reader is concerned: zero-width
# and bidi formatting, the soft hyphen, and every control character the XML
# writer deletes on its way out.
#
# That last group is why this set and `_ILLEGAL_XML_RE` are described
# together. They were two different sets, and the gap between them was a hole
# straight through both layers of the gate: "[veri\x01fikasi]" matched no
# pattern here, and then `escape` — which runs AFTER the last check, inside
# `document_xml` — deleted the \x01 and reassembled a clean "[verifikasi]"
# in the shipped document. A character-removing transformation downstream of
# the gate can only ever do that.
#
# `_ILLEGAL_XML_RE` must therefore stay a SUBSET of what this removes. The
# two are built from different definitions — one from the XML grammar, one
# from Unicode categories — so the relation is pinned by a test rather than
# guaranteed by construction. Saying "by construction" here was an overclaim.

# What Unicode calls Default_Ignorable_Code_Point — characters a renderer is
# expected to show as nothing. `unicodedata` does not expose that property,
# so it is covered by the categories that contain it rather than by a
# hand-written range list, which is the thing that keeps going wrong here.
#
# `Cc` control, `Cf` format, `Cn` unassigned (the reserved ignorable blocks
# live there, and a codepoint nobody has defined cannot be meaningful text),
# `Cs` surrogate, `Me` enclosing mark, and `Mn` nonspacing mark. `Mn` is the
# one that matters most and the one an earlier version missed: every
# variation selector is `Mn`, as are the combining grapheme joiner and
# U+E0100's block. `Me` came next — U+20DD draws a ring around a letter and
# Calibri has no glyph for it at all. Removing marks from a PROJECTION is
# safe in the only direction that counts: deleting characters can reveal a
# marker that was hidden, never invent one that was not written.
_INVISIBLE_CATEGORIES = frozenset(("Cc", "Cf", "Cn", "Cs", "Me", "Mn"))

# The Hangul fillers are `Lo`, an enormous category that also holds every CJK
# ideograph, so these four are named rather than swept in.
_INVISIBLE_LETTERS = frozenset("\u115f\u1160\u3164\uffa0")

# Every space separator EXCEPT the ordinary one. NFKC folds U+00A0, the
# U+2000 block, U+202F, U+205F and U+3000 into U+0020, so each of them lands
# wherever a plain space lands — and U+200A HAIR SPACE is about half a point
# wide in Calibri, which is not a space a reader sees. U+0020 itself is left
# in place deliberately: the loose pattern already tolerates it between the
# letters, and removing it would silently turn "[ Assumption ]" into a match,
# which the plan pins as NOT one.
_INVISIBLE_SPACES = frozenset(
    ch
    for ch in map(chr, range(0x110000))
    if unicodedata.category(ch) in ("Zs", "Zl", "Zp") and ch != " "
)


def _remove_invisible(text):
    """Drop every character that renders as nothing to a reader.

    Used on the gate's projection only, never on text that reaches the
    document — a CV that writes "e" plus a combining acute still prints
    "é".
    """
    return "".join(
        ch
        for ch in text
        if ch not in _INVISIBLE_LETTERS
        and ch not in _INVISIBLE_SPACES
        and unicodedata.category(ch) not in _INVISIBLE_CATEGORIES
    )


def strip_inline(text):
    """Remove `**bold**`, `*italic*` and `` `code` `` markers, keeping text.

    Bold runs first: `\\*\\*x\\*\\*` would otherwise be seen by the italic
    pattern as an italic run wrapping `\\*x\\*`.
    """
    out = []
    position = 0
    # Emphasis is stripped OUTSIDE code spans only. A CV that names
    # `__init__` or writes `cat a | sed -e *` in backticks means those
    # characters literally, and markdown agrees: emphasis does not apply
    # inside a code span. Applying it everywhere turned `__init__` into
    # `init`.
    for match in _CODE_RE.finditer(text):
        out.append(_strip_emphasis(text[position : match.start()]))
        out.append(match.group(1))
        position = match.end()
    out.append(_strip_emphasis(text[position:]))
    return "".join(out)


def _strip_emphasis(text):
    """Bold before italic: `**x**` would otherwise read as italic around `*x*`."""
    text = _BOLD_RE.sub(r"\1", text)
    text = _BOLD_UNDERSCORE_RE.sub(r"\1", text)
    text = _ITALIC_RE.sub(r"\1", text)
    text = _ITALIC_UNDERSCORE_RE.sub(r"\1", text)
    return text


def parse_blocks(markdown):
    """The supported markdown subset as a flat list of block dicts.

    Every block carries `kind` (exactly one of `heading`, `paragraph`,
    `bullet`) and `text`; `level` (1, 2 or 3) appears on headings only.

    This function never refuses and never raises. Unrecognised syntax becomes
    a paragraph: refusing is `ats_lint`'s job and repairing is `flatten`'s, and
    a parser that also decides policy is a parser nobody can reason about.
    `####` is a paragraph for the same reason — the style table stops at
    level 3, so there is no style to render a level-4 heading with.

    A block whose text is empty after stripping is dropped rather than
    emitted: an empty heading renders as blank vertical space that looks like
    a layout bug, and carries nothing a parser could read.
    """
    blocks = []
    paragraph_lines = []
    # The bullet a wrapped line would continue, or None. A tailored CV wraps
    # its bullets at 72-ish columns, and without this every wrapped bullet
    # rendered as a bullet plus a stray un-bulleted paragraph under it.
    open_bullet = None

    def flush_paragraph():
        # A run of consecutive text lines is one paragraph, joined by spaces,
        # which is how markdown itself reads a soft line break.
        if paragraph_lines:
            text = strip_inline(" ".join(paragraph_lines)).strip()
            if text:
                blocks.append({"kind": "paragraph", "text": text})
            paragraph_lines.clear()

    # `splitlines` handles CRLF, LF and a lone CR alike, so Windows-authored
    # markdown needs no separate path.
    for raw_line in (markdown or "").splitlines():
        line = raw_line.rstrip()

        if not line.strip():
            flush_paragraph()
            open_bullet = None
            continue

        # Checked before the bullet rule: `---` also matches "a dash followed
        # by dashes", and a horizontal rule read as a bullet would print one.
        if _RULE_RE.match(line):
            flush_paragraph()
            open_bullet = None
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_paragraph()
            open_bullet = None
            text = strip_inline(heading.group(2)).strip()
            if text:
                blocks.append(
                    {
                        "kind": "heading",
                        "level": len(heading.group(1)),
                        "text": text,
                    }
                )
            continue

        if _EMPTY_HEADING_RE.match(line):
            flush_paragraph()
            open_bullet = None
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            flush_paragraph()
            open_bullet = None
            text = strip_inline(bullet.group(1)).strip()
            if text:
                blocks.append({"kind": "bullet", "text": text})
                open_bullet = blocks[-1]
            continue

        if _EMPTY_BULLET_RE.match(line):
            flush_paragraph()
            open_bullet = None
            continue

        # An indented line under a bullet is that bullet's wrapped remainder,
        # not a new paragraph. Only indented lines continue a bullet: an
        # unindented line is far more often the next real paragraph, and
        # swallowing one into the list item above loses a whole section.
        if open_bullet is not None and raw_line[:1].isspace():
            continuation = strip_inline(line.strip()).strip()
            if continuation:
                open_bullet["text"] = open_bullet["text"] + " " + continuation
            continue

        open_bullet = None
        paragraph_lines.append(line.strip())

    flush_paragraph()
    return blocks


# --- what must not ship, and what parses badly ---------------------------

# The vault convention, exact. Case is ignored because a CV written in a hurry
# capitalises inconsistently, but the inner spelling is not loosened: matching
# `[ verifikasi ]` or `[verifikasi-nanti]` would refuse on text that only
# resembles the marker, and a gate that cries wolf gets bypassed by habit.
_UNVERIFIED_RE = re.compile(r"\[(?:verifikasi|assumption)\b[^\]]*\]", re.I)


def _spaced(word):
    """`verifikasi` as a pattern tolerating whitespace between its letters."""
    return r"\s*".join(re.escape(ch) for ch in word)


# Applied to the PROJECTION only, never to the raw line. Two things put a
# space inside the word after the gate had already read it: a line wrapped
# mid-marker, whose continuation `parse_blocks` joins with a space, and a tag
# with spaces inside it — "[veri<span>  </span>fikasi]" — which the html
# cleaner collapses to "[veri fikasi]". Both shipped the claim.
# No `\s*` after the opening bracket, deliberately. "[ Assumption ]" stays
# NOT a match, as the plan pins it: a leading space is the author writing
# something else, while a space INSIDE the word is a transformation having
# split it. The two cases look similar and are not the same.
_UNVERIFIED_LOOSE_RE = re.compile(
    r"\[(?:" + _spaced("verifikasi") + r"|" + _spaced("assumption") + r")\b[^\]]*\]",
    re.I,
)

_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]*)\)")

# Stricter than `ats._TAG_RE` (`<[^>]+>`) on purpose, and only for DETECTING
# html — the stripping itself still delegates to `ats._clean_description`.
# `ats`'s pattern matches "< 200ms, throughput >" inside an ordinary sentence,
# and a CV that says "p95 < 200ms and > 1k rps" would have the middle of that
# sentence deleted as if it were a tag.
_HTML_TAG_RE = re.compile(
    r"<!--.*?-->|</?[A-Za-z][A-Za-z0-9]*(?:\s[^<>]*?)?\s*/?>", re.S
)

# A table separator row: pipe-delimited cells of dashes, with optional
# alignment colons. Requiring one is what keeps a sentence containing a
# literal "|" from being read as a table.
# One or more dash cells, so a single-column table is still a table. The
# pattern alone also matches a bare "---", which is a horizontal rule and,
# under a line containing a pipe, a setext heading underline — so `find_tables`
# additionally requires a pipe on the separator line itself.
_TABLE_SEP_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$"
)

# A bullet indented four or more spaces (or by a tab) is nested at least two
# levels deep. One level of nesting survives flattening; deeper does not.
_DEEP_BULLET_RE = re.compile(r"^(?: {4,}|\t+)\s*[-*]\s")


def _unmask(line):
    """The line as it will READ once every later stage has had its turn.

    The gate used to run on the raw markdown only, while `strip_inline` and
    the html cleaner ran afterwards — so a marker could reassemble itself
    downstream of the check. Three spellings got a claim into a shipped CV
    with the gate reporting clean:

        - Grew ARR to $9M [**verifikasi**]      emphasis stripped later
        - Cut spend 35% [`verifikasi`]          code span stripped later
        - <b>Impact</b> revenue &#91;verifikasi&#93;   entities decoded later

    Linting this projection as well as the raw line closes all three, and
    closes the ones nobody has thought of yet: any future transformation that
    removes characters can only make a marker MORE visible here, never less.

    Tags are removed with no separator on purpose. That is stricter than the
    html cleaner, which substitutes a space — `[verif<i>ikasi</i>]` rejoins
    into the marker here and is refused, rather than being caught by luck.
    Characters that render as nothing go the same way, whether they are
    zero-width spaces, control characters, variation selectors or the Hangul
    fillers: `[verifi<ZWSP>kasi]` and `[veri<VS1>fikasi]` both read to a
    human as the marker while matching no pattern of their own.

    Known limit, stated rather than hidden: a homoglyph from another script —
    Cyrillic "а" for Latin "a" — is not caught. NFKC folds compatibility
    forms, not confusables, and a confusables table is not in the standard
    library. It is an evasion nobody writes by accident. The gate is built
    against mistakes, not against an author deliberately smuggling a claim
    past themselves.
    """
    text = line
    previous = None
    # To a fixed point, because `&amp;#91;` decodes to `&#91;` and then to
    # `[`. One pass would leave the second spelling readable.
    while text != previous:
        previous = text
        text = html.unescape(text)
    # Compatibility normalisation folds the fullwidth forms — "［verifikasi］"
    # is indistinguishable from the marker on the page. It does NOT fold a
    # Cyrillic "а" into a Latin "a"; see the limit stated below.
    # Marks are removed BEFORE normalising as well as after. NFKC does not
    # only decompose — it COMPOSES, and composition destroys a match rather
    # than revealing one: "i" plus U+0301 becomes "í", a letter, and the Mn
    # is gone before anything can strip it. Seventeen combining marks hid a
    # marker that way.
    text = _remove_invisible(text)
    text = unicodedata.normalize("NFKC", text)
    text = _HTML_TAG_RE.sub("", text)
    text = _remove_invisible(text)
    return strip_inline(text)


def _is_table_row(line):
    return "|" in line and line.strip() != ""


def find_tables(lines):
    """Index ranges of `lines` that form a markdown table, header row first.

    Returns a list of `(start, stop)` half-open index pairs. A table is a row
    containing a pipe, immediately followed by a separator row, followed by
    any number of further pipe-carrying rows.

    One detector, used by both `ats_lint` and `flatten`, so the two can never
    disagree about what a table is.
    """
    tables = []
    index = 0
    while index < len(lines) - 1:
        separator = lines[index + 1]
        if (
            _is_table_row(lines[index])
            and "|" in separator
            and _TABLE_SEP_RE.match(separator)
        ):
            stop = index + 2
            while stop < len(lines) and _is_table_row(lines[stop]):
                stop += 1
            tables.append((index, stop))
            index = stop
            continue
        index += 1
    return tables


def ats_lint(markdown):
    """Findings for everything an ATS reads badly, plus the refusal trigger.

    Each finding is `{"line": <1-based>, "text": <the line>, "reason": <one
    of unverified-claim, table, image, deep-nesting, html>}`.

    Only `unverified-claim` refuses — `render` raises on it. The other four
    are what `flatten` repairs, reported here so the operator sees what the
    document contained before anything rewrote it.

    Every finding carries the line's own text, not just a count, because the
    person reading the refusal at 3am needs to see the claim itself.
    """
    lines = (markdown or "").splitlines()
    findings = []

    def add(index, reason):
        findings.append(
            {"line": index + 1, "text": lines[index].rstrip(), "reason": reason}
        )

    for start, _stop in find_tables(lines):
        add(start, "table")

    for index, line in enumerate(lines):
        # One finding per line even when the line carries two markers: the
        # unit of the refusal is the claim's line, and two findings pointing
        # at one line read as two separate problems.
        if _UNVERIFIED_RE.search(line) or _UNVERIFIED_LOOSE_RE.search(_unmask(line)):
            add(index, "unverified-claim")
        if _IMAGE_RE.search(line):
            add(index, "image")
        if _DEEP_BULLET_RE.match(line):
            add(index, "deep-nesting")
        if _HTML_TAG_RE.search(line):
            add(index, "html")

    findings.sort(key=lambda f: (f["line"], f["reason"]))
    return findings


def unverified_findings(markdown):
    """Just the findings that refuse — the gate `render` consults."""
    return [f for f in ats_lint(markdown) if f["reason"] == "unverified-claim"]


# --- repairing what an ATS reads badly -----------------------------------

_INLINE_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
_REFERENCE_LINK_RE = re.compile(r"\[[^\]]*\]\[[^\]]*\]")
_LEADING_WS_RE = re.compile(r"^[ \t]*")

# `ats._clean_description` returns the literal "N/A" for any result shorter
# than ten characters, because jobsync rejects a 1-9 character description.
# That floor belongs to jobsync, not to a CV: without this pad, the line
# "<b>Skills</b>" would come back as "N/A" and a heading would be replaced by
# a shrug. NUL is used because nothing in the cleaning pipeline touches it —
# it is not whitespace, not a tag, not an entity — and it is not legal in XML
# anyway, so a leak would be loud rather than silent.
_HTML_FLOOR_PAD = "\x00" * ats._MIN_DESCRIPTION_LEN


# Sentinels for the angle brackets that are NOT part of a tag. See
# `_protect_non_tags` — `ats._TAG_RE` is `<[^>]+>`, which happily eats the
# middle of "p95 < 200ms and > 1k rps".
_LT_SENTINEL = "\x01"
_GT_SENTINEL = "\x02"

# " ," and "( " after a tag became a space. A CV that reads "engineer ,
# Amsterdam" looks like a bug to the human who opens it.
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?%)\]])")
_SPACE_AFTER_OPEN_RE = re.compile(r"([(\[])\s+")


def _protect_non_tags(text):
    """Hide angle brackets that are not part of an html tag.

    `ats._clean_description` strips `<[^>]+>`, which is right for a job
    description scraped from a careers page and wrong for a CV line: it
    deletes everything between a less-than and the next greater-than, and
    "Keeps p95 < 200ms and > 1k rps" loses its middle. Only the spans the
    strict tag pattern matched are left visible to it.
    """
    spans = [match.span() for match in _HTML_TAG_RE.finditer(text)]
    out = []
    position = 0
    for start, stop in spans:
        before = text[position:start]
        out.append(
            before.replace("<", _LT_SENTINEL).replace(">", _GT_SENTINEL)
        )
        out.append(text[start:stop])
        position = stop
    tail = text[position:]
    out.append(tail.replace("<", _LT_SENTINEL).replace(">", _GT_SENTINEL))
    return "".join(out)


def strip_html(text):
    """`ats._clean_description`, minus two behaviours a CV cannot survive.

    The jobsync length floor ("N/A" below ten characters) is neutralised by a
    pad, and non-tag angle brackets are hidden behind sentinels first.
    Indentation is restored afterwards: the cleaner collapses all whitespace,
    and a nested bullet that lost its indent would stop being a bullet.
    """
    indent = _LEADING_WS_RE.match(text).group(0)
    cleaned = ats._clean_description(_protect_non_tags(text) + _HTML_FLOOR_PAD)
    cleaned = cleaned.replace("\x00", "")
    cleaned = cleaned.replace(_LT_SENTINEL, "<").replace(_GT_SENTINEL, ">")
    cleaned = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", cleaned)
    cleaned = _SPACE_AFTER_OPEN_RE.sub(r"\1", cleaned)
    return indent + cleaned.strip()


def _split_row(line):
    """The cells of a markdown table row, outer pipes discarded."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _flatten_table(lines, start, stop):
    """One BULLET per body row: `"- <header1>: <cell1> — <header2>: <cell2>"`.

    A row short of cells is padded rather than dropped — a missing cell is
    missing data, but dropping the row loses the data that IS there. Padding
    is trailing-only by construction, so a short row simply ends early.

    The bullet marker is not decoration. Emitted as bare lines, consecutive
    rows are a run of text with no blank line between them, and
    `parse_blocks` — correctly, by markdown's own rules — joins them into one
    paragraph. A three-row skills table came out of a real render as a single
    run-on sentence. A row of a table is a list item; marking it as one keeps
    each row its own block.
    """
    headers = _split_row(lines[start])
    out = []
    for row_line in lines[start + 2 : stop]:
        cells = _split_row(row_line)
        # Only the headers are padded. Padding the cells was inert — `zip`
        # stops at the shorter list and the filter below drops empty cells
        # anyway — and an inert line reads as load-bearing to the next person.
        # A short row is still never dropped: `filled` decides that, and the
        # branch below keeps a row even when every cell is empty.
        padded_headers = headers + [""] * (len(cells) - len(headers))

        # The label is the header of the first NON-EMPTY cell, not simply the
        # first header. Dropping empties before choosing the label let a row
        # like "|  | 5 |" render as "Skill: 5" — the CV then asserts that "5"
        # is a skill. That is corruption, not loss, and the worse of the two.
        filled = [
            (header, cell) for header, cell in zip(padded_headers, cells) if cell
        ]
        if not filled:
            # Every cell was empty. The row still held a position in the
            # table, so it is kept rather than silently dropped.
            out.append("- %s:" % headers[0] if headers else "-")
            continue

        # Every cell keeps its own header. Labelling only the first one left
        # "Skill: Python — 8 — 2026", so an ATS read two numbers with nothing
        # saying what they measured, and the years of experience the row
        # existed to state were gone.
        parts = [
            "%s: %s" % (header, cell) if header else cell
            for header, cell in filled
        ]
        out.append("- %s" % " — ".join(parts))
    return out


def flatten(markdown):
    """Rewrite what an ATS parses badly into something it parses.

    Returns `(flattened_markdown, notes)`. `notes` is a list of human lines
    naming every transformation applied, printed to stderr by the CLI so the
    operator sees what changed without diffing two files.

    This function never refuses — that is the whole distinction from
    `ats_lint`. A construct it cannot repair is passed through and noted.
    Every note carries the line number from the ORIGINAL markdown, so it
    still points at something the author can find after the rewrite has
    shifted every line below it.
    """
    lines = (markdown or "").splitlines()
    notes = []

    # Tables first, and line-wise: a table is the one construct that spans
    # more than one line, so every later transformation can be per-line.
    # Each output line keeps the original line number it came from.
    numbered = []
    table_ranges = find_tables(lines)
    consumed = set()
    for start, stop in table_ranges:
        consumed.update(range(start, stop))
    table_starts = {start: (start, stop) for start, stop in table_ranges}

    for index, line in enumerate(lines):
        if index in table_starts:
            start, stop = table_starts[index]
            rows = _flatten_table(lines, start, stop)
            for row in rows:
                numbered.append((index, row))
            if rows:
                notes.append(
                    "line %d: table flattened to %d line(s)" % (index + 1, len(rows))
                )
            else:
                notes.append(
                    "line %d: table had no body rows, dropped" % (index + 1)
                )
            continue
        if index in consumed:
            continue
        numbered.append((index, line))

    out = []
    for index, line in numbered:
        number = index + 1

        removed = _HTML_TAG_RE.findall(line)
        if removed:
            line = strip_html(line)
            # Naming what was removed, not just that something was. A phrase
            # like "<team lead>" is indistinguishable from a tag, and the
            # operator needs to see that the sentence lost those words.
            notes.append(
                "line %d: inline html stripped (%s)"
                % (number, ", ".join(sorted(set(removed))))
            )

        images = _IMAGE_RE.findall(line)
        if images:
            line = _IMAGE_RE.sub("", line)
            for source in images:
                notes.append("line %d: image removed (%s)" % (number, source or "no src"))

        if _REFERENCE_LINK_RE.search(line):
            notes.append(
                "line %d: reference-style link left as written — out of scope" % number
            )

        if _INLINE_LINK_RE.search(line):
            line = _INLINE_LINK_RE.sub(_rewrite_link, line)
            notes.append("line %d: link rewritten as text (url)" % number)

        if _DEEP_BULLET_RE.match(line):
            # One level, not zero: a nested bullet still reads as a
            # sub-point, and `parse_blocks` renders it as an ordinary bullet
            # either way.
            line = "  " + line.lstrip()
            notes.append("line %d: nesting flattened to one level" % number)

        # A line that held nothing but an image is now empty. Keeping it as a
        # blank line is correct — it separates the paragraphs around it.
        out.append(line.rstrip())

    # Tables are found in a first pass over the whole document, so their
    # notes would otherwise all precede notes about earlier lines. Sorted by
    # the number each note names, a reader can follow them down the file.
    notes.sort(key=_note_line_number)
    return "\n".join(out) + ("\n" if out else ""), notes


_NOTE_LINE_RE = re.compile(r"^line (\d+):")


def _note_line_number(note):
    match = _NOTE_LINE_RE.match(note)
    return int(match.group(1)) if match else 0


def _rewrite_link(match):
    """`[text](url)` → `text (url)`, because an ATS keeps neither reliably."""
    text = match.group(1).strip()
    url = match.group(2).strip()
    if not text:
        return url
    if not url or text == url:
        return text
    return "%s (%s)" % (text, url)


# --- the OOXML writer ----------------------------------------------------

class DestinationError(DocxError):
    """The destination cannot be written — missing directory, or no permission.

    A named class rather than a bare `OSError`, so the CLI reports a refusal
    instead of a crash wearing a refusal's clothes.
    """


class EmptyDocumentError(DocxError):
    """The markdown held nothing to render.

    An empty CV is never the intent. Writing a valid, blank `.docx` would be
    the worst outcome available: it fails silently, at the one moment the
    candidate believes the work is done.
    """


CONTENT_TYPES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    "</Types>"
)

ROOT_RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    "</Relationships>"
)

DOCUMENT_RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    "</Relationships>"
)

DOCUMENT_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:body>{body}"
    '<w:sectPr><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>'
    "</w:body></w:document>"
)

# `xml:space="preserve"` is mandatory. Without it Word collapses leading and
# trailing spaces, and two bullets can merge visually.
PARAGRAPH_XML = (
    '<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
    '<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'
)

# Fixed, not configurable. Every style option is a new way to produce a CV
# that fails to parse, and the candidate cannot tell which one did it.
STYLES = {
    ("heading", 1): ("Heading1", 32, True),
    ("heading", 2): ("Heading2", 26, True),
    ("heading", 3): ("Heading3", 24, True),
    ("paragraph", None): ("Normal", 22, False),
    ("bullet", None): ("ListParagraph", 22, False),
}

# A literal glyph, not a numbering definition. Real list formatting needs a
# sixth part (`word/numbering.xml`) and is a routine source of resume-parser
# garbage; a bullet character is plain text that every parser reads as text.
BULLET_GLYPH = "• "

# Every timestamp fixed, so rendering the same markdown twice produces the
# same bytes. The committed eval sample can then be regenerated and diffed
# rather than taken on trust.
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)

# XML 1.0 forbids most control characters outright — a stray one makes the
# document unopenable rather than merely ugly.
# The complement of XML 1.0's `Char` production, rather than a list of
# control characters somebody thought of. The list version allowed U+FFFF
# through: one of those in ordinary CV text produced a `.docx` that no
# parser can open, and `render-docx` reported success with a plausible byte
# count. Surrogates and the two noncharacters are forbidden too, and only
# the grammar knows the whole set.
_ILLEGAL_XML_RE = re.compile(
    "[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]"
)


def escape(text):
    """XML-escape, ampersand first.

    Escaping `&` last would double-escape the entities the other two
    produced, and the reader would see "&amp;lt;" on the page.
    """
    text = _ILLEGAL_XML_RE.sub("", text)
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def _style_for(block):
    return STYLES[(block["kind"], block.get("level"))]


def styles_xml():
    """`word/styles.xml` built from the one style table above."""
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">',
        "<w:docDefaults><w:rPrDefault><w:rPr>"
        '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
        '<w:sz w:val="22"/><w:szCs w:val="22"/>'
        "</w:rPr></w:rPrDefault></w:docDefaults>",
    ]
    for style_id, half_points, bold in sorted(set(STYLES.values())):
        default = ' w:default="1"' if style_id == "Normal" else ""
        indent = (
            '<w:ind w:left="360"/>' if style_id == "ListParagraph" else ""
        )
        parts.append(
            '<w:style w:type="paragraph"%s w:styleId="%s">'
            '<w:name w:val="%s"/>'
            "<w:pPr>%s</w:pPr>"
            "<w:rPr>"
            '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
            "%s"
            '<w:sz w:val="%d"/><w:szCs w:val="%d"/>'
            "</w:rPr></w:style>"
            % (
                default,
                style_id,
                style_id,
                indent,
                "<w:b/>" if bold else "",
                half_points,
                half_points,
            )
        )
    parts.append("</w:styles>")
    return "".join(parts)


def document_xml(blocks):
    """`word/document.xml` — the body is a flat run of `<w:p>` elements."""
    body = []
    for block in blocks:
        style_id, _size, _bold = _style_for(block)
        text = block["text"]
        if block["kind"] == "bullet":
            text = BULLET_GLYPH + text
        body.append(PARAGRAPH_XML.format(style=style_id, text=escape(text)))
    return DOCUMENT_XML.format(body="".join(body))


def render(markdown, path, allow_unverified=False, source=None):
    """Write `markdown` to `path` as an ATS-readable `.docx`.

    The order is the whole design: lint, then refuse, then repair, then
    parse, then write. Nothing touches the filesystem until the refusal has
    had its chance, so a refused render leaves no file — not a truncated one,
    not a stale one, none.

    Returns `{"out", "blocks", "notes", "bytes"}`. Raises
    `UnverifiedClaimError` unless `allow_unverified`, and
    `EmptyDocumentError` when there is nothing to write.
    """
    label = source or os.path.basename(path) or "<markdown>"

    unverified = unverified_findings(markdown)
    if unverified and not allow_unverified:
        raise UnverifiedClaimError(unverified, label)

    flattened, notes = flatten(markdown)
    blocks = parse_blocks(flattened)

    # The last word, on the text that will actually be written. `_unmask`
    # anticipates the transformations that exist today; this catches any that
    # arrive later, on the only string that matters — the one the employer
    # reads. A gate defended in one place is a gate one refactor from gone.
    # Joined two ways. A character that `splitlines` treats as a line break —
    # a vertical tab, a form feed, U+2028 — splits "[verifikasi]" across two
    # blocks, and neither half matches anything. Concatenating without a
    # separator puts the marker back together. It cannot raise a false alarm
    # unless one block ends mid-marker and the next begins mid-marker.
    rendered = [block["text"] for block in blocks]
    residual = unverified_findings("\n".join(rendered)) or unverified_findings(
        "".join(rendered)
    )
    if residual and not allow_unverified:
        raise UnverifiedClaimError(
            residual, "%s (marker survived into the rendered text)" % label
        )

    if allow_unverified:
        stripped = _strip_markers(blocks)
        if stripped:
            # The claim stays; the marker does not. An override is a decision
            # to send the claim, never a decision to print the word
            # "[verifikasi]" on a document an employer reads. The count is
            # reported so the override is never silent.
            notes.append(
                "%d unverified marker(s) removed from the rendered text "
                "(--allow-unverified)" % stripped
            )

    if not blocks:
        raise EmptyDocumentError(
            "refused to render %s: the markdown holds no headings, "
            "paragraphs or bullets. An empty document is never the intent." % label
        )

    payload = {
        "[Content_Types].xml": CONTENT_TYPES_XML,
        "_rels/.rels": ROOT_RELS_XML,
        "word/_rels/document.xml.rels": DOCUMENT_RELS_XML,
        "word/styles.xml": styles_xml(),
        "word/document.xml": document_xml(blocks),
    }

    directory = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(directory):
        raise DestinationError(
            "cannot write %s: the directory %s does not exist" % (path, directory)
        )

    return _write_archive(path, payload, blocks, notes, directory)


def _write_archive(path, payload, blocks, notes, directory):
    """Write the parts to a temp file in `directory`, then `os.replace` it.

    The same atomic-write pattern `scripts/jobq.py::update_rows` uses. A
    failure halfway through leaves the temp file, never a half-written
    `.docx` at the destination — and a `.docx` that is half a ZIP is a file
    the candidate discovers is broken only when the employer does.
    """
    try:
        # Inside the guard: an unwritable directory fails HERE, and an
        # unguarded `mkstemp` would hand the CLI a bare `PermissionError` —
        # a crash wearing a refusal's clothes.
        handle, temporary = tempfile.mkstemp(suffix=".docx.tmp", dir=directory)
        os.close(handle)
    except OSError as error:
        raise DestinationError("cannot write %s: %s" % (path, error)) from error

    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, text in payload.items():
                info = zipfile.ZipInfo(name, date_time=_ZIP_DATE)
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, text.encode("utf-8"))
        size = os.path.getsize(temporary)
        os.replace(temporary, path)
    except OSError as error:
        _remove_quietly(temporary)
        raise DestinationError("cannot write %s: %s" % (path, error)) from error
    except Exception:
        _remove_quietly(temporary)
        raise

    # The three numbers that tell a reader whether the document is plausibly
    # complete, without opening it.
    print(
        "docx.render: blocks=%d notes=%d bytes=%d" % (len(blocks), len(notes), size),
        file=sys.stderr,
    )
    return {"out": path, "blocks": len(blocks), "notes": notes, "bytes": size}


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


# Collapses the double space a removed marker leaves mid-sentence.
_DOUBLE_SPACE_RE = re.compile(r"[ \t]{2,}")


def _strip_markers(blocks):
    """Remove `[verifikasi]` / `[Assumption]` from block text, in place.

    Only reached under `allow_unverified`. Returns how many blocks changed,
    so the caller can report it — an override that is invisible in the output
    is an override nobody reviews.
    """
    changed = 0
    for block in blocks:
        text = block["text"]
        # Substituting on the raw text removed only the spellings that happen
        # to be literal there. A marker written as html entities survived the
        # strip, printed the word "verifikasi" onto the page, and reported
        # nothing — the override went silent, which is the one thing it
        # promised not to do. Collapsing to the projection first makes the
        # removal cover exactly what the gate detects, by construction.
        if not _UNVERIFIED_RE.search(text) and _UNVERIFIED_LOOSE_RE.search(
            _unmask(text)
        ):
            text = _unmask(text)
        cleaned = _UNVERIFIED_LOOSE_RE.sub("", _UNVERIFIED_RE.sub("", text))
        if cleaned == block["text"]:
            continue
        cleaned = _DOUBLE_SPACE_RE.sub(" ", cleaned)
        cleaned = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", cleaned).strip()
        block["text"] = cleaned
        changed += 1
    return changed

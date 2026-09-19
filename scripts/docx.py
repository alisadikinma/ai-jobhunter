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

import os
import re
import sys

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


def strip_inline(text):
    """Remove `**bold**`, `*italic*` and `` `code` `` markers, keeping text.

    Bold runs first: `\\*\\*x\\*\\*` would otherwise be seen by the italic
    pattern as an italic run wrapping `\\*x\\*`.
    """
    text = _BOLD_RE.sub(r"\1", text)
    text = _ITALIC_RE.sub(r"\1", text)
    text = _CODE_RE.sub(r"\1", text)
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
_UNVERIFIED_RE = re.compile(r"\[(?:verifikasi|assumption)\]", re.I)

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
_TABLE_SEP_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")

# A bullet indented four or more spaces (or by a tab) is nested at least two
# levels deep. One level of nesting survives flattening; deeper does not.
_DEEP_BULLET_RE = re.compile(r"^(?: {4,}|\t+)\s*[-*]\s")


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
        if _is_table_row(lines[index]) and _TABLE_SEP_RE.match(lines[index + 1]):
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
        if _UNVERIFIED_RE.search(line):
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

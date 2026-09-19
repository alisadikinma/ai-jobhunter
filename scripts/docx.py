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

import re

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

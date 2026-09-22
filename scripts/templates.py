"""CV template loader and `check_cv`, the deterministic structural checker
that keeps a tailored CV on its chosen template's section list and order.

## Template files, and the comment block that describes them

Every CV template lives at `templates/cv/<name>.md` and opens with exactly
one HTML comment, machine-read by `load_cv_template` (never by anything that
also renders the file — `docx.flatten`'s multi-line comment strip removes
this whole block before a template reaches `pdf.render`/`docx.render`, so
none of its `name:`/`sections:` lines ever leak onto a page):

    <!-- gaspol-jobhunter cv-template
    name: technical
    for: engineering / AI / software individual contributors
    sections:
    - Professional Summary | Summary
    - Technical Skills | Skills
    - Work Experience | Professional Experience | Experience
    - Projects (optional)
    - Education
    - Certifications (optional)
    - Awards (optional)
    -->

Each `sections:` line is one canonical heading, optionally followed by
`|`-separated aliases, with a trailing `(optional)` (after the canonical
name or the last alias) marking the whole section optional. After the
comment, the file's own `## ` headings are expected to equal that list, in
that order — `check_cv` (below) enforces exactly that against a real CV.

## Module-name collision, resolved by `sys.path` order, not by this file

This repository also has a `templates/` directory at its root (the `.md`
files themselves) sitting next to `scripts/templates.py`. Every test module
inserts `scripts/` at the FRONT of `sys.path` before importing, which is
what makes `import templates` resolve to this regular module rather than a
namespace package assembled from the `templates/` directory — Python's
import system only ever falls back to a namespace package when no `sys.path`
entry holds a regular module or package for that name, regardless of which
entry comes first. `tests/test_templates.py` asserts this resolution
explicitly (`templates.__file__` ends with `scripts/templates.py`) rather
than assuming it holds.
"""

import os
import re

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates")

# Private so a test can point it at a scratch directory (`unittest.mock.patch`)
# to exercise error paths — a missing comment block, a malformed `sections:`
# line — without needing a broken file sitting in the real templates/cv/.
_CV_DIR = os.path.join(TEMPLATES_DIR, "cv")

_CV_HEADER_LINE = "<!-- gaspol-jobhunter cv-template"
_COMMENT_CLOSE_LINE = "-->"
_OPTIONAL_SUFFIX = "(optional)"

# H1: exactly one `#`, not `##`. The negative lookahead is what tells a
# name heading apart from a section heading — `#(?!#)` fails to match the
# first `#` of `## Education`.
_H1_RE = re.compile(r"^#(?!#)\s+\S")
# A section heading: exactly two `#`, not one and not three (the latter is
# the experience-entry skeleton, `### <Job title> — <Employer>`, which must
# never be mistaken for a section of its own).
_SECTION_HEADING_RE = re.compile(r"^##(?!#)\s+(.*)$")
_BULLET_RE = re.compile(r"^[ \t]*[-*][ \t]+")
# `\bI\b` alone would flag "I/O" — the slash sits at a word boundary too,
# since `/` is a non-word character. The lookahead is the fix, not a
# tightened `\b`: it excludes only the one case a plain word boundary can't,
# leaving "AI", "IoT" and "Mine" alone on the ordinary strength of `\b`
# (each has a word character, not a boundary, on at least one side of "I").
_PRONOUN_I_RE = re.compile(r"\bI\b(?!/)")
_PRONOUN_OTHER_RE = re.compile(r"\b(me|my|we|our)\b", re.IGNORECASE)


class TemplateError(Exception):
    """Base class for every error this module raises.

    Every message names the file (and, where the problem is line-specific,
    the line) so a refusal printed by the CLI points straight at the fix.
    """


def _normalize_heading(text):
    """Case- and whitespace-insensitive form used to match a `## ` heading
    against a template's canonical names and aliases."""
    return re.sub(r"\s+", " ", text.strip()).lower()


def _parse_section_line(text, path, line_no):
    """Parse one `sections:` list entry (`text` has the leading `- `
    already removed). Raises `TemplateError` naming `path` and `line_no` on
    an empty canonical name — the one shape that would otherwise produce a
    section nothing can ever match."""
    optional = False
    if text.endswith(_OPTIONAL_SUFFIX):
        optional = True
        text = text[: -len(_OPTIONAL_SUFFIX)].rstrip()

    parts = [part.strip() for part in text.split("|")]
    name = parts[0]
    aliases = parts[1:]
    if not name or any(alias == "" for alias in aliases):
        raise TemplateError(
            "%s:%d: malformed sections line (empty section or alias name)"
            % (path, line_no)
        )
    return {"name": name, "aliases": aliases, "optional": optional}


def _parse_cv_template_text(text, path):
    """Parse the `<!-- gaspol-jobhunter cv-template ... -->` comment block
    at the start of `text` into `{"name", "for", "sections"}`.

    Only the comment block is parsed here — the body after it (`# <name>`,
    the contact line, the `## ` sections themselves) is what `check_cv`
    reads back out, and deliberately isn't re-derived or cross-checked here:
    the two stay independent so `check_cv` genuinely verifies the file
    rather than restating what this function already assumed.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != _CV_HEADER_LINE:
        raise TemplateError(
            "%s: does not open with the '%s' comment block" % (path, _CV_HEADER_LINE)
        )

    name = None
    for_desc = None
    sections = []
    in_sections = False
    closed = False

    for offset, raw in enumerate(lines[1:], start=2):
        stripped = raw.strip()
        if stripped == _COMMENT_CLOSE_LINE:
            closed = True
            break
        if stripped == "":
            continue
        if stripped.startswith("name:"):
            name = stripped[len("name:") :].strip()
            in_sections = False
        elif stripped.startswith("for:"):
            for_desc = stripped[len("for:") :].strip()
            in_sections = False
        elif stripped == "sections:":
            in_sections = True
        elif in_sections and stripped.startswith("-"):
            sections.append(_parse_section_line(stripped[1:].strip(), path, offset))
        else:
            raise TemplateError(
                "%s:%d: unrecognised line inside the cv-template comment: %r"
                % (path, offset, raw)
            )

    if not closed:
        raise TemplateError(
            "%s: cv-template comment block is never closed with '-->'" % path
        )
    if not name:
        raise TemplateError("%s: cv-template comment is missing 'name:'" % path)
    if not sections:
        raise TemplateError(
            "%s: cv-template comment has no 'sections:' entries" % path
        )
    return {"name": name, "for": for_desc or "", "sections": sections}


def list_cv_templates():
    """Sorted template names from `templates/cv/*.md` (the filename stem,
    e.g. `templates/cv/hybrid.md` -> `"hybrid"`)."""
    if not os.path.isdir(_CV_DIR):
        raise TemplateError("cv template directory missing: %s" % _CV_DIR)
    return sorted(
        os.path.splitext(fname)[0]
        for fname in os.listdir(_CV_DIR)
        if fname.endswith(".md")
    )


def load_cv_template(name):
    """Load and parse `templates/cv/<name>.md`.

    Returns `{"name", "for", "sections": [{"name", "aliases", "optional"}]}`.
    Raises `TemplateError` for an unknown name, a file without the comment
    block, or a malformed `sections:` line (naming the file and line).
    """
    path = os.path.join(_CV_DIR, "%s.md" % name)
    if not os.path.isfile(path):
        raise TemplateError("unknown CV template %r (no file at %s)" % (name, path))
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    return _parse_cv_template_text(text, path)

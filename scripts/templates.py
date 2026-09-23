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


def _finding(rule, line, message):
    return {"rule": rule, "line": line, "message": message}


def _build_section_lookup(sections):
    """Map every normalized canonical name AND alias to
    `(template_order_index, canonical_name)`. A heading in the CV matches a
    section the moment it normalizes to any name in that section's list —
    canonical or alias, case- and whitespace-insensitive."""
    lookup = {}
    for index, section in enumerate(sections):
        for candidate in [section["name"]] + section["aliases"]:
            lookup[_normalize_heading(candidate)] = (index, section["name"])
    return lookup


def check_cv(markdown, name):
    """Check `markdown` against the CV template `name`'s section list.

    Returns a list of `{"rule", "line", "message"}` findings, sorted by
    line (1-based, same numbering as the input). Rule ids: `no-name`,
    `no-contact`, `unknown-section`, `order`, `duplicate-section`,
    `missing-section`, `pronoun`, `chronology`. Raises `TemplateError` for an unknown
    `name`, via `load_cv_template`.
    """
    template = load_cv_template(name)
    sections = template["sections"]
    lookup = _build_section_lookup(sections)

    lines = markdown.splitlines()
    findings = []

    # --- name (H1) and the contact line directly under it -----------------
    h1_line = None
    for index, line in enumerate(lines, start=1):
        if _H1_RE.match(line):
            h1_line = index
            break

    if h1_line is None:
        findings.append(
            _finding("no-name", 1, "no top-level '# <name>' heading found")
        )
    else:
        # Blank lines are skipped; the first non-blank line after the name
        # must be plain text, not another heading — and it has to exist at
        # all, which a template cut off right after its name heading would
        # fail too.
        cursor = h1_line  # 0-based index of the line right after the H1
        while cursor < len(lines) and lines[cursor].strip() == "":
            cursor += 1
        if cursor >= len(lines):
            findings.append(
                _finding(
                    "no-contact",
                    h1_line + 1,
                    "no contact line found after the name heading",
                )
            )
        elif _H1_RE.match(lines[cursor]) or _SECTION_HEADING_RE.match(lines[cursor]):
            findings.append(
                _finding(
                    "no-contact",
                    cursor + 1,
                    "a heading appears immediately after the name heading, "
                    "with no contact line in between",
                )
            )

    # --- sections: unknown / order / duplicate -----------------------------
    seen_canonical = set()
    last_index = -1
    for index, line in enumerate(lines, start=1):
        match = _SECTION_HEADING_RE.match(line)
        if not match:
            continue
        heading_text = match.group(1).strip()
        found = lookup.get(_normalize_heading(heading_text))
        if found is None:
            findings.append(
                _finding(
                    "unknown-section",
                    index,
                    "'%s' does not match any section of the %s template"
                    % (heading_text, name),
                )
            )
            continue
        section_index, canonical = found
        if canonical in seen_canonical:
            findings.append(
                _finding(
                    "duplicate-section",
                    index,
                    "'%s' appears more than once" % canonical,
                )
            )
        else:
            seen_canonical.add(canonical)
        if section_index < last_index:
            findings.append(
                _finding(
                    "order",
                    index,
                    "'%s' is out of order for the %s template" % (canonical, name),
                )
            )
        else:
            last_index = max(last_index, section_index)

    # --- missing required sections ------------------------------------------
    # No heading means no line to point at; the line after the last line of
    # the input is the deterministic, unambiguous convention used here —
    # "this section belongs somewhere in the document, and isn't".
    missing_line = len(lines) + 1
    for section in sections:
        if not section["optional"] and section["name"] not in seen_canonical:
            findings.append(
                _finding(
                    "missing-section",
                    missing_line,
                    "required section '%s' is missing" % section["name"],
                )
            )

    # --- first-person pronouns in bullet lines ------------------------------
    for index, line in enumerate(lines, start=1):
        if not _BULLET_RE.match(line):
            continue
        if _PRONOUN_I_RE.search(line) or _PRONOUN_OTHER_RE.search(line):
            findings.append(
                _finding("pronoun", index, "first-person pronoun in a bullet line")
            )

    findings.extend(_check_reverse_chronological(lines))
    findings.sort(key=lambda finding: finding["line"])
    return findings


_MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}
_DATE_RANGE_RE = re.compile(
    r"^(?P<m>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (?P<y>\d{4}) [\u2013-] (?:[A-Z][a-z]{2} \d{4}|Present)\b"
)


def _check_reverse_chronological(lines):
    """A job entry may not start later than the entry above it.

    Every template says work history is reverse-chronological. Ordering by how
    relevant a role is to one JD hides the current role and reads as a gap, so
    it is a finding, not a style choice.
    """
    findings = []
    previous = None
    for number, line in enumerate(lines, start=1):
        match = _DATE_RANGE_RE.match(line.strip())
        if not match:
            continue
        start = (int(match["y"]), _MONTHS[match["m"]])
        if previous is not None and start > previous[0]:
            findings.append(
                _finding(
                    "chronology",
                    number,
                    "entry starting %s %s is listed below one starting %s %s; work history must be newest first"
                    % (match["m"], match["y"], previous[1], previous[2])
                )
            )
        previous = (start, match["m"], match["y"])
    return findings


# --- cover-letter format and check_letter -----------------------------------
#
# One file, `templates/cover-letter.md`, rather than one per level — the
# levels differ only in word-count band, not in structure, so `letter_levels`
# reads all three bands out of the same comment block `check_letter` also
# reads its sign-off list from.

_LETTER_HEADER_LINE = "<!-- gaspol-jobhunter cover-letter"
_LETTER_LEVELS_KEY = "levels:"
_LETTER_SIGN_OFFS_PREFIX = "sign-offs:"
_LEVEL_LINE_RE = re.compile(r"^(\S+)\s+(\d+)-(\d+)$")

# `Dear ` at the start of a line, after stripping leading whitespace — the
# salutation the contract requires, whatever name or team title follows it.
_SALUTATION_RE = re.compile(r"^Dear\s")
# The two dead phrases anywhere in the file, not just on the salutation line
# — a "Dear Sir or Madam" that also happens to start with "Dear " would
# otherwise satisfy `_SALUTATION_RE` and never get flagged at all.
_GENERIC_SALUTATION_RE = re.compile(
    r"to whom it may concern|dear sir or madam", re.IGNORECASE
)
# Anchored at the start of any SENTENCE, not just the paragraph: spec §6 says
# no body sentence starts with it, and "Hello there. I am writing to apply"
# passed the paragraph-only check (plan-verifier, AJOB-4). "The service I am
# writing about" stays clean — the phrase must follow a sentence boundary.
_WEAK_OPENING_RE = re.compile(r"(?:^|[.!?]\s+)I am writing\b", re.IGNORECASE)
_WEAK_CLOSE_RE = re.compile(r"hope to hear from you", re.IGNORECASE)
_TOKEN_RE = re.compile(r"\S+")


def _names(text, name):
    """Whether `text` names `name` as a whole phrase, ignoring case.

    A substring test counted "metadata" as naming "Meta" and "harmony" as
    naming "Arm" — a false pass (gaspol-review, AJOB-4). Lookarounds rather
    than `\\b`, so a name ending in punctuation ("C++") still matches.
    """
    pattern = r"(?<!\w)" + re.escape(name.strip()) + r"(?!\w)"
    return re.search(pattern, text, re.IGNORECASE) is not None

# Private, like `_CV_DIR`, so a test can point it at a scratch file
# (`unittest.mock.patch`) to exercise error paths without a broken file
# sitting in the real `templates/cover-letter.md`.
_LETTER_PATH = os.path.join(TEMPLATES_DIR, "cover-letter.md")


def _parse_letter_template_text(text, path):
    """Parse the `<!-- gaspol-jobhunter cover-letter ... -->` comment block
    at the start of `text` into `{"levels": {name: (low, high)}, "sign_offs":
    [...]}`. Mirrors `_parse_cv_template_text`'s shape and error style, for
    a different pair of keys (`levels:`/`sign-offs:` instead of
    `name:`/`for:`/`sections:`)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != _LETTER_HEADER_LINE:
        raise TemplateError(
            "%s: does not open with the '%s' comment block" % (path, _LETTER_HEADER_LINE)
        )

    levels = {}
    sign_offs = None
    in_levels = False
    closed = False

    for offset, raw in enumerate(lines[1:], start=2):
        stripped = raw.strip()
        if stripped == _COMMENT_CLOSE_LINE:
            closed = True
            break
        if stripped == "":
            continue
        if stripped == _LETTER_LEVELS_KEY:
            in_levels = True
            continue
        if stripped.startswith(_LETTER_SIGN_OFFS_PREFIX):
            in_levels = False
            value = stripped[len(_LETTER_SIGN_OFFS_PREFIX) :].strip()
            parts = [part.strip() for part in value.split("|")]
            if not value or any(part == "" for part in parts):
                raise TemplateError("%s:%d: malformed sign-offs line" % (path, offset))
            sign_offs = parts
            continue
        if in_levels and stripped.startswith("-"):
            entry = stripped[1:].strip()
            match = _LEVEL_LINE_RE.match(entry)
            if not match:
                raise TemplateError(
                    "%s:%d: malformed levels line: %r" % (path, offset, raw)
                )
            levels[match.group(1)] = (int(match.group(2)), int(match.group(3)))
            continue
        raise TemplateError(
            "%s:%d: unrecognised line inside the cover-letter comment: %r"
            % (path, offset, raw)
        )

    if not closed:
        raise TemplateError(
            "%s: cover-letter comment block is never closed with '-->'" % path
        )
    if not levels:
        raise TemplateError("%s: cover-letter comment has no 'levels:' entries" % path)
    if not sign_offs:
        raise TemplateError("%s: cover-letter comment is missing 'sign-offs:'" % path)
    return {"levels": levels, "sign_offs": sign_offs}


def _load_letter_format():
    if not os.path.isfile(_LETTER_PATH):
        raise TemplateError("cover-letter template missing: %s" % _LETTER_PATH)
    with open(_LETTER_PATH, "r", encoding="utf-8") as handle:
        text = handle.read()
    return _parse_letter_template_text(text, _LETTER_PATH)


def letter_levels():
    """Word-count bands for each cover-letter level, parsed from
    `templates/cover-letter.md`'s comment block.

    Returns `{"entry": (200, 250), "mid": (250, 400), "executive": (400,
    450)}` — the exact bounds live in the file; this only parses them.
    Raises `TemplateError` if the file is missing the comment block, never
    closes it, or a `levels:`/`sign-offs:` line is malformed.
    """
    return _load_letter_format()["levels"]


def _blocks(lines, start, end):
    """Blank-line-separated blocks of `lines[start:end]` (0-based, `end`
    exclusive), each as `(first_line_1_based, [line, ...])`.

    A block whose first line is itself a heading (`# ` or `## `) is dropped
    — `check_letter`'s contract calls the body "non-heading blocks", which
    matters if a user pastes a stray heading into the body by hand; the
    shipped template carries no heading between the salutation and the
    sign-off, so this path exists for that hand-edited case, not the
    template itself.
    """
    blocks = []
    current = []
    current_start = None
    for index in range(start, end):
        line = lines[index]
        if line.strip() == "":
            if current:
                blocks.append((current_start, current))
                current = []
                current_start = None
            continue
        if current_start is None:
            current_start = index + 1
        current.append(line)
    if current:
        blocks.append((current_start, current))
    return [
        (line_no, block_lines)
        for line_no, block_lines in blocks
        if not (_H1_RE.match(block_lines[0]) or _SECTION_HEADING_RE.match(block_lines[0]))
    ]


def _is_word_token(token):
    """A word: a whitespace-separated token containing at least one letter
    or digit — a lone "-" or "—" used as punctuation does not count."""
    return any(ch.isalnum() for ch in token)


def check_letter(markdown, level, company=None, role=None):
    """Check `markdown` against the cover-letter format for `level`.

    Returns a list of `{"rule", "line", "message"}` findings, sorted by
    line (1-based, same numbering as the input). Rule ids: `no-salutation`,
    `generic-salutation`, `no-sign-off`, `paragraphs`, `word-count`,
    `opening-company`, `opening-role`, `weak-opening`, `weak-close`.
    `company`/`role` are checked only when given (not `None`). Raises
    `TemplateError` for an unknown `level`, via `_load_letter_format`.
    """
    letter_format = _load_letter_format()
    levels = letter_format["levels"]
    sign_offs = letter_format["sign_offs"]
    if level not in levels:
        raise TemplateError(
            "unknown letter level %r (known: %s)" % (level, ", ".join(sorted(levels)))
        )
    low, high = levels[level]

    lines = markdown.splitlines()
    findings = []

    # --- generic salutation phrases, anywhere in the document --------------
    for index, line in enumerate(lines, start=1):
        if _GENERIC_SALUTATION_RE.search(line):
            findings.append(
                _finding("generic-salutation", index, "generic salutation phrase found")
            )

    # --- salutation line -----------------------------------------------------
    salutation_index = None  # 0-based index into `lines`
    for index, line in enumerate(lines):
        if _SALUTATION_RE.match(line.strip()):
            salutation_index = index
            break
    if salutation_index is None:
        findings.append(_finding("no-salutation", 1, "no line starting 'Dear ' found"))

    # --- sign-off line, searched after the salutation (or from the top if
    # there is none) ----------------------------------------------------------
    search_from = salutation_index + 1 if salutation_index is not None else 0
    sign_off_index = None  # 0-based
    for index in range(search_from, len(lines)):
        # Case-insensitive: "Best Regards," is the same sign-off, and a miss
        # here suppresses every body check until it is "fixed".
        if lines[index].strip().lower() in {s.lower() for s in sign_offs}:
            sign_off_index = index
            break
    if sign_off_index is None:
        findings.append(
            _finding(
                "no-sign-off",
                len(lines) + 1,
                "no sign-off line (%s) found after the salutation"
                % " | ".join(sign_offs),
            )
        )

    if salutation_index is None or sign_off_index is None:
        # Every remaining rule reads the body strictly between the two
        # boundary lines; without both there is nothing safe left to check.
        findings.sort(key=lambda finding: finding["line"])
        return findings

    body_blocks = _blocks(lines, salutation_index + 1, sign_off_index)
    anchor_line = body_blocks[0][0] if body_blocks else salutation_index + 2

    if len(body_blocks) != 4:
        findings.append(
            _finding(
                "paragraphs",
                anchor_line,
                "body has %d paragraph(s), expected exactly 4" % len(body_blocks),
            )
        )

    body_text = " ".join(" ".join(block_lines) for _line_no, block_lines in body_blocks)
    word_count = sum(1 for token in _TOKEN_RE.findall(body_text) if _is_word_token(token))
    if not (low <= word_count <= high):
        findings.append(
            _finding(
                "word-count",
                anchor_line,
                "body has %d words, outside the %s band (%d-%d)"
                % (word_count, level, low, high),
            )
        )

    if body_blocks:
        p1_line, p1_lines = body_blocks[0]
        p1_text = " ".join(p1_lines)
        if company and not _names(p1_text, company):
            findings.append(
                _finding(
                    "opening-company",
                    p1_line,
                    "opening paragraph does not name the company (%r)" % company,
                )
            )
        if role and not _names(p1_text, role):
            findings.append(
                _finding(
                    "opening-role",
                    p1_line,
                    "opening paragraph does not name the role (%r)" % role,
                )
            )

    for block_line, block_lines in body_blocks:
        block_text = " ".join(block_lines).strip()
        if _WEAK_OPENING_RE.search(block_text):
            findings.append(
                _finding("weak-opening", block_line, "a sentence opens with 'I am writing'")
            )
        if _WEAK_CLOSE_RE.search(block_text):
            findings.append(
                _finding(
                    "weak-close", block_line, "paragraph uses 'hope to hear from you'"
                )
            )

    findings.sort(key=lambda finding: finding["line"])
    return findings

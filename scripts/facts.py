"""User-verified facts a tailored CV or letter must not contradict.

`master-cv.md` is compiled from many sources (vault, LinkedIn PDF, sites) and
some of them are stale: an old email, a wrong start date. The user corrects
a fact once in `.jobhunter/profile/facts.toml`, and every `template-check
--facts` run then enforces it on the drafted document, whatever the compile
step picked up.

    [contact]
    email = "..."
    phone = "..."
    website = "www.example.com"

    [forbidden]
    strings = ["Jan 2025 – Present"]   # text that was wrong and must never come back
"""

import re

import tomllib

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_HEADER_LINES = 8


class FactsError(Exception):
    """Raised when the facts file is missing or malformed."""


def load(path):
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except OSError as exc:
        raise FactsError(f"cannot read facts file {path!r}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise FactsError(f"facts file {path!r} is not valid TOML: {exc}") from exc


def check(markdown, facts):
    """Return findings as `{"rule", "line", "message"}` dicts, like `templates.check_*`."""
    findings = []
    lines = markdown.split("\n")
    header = "\n".join(lines[:_HEADER_LINES])

    contact = facts.get("contact", {})
    for key in ("email", "phone", "website"):
        want = contact.get(key)
        if want and want not in header:
            findings.append(
                {"rule": "facts-contact", "line": 3, "message": f"contact line is missing the {key}: {want}"}
            )
    want_email = contact.get("email")
    if want_email:
        for found in _EMAIL_RE.findall(header):
            if found != want_email:
                findings.append(
                    {"rule": "facts-contact", "line": 3, "message": f"contact line has a different email: {found}"}
                )

    for bad in facts.get("forbidden", {}).get("strings", []):
        for n, line in enumerate(lines, 1):
            if bad in line:
                findings.append(
                    {"rule": "facts-forbidden", "line": n, "message": f"contains text the user marked wrong: {bad!r}"}
                )
    return findings

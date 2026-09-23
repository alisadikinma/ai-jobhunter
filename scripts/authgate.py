"""Work-authorization gate: spot postings the candidate cannot legally take.

Discover and score both need the same answer to "is this posting closed to
someone who lives abroad and needs sponsorship?", so it lives here once.
`classify(text)` returns `("closed", reason)` when the text states a hard
restriction, and `("unclear", None)` otherwise. It never returns `open`:
saying a company hires globally is a judgement the scorer makes from the
whole posting, not something a phrase list can settle.

The patterns are deliberately narrow. A false "closed" hides a real job, and
EEO boilerplate ("citizenship", "security clearance requirements" in a
fair-chance notice) is full of the same words the real restrictions use.
"""

import re

_CLOSED = [
    ("local employment only",
     r"local\s+(?:employment|candidates?|hires?|talents?)\s+only|open\s+(?:to|for)\s+locals?\s+only|locals?\s+only"),
    ("citizens only",
     r"(?:singapore|malaysian?|u\.?s\.?|united states|uk|british|canadian|australian|indian)\s+citizens?"
     r"(?:\s+(?:or|and)\s+(?:permanent\s+residents?|PRs?))?\s+(?:only|required)"
     r"|must\s+be\s+(?:a\s+)?(?:singapore|u\.?s\.?|united states|uk|british|canadian)\s+citizen"
     r"|(?:singapore|u\.?s\.?)\s+citizen[^.]{0,60}(?:clearance|eligible)"
     r"|citizens?\s+and\s+(?:permanent\s+residents?|PRs?)\s+only"),
    ("security clearance required",
     r"(?:active|current|valid)\s+(?:\w+\s+)?(?:security\s+)?clearance"
     r"|(?:ability|able|eligible)\s+to\s+(?:obtain|hold|maintain)[^.]{0,40}clearance"
     r"|must\s+(?:have|hold|obtain)[^.]{0,30}clearance"
     r"|security\s+clearance\s+(?:is\s+)?required"),
    ("no visa sponsorship",
     r"(?:do(?:es)?\s+not|cannot|can't|won't|will\s+not|unable\s+to|not\s+able\s+to)\s+"
     r"(?:offer|provide|consider|support|sponsor)[^.]{0,80}?(?:visa\s+)?sponsorship"
     r"|no\s+(?:visa\s+)?sponsorship|will\s+not\s+sponsor|unable\s+to\s+sponsor"
     r"|without\s+(?:the\s+need\s+for\s+)?(?:visa\s+)?sponsorship"
     r"|(?:not|unable)[^.]{0,40}candidates\s+who[^.]{0,60}require[^.]{0,20}visa\s+sponsorship"),
    ("must already hold work authorization",
     r"must\s+(?:already\s+)?(?:be\s+)?(?:legally\s+)?authori[sz]ed\s+to\s+work\s+in\s+the\s+(?:u\.?s\.?|united states)"
     r"|already\s+have\s+authori[sz]ation\s+to\s+work\s+in\s+the\s+(?:u\.?s\.?|united states)"),
    ("US-based citizen or resident required",
     r"based\s+in\s+(?:the\s+)?(?:us|u\.s\.|united states)\s*[-,:]\s*citizen"),
]
_COMPILED = [(reason, re.compile(pat, re.IGNORECASE)) for reason, pat in _CLOSED]


def classify(text):
    """Return `("closed", "<reason>: <quote>")` or `("unclear", None)`."""
    flat = re.sub(r"\s+", " ", text or "")
    for reason, rx in _COMPILED:
        m = rx.search(flat)
        if m:
            return "closed", f"{reason}: \"{flat[max(0, m.start() - 20):m.end() + 20].strip()}\""
    return "unclear", None


def split_closed(rows):
    """Split queue rows into `(kept, blocked)`; `blocked` is `[(row, reason)]`."""
    kept, blocked = [], []
    for row in rows:
        status, reason = classify(row.get("jobDescription") or "")
        if status == "closed":
            blocked.append((row, reason))
        else:
            kept.append(row)
    return kept, blocked

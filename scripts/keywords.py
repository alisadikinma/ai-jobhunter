"""JD-vs-CV keyword overlap report.

`coverage(jd_text, cv_text)` extracts 1-3 word candidate terms from a job
description, ranks them by how often they occur in the JD, and reports which
of them also appear — as whole terms — in a CV. `render(report)` turns that
into the `keyword-report.md` body.

## This is a keyword overlap report, not an ATS score

Per spec section 6 ("Tailoring — one document set per job, always"): ATS
vendors parse differently from each other and no local computation can
honestly claim to predict what any of them would score. This module never
computes, stores or prints a number called an "ATS score", and `render`'s
heading says "keyword overlap report" — never "ATS score" — enforced by
`tests/test_keywords.py`.

## Whole-term matching, not substring matching

The single most important behaviour here: `java` appearing in a CV must never
mark `javascript` "covered", and vice versa. A false "covered" hides a real
gap from the candidate. This module never uses substring containment
(`"java" in cv_text`) to decide coverage. Instead both the JD and the CV are
tokenised with the same word-boundary regex, and a JD term is "covered" only
when that exact token (or exact multi-word phrase) also appears in the CV's
own extracted term set. Because the tokenizer matches maximal runs of word
characters, "javascript" tokenizes to one token, `javascript` — never to
`java` plus a discarded remainder — so set-membership comparison is
substring-safe by construction.

## Extraction

1. Lower-case the text.
2. Split into tokens on non-word characters, except that a single hyphen
   between two word runs keeps them as one token (`end-to-end` stays one
   term, never three).
3. Drop stopwords (`_STOPWORDS`, a fixed closed-class function-word list:
   articles, pronouns, prepositions, conjunctions, auxiliary/modal verbs and
   wh-words — not a domain-specific list, so ordinary content words like
   "experience" are never silently discarded).
4. Within each run of consecutive non-stopword tokens, build every
   contiguous 1-, 2- and 3-word phrase as a candidate term. A term repeated
   many times in the JD is still one entry in the term lists — its JD
   occurrence count only drives where it ranks.

`\\w` in Python's `re` module is Unicode-aware by default (no `re.ASCII`
flag is used here), so accented text and CJK text tokenize as ordinary word
characters instead of being dropped or mis-split.
"""

import re
from collections import Counter

_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "if", "then", "else", "when",
        "while", "as", "of", "at", "by", "for", "with", "about", "against",
        "between", "into", "through", "during", "before", "after", "above",
        "below", "to", "from", "up", "down", "in", "out", "on", "off",
        "over", "under", "again", "further", "once", "here", "there", "all",
        "both", "each", "few", "more", "most", "other", "some", "such",
        "no", "nor", "not", "only", "own", "same", "so", "than", "too",
        "very", "s", "t", "can", "will", "just", "don", "now", "is", "are",
        "was", "were", "be", "been", "being", "have", "has", "had",
        "having", "do", "does", "did", "doing", "would", "should", "could",
        "ought", "i", "me", "my", "myself", "we", "our", "ours",
        "ourselves", "you", "your", "yours", "yourself", "yourselves",
        "he", "him", "his", "himself", "she", "her", "hers", "herself",
        "it", "its", "itself", "they", "them", "their", "theirs",
        "themselves", "what", "which", "who", "whom", "this", "that",
        "these", "those", "am", "shall", "might", "must", "any", "because",
        "until", "across", "within", "without", "per", "via", "etc",
    }
)

# `[^\W_]+` alone drops the symbols that ARE the name: "C++" and "C#" both
# collapse to the token "c", and a CV mentioning a grade of "C" then marks
# both as covered — the exact false "covered" this module exists to prevent.
# `.NET` collapses to "net" the same way. A trailing run of + or # and an
# internal dot are therefore part of the token.
# A leading dot is part of the name in ".NET"; without it the token is
# "net" and a CV saying "net profit" marks .NET covered. The dot is only
# taken when a word character follows, so ordinary sentence punctuation
# never starts a token.
_WORD = r"\.?[^\W_]+(?:\.[^\W_]+)*[+#]*"
_TOKEN_RE = re.compile(rf"{_WORD}(?:-{_WORD})*")
_MAX_PHRASE_LEN = 3

# A real job description yields hundreds of terms, most of them three-word
# fragments nobody reads. Measured on one real Greenhouse posting: 686
# missing terms across 699 lines of markdown. A report that long is not read
# at all, so the ranked head is the whole value.
DEFAULT_TOP_N = 40


class KeywordsError(Exception):
    """Base class for every error this module raises."""


def _tokenize(text):
    return _TOKEN_RE.findall(text.lower())


def _runs_without_stopwords(tokens):
    """Yield each maximal run of consecutive non-stopword tokens.

    Phrases are only built within a run, so a stopword always breaks a
    candidate phrase rather than being folded into one (e.g. "increase the
    GDP" never becomes a 3-word candidate spanning "the").
    """
    run = []
    for tok in tokens:
        if tok in _STOPWORDS:
            if run:
                yield run
                run = []
        else:
            run.append(tok)
    if run:
        yield run


def _extract_terms(text):
    """Return (phrase_counts, extracted_count, survived_count) for `text`.

    `extracted_count` is every token the tokenizer found, before stopword
    removal. `survived_count` is how many of those tokens are not
    stopwords. `phrase_counts` is a `Counter` mapping each candidate 1-3
    word phrase to how many times it occurs in `text`.
    """
    tokens = _tokenize(text)
    extracted_count = len(tokens)
    survived_count = sum(1 for tok in tokens if tok not in _STOPWORDS)

    counts = Counter()
    for run in _runs_without_stopwords(tokens):
        for n in range(1, _MAX_PHRASE_LEN + 1):
            for i in range(len(run) - n + 1):
                counts[" ".join(run[i : i + n])] += 1

    return counts, extracted_count, survived_count


def _empty_report(reason):
    return {
        "covered": [],
        "missing": [],
        "covered_total": 0,
        "missing_total": 0,
        "extracted_count": 0,
        "survived_count": 0,
        "reason": reason,
    }


def coverage(jd_text, cv_text, top_n=DEFAULT_TOP_N):
    """Compare `jd_text` against `cv_text` and report keyword overlap.

    Returns a dict:
      - `covered`: JD terms that also appear in the CV, ranked by JD
        frequency (highest first), each term listed once, truncated to
        `top_n`.
      - `missing`: JD terms that do not appear in the CV, same ranking and
        same truncation.
      - `covered_total` / `missing_total`: the counts before truncation, so
        a truncated report still reports the real size.
      - `extracted_count`: total tokens the tokenizer found in the JD.
      - `survived_count`: how many of those tokens were not stopwords.
      - `reason`: `None` for a normal report; a human-readable string when
        `jd_text` or `cv_text` was empty or whitespace-only, in which case
        `covered`/`missing` are empty and the counts are zero. Returning
        early here also means no division is ever attempted on a zero
        denominator.
    """
    jd_stripped = (jd_text or "").strip()
    cv_stripped = (cv_text or "").strip()
    # Validate the flag BEFORE anything else. Sitting below the two
    # empty-text early returns, this guard never fired on the paths a user
    # is most likely to hit: `--top 0` with an empty JD exited 0 with a
    # report. Argument validation also has no business running after the
    # text has been tokenised and sorted.
    if top_n is not None and top_n <= 0:
        raise KeywordsError(f"top_n must be positive or None, got {top_n!r}")

    if not jd_stripped:
        return _empty_report("the job description text is empty")
    if not cv_stripped:
        return _empty_report("the CV text is empty")

    jd_counts, extracted_count, survived_count = _extract_terms(jd_text)
    cv_counts, _cv_extracted, _cv_survived = _extract_terms(cv_text)
    cv_terms = set(cv_counts)

    ranked = sorted(jd_counts.items(), key=lambda item: (-item[1], item[0]))
    covered = [term for term, _count in ranked if term in cv_terms]
    missing = [term for term, _count in ranked if term not in cv_terms]

    # `top_n=None` means "no limit" explicitly; a non-positive number was
    # already refused at the top of this function.
    limit = top_n
    return {
        "covered": covered[:limit] if limit else covered,
        "missing": missing[:limit] if limit else missing,
        "covered_total": len(covered),
        "missing_total": len(missing),
        "extracted_count": extracted_count,
        "survived_count": survived_count,
        "reason": None,
    }


def _section_heading(label, report, key):
    """Heading that says when the list is a ranked head, not the whole set.

    A truncated list that claims to be complete is worse than a long one.
    """
    shown = len(report[key])
    total = report.get(f"{key}_total", shown)
    if total > shown:
        return f"## {label} ({shown} of {total}, highest job-description frequency first)"
    return f"## {label} ({shown})"


def render(report):
    """Render `report` (as returned by `coverage`) as the
    `keyword-report.md` body.

    The heading states this is a keyword overlap report. It never claims an
    ATS score, because no local computation can honestly predict one.
    """
    lines = [
        "# Keyword overlap report",
        "",
        "This compares words in the job description against the CV text. "
        "It reports keyword overlap only. **It is not an ATS score** — ATS "
        "vendors parse differently from each other, and no local "
        "computation can honestly predict what any of them would score.",
        "",
    ]

    if report["reason"]:
        lines.append(f"No comparison was made: {report['reason']}.")
        return "\n".join(lines) + "\n"

    lines.append(
        f"Extracted {report['extracted_count']} term occurrence(s) from the "
        f"job description; {report['survived_count']} survived stopword "
        "removal."
    )
    lines.append("")

    lines.append(_section_heading("Covered", report, "covered"))
    lines.append("")
    if report["covered"]:
        lines.extend(f"- {term}" for term in report["covered"])
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append(_section_heading("Missing", report, "missing"))
    lines.append("")
    if report["missing"]:
        lines.extend(f"- {term}" for term in report["missing"])
    else:
        lines.append("- (none)")
    lines.append("")

    return "\n".join(lines) + "\n"

"""Greenhouse, Lever and Ashby ATS fetch and normalisation.

`fetch` is the only network-touching function in this module and is never
exercised by a test — tests read the JSON fixtures in `tests/fixtures/`
straight off disk. `normalize_<board>` functions are pure: read JSON from
`path`, return a list of queue rows shaped for `jobq`/`promote`
(`company`, `jobTitle`, `jobDescription`, `location`, `source`, `jobType`,
`workplaceType`, `jobUrl` — only the fields that could be established for
that row are set; the rest are simply absent, never guessed).

## Why `normalize_lever` and `normalize_ashby` take a `company` argument

Verified against the live payloads 2026-09-19: Greenhouse's per-job JSON
carries `company_name`, but neither Lever's
(`https://api.lever.co/v0/postings/<slug>`) nor Ashby's
(`https://api.ashbyhq.com/posting-api/job-board/<slug>`) payload carries any
company field at all — not per job, not at the container level. The only
place the company identity lives is the board `slug` the caller already used
to fetch the board. Guessing a display name from the slug (turning
`"leverdemo"` into `"Leverdemo"`, say) would be exactly the kind of
unverifiable guess this module refuses to make for Greenhouse's
`workplaceType` (see `_infer_greenhouse_workplace_type`), so the caller must
pass the real company name in explicitly — it already has it, from the same
config entry that supplied the slug to `fetch`.

## HTML / entity handling

Greenhouse's `content` field is HTML-escaped *twice* (verified on the live
Stripe board: the raw JSON string contains `&amp;nbsp;`, which unescapes
once to the still-escaped `&nbsp;`, and only a second `html.unescape` pass
turns that into a real non-breaking space). `_clean_description` loops
`html.unescape` to a fixed point before stripping tags, so single- and
double-escaped input both come out clean. Lever's `descriptionPlain` and
Ashby's `descriptionPlain` are already plain text in practice, but are run
through the same cleaner defensively — it is a no-op on text with no tags
or entities.
"""

import html
import json
import re
import sys
import urllib.error
import urllib.request

SOURCE_GREENHOUSE = "Greenhouse"
SOURCE_LEVER = "Lever"
SOURCE_ASHBY = "Ashby"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_MIN_DESCRIPTION_LEN = 10
_NA_DESCRIPTION = "N/A"

_FETCH_TIMEOUT_SECONDS = 30
_CHUNK_SIZE = 65536

_ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}


class AtsError(Exception):
    """Base class for every ATS fetch/normalise error this module raises."""


class MissingFieldError(AtsError):
    """A provider payload is missing a key normalisation depends on.

    Raised instead of returning a half-built row, per the plan's hard rule:
    a schema change upstream must surface as a named, loud failure.
    """

    def __init__(self, provider, key):
        self.provider = provider
        self.key = key
        super().__init__(f"{provider} posting missing required key {key!r}")


def fetch(board, slug, dest):
    """Stream a live ATS board to `dest` on disk. The only network call in this module.

    `board` is one of "greenhouse", "lever", "ashby". Streams the response
    body straight to `dest` in fixed-size chunks (a Greenhouse board alone
    is 5.1 MB — never held in memory as one string). After the stream
    completes, re-reads `dest` once to compute a row count for logging
    (`fetch` logs board, slug, HTTP status and row count) and returns
    `(status, row_count)`.

    Any HTTP error, transport error/timeout, or non-JSON response body
    raises `AtsError` naming the board and slug; nothing partially-written
    is left importable as a fixture in that case beyond what was already
    streamed to `dest`.
    """
    template = _ENDPOINTS.get(board)
    if template is None:
        raise AtsError(f"Unknown ATS board {board!r}; expected one of {sorted(_ENDPOINTS)}")
    url = template.format(slug=slug)
    request = urllib.request.Request(url, headers={"User-Agent": "ai-jobhunter/0.1"})

    try:
        response = urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"ats.fetch: board={board} slug={slug} status={exc.code} rows=0")
        raise AtsError(
            f"{board} fetch for slug={slug!r} failed: HTTP {exc.code} {body}"
        ) from exc
    except (TimeoutError, urllib.error.URLError) as exc:
        print(f"ats.fetch: board={board} slug={slug} status=<no response> error={exc}")
        raise AtsError(f"{board} fetch for slug={slug!r} failed: {exc}") from exc

    with response:
        status = getattr(response, "status", None)
        with open(dest, "wb") as out:
            while True:
                chunk = response.read(_CHUNK_SIZE)
                if not chunk:
                    break
                out.write(chunk)

    with open(dest, "rb") as f:
        try:
            payload = json.load(f)
        except json.JSONDecodeError as exc:
            print(f"ats.fetch: board={board} slug={slug} status={status} rows=<non-JSON body>")
            raise AtsError(
                f"{board} fetch for slug={slug!r} returned a non-JSON response body"
            ) from exc

    if isinstance(payload, list):
        row_count = len(payload)
    elif isinstance(payload, dict):
        row_count = len(payload.get("jobs") or [])
    else:
        row_count = 0

    print(f"ats.fetch: board={board} slug={slug} status={status} rows={row_count}")
    return status, row_count


def _clean_description(raw):
    """Strip HTML, unescape entities (looping to a fixed point), collapse
    whitespace. A result shorter than 10 characters becomes the literal
    string "N/A" — jobsync rejects a 1-9 character `jobDescription` but
    accepts "N/A".
    """
    text = raw or ""
    previous = None
    while text != previous:
        previous = text
        text = html.unescape(text)
    text = _TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    if len(text) < _MIN_DESCRIPTION_LEN:
        return _NA_DESCRIPTION
    return text


# Greenhouse never states a work arrangement. Its only signal is the free-text
# `location.name`, so the arrangement is read ONLY from words that actually
# state one. A bare place name states where an office is, not whether the role
# is performed there: measured on a live 667-job board, 560 locations were a
# place name alone and not one said "hybrid" or "onsite". Treating those as
# Onsite invented an arrangement for 329 postings.
#
# An absent optional field is accepted by jobsync; a wrong value is not
# correctable later. So: no arrangement word means no field.
_WORKPLACE_WORD_PATTERNS = (
    ("Hybrid", re.compile(r"\bhybrid\b")),
    ("Remote", re.compile(r"\bremote\b")),
    ("Onsite", re.compile(r"\bon-?site\b|\bin-?office\b")),
)
_UNSET_LOCATION_TEXT = frozenset({"n/a", "na"})


def _infer_greenhouse_workplace_type(location_name):
    """Return Remote/Hybrid/Onsite only when the location text says so.

    Returns `None` for empty or unset text and for any text that names a place
    without naming an arrangement. Hybrid wins over Remote when both appear,
    because "hybrid" is the narrower statement of the two.
    """
    lowered = location_name.strip().lower()
    if not lowered or lowered in _UNSET_LOCATION_TEXT:
        return None
    for value, pattern in _WORKPLACE_WORD_PATTERNS:
        if pattern.search(lowered):
            return value
    return None


class _Rows(list):
    """A normal list of rows that also carries what could not be normalised.

    `_normalize_all` returned `(rows, skipped)` and every caller discarded
    the second half, so the postings it named were lost as quietly as before.
    Subclassing `list` keeps every existing caller working — the rows ARE the
    list — while `rows.skipped` stays available to a caller that reports it.
    """

    def __init__(self, rows, skipped):
        super().__init__(rows)
        self.skipped = skipped


def _normalize_all(source, jobs, normalizer):
    """Normalise every posting, surviving a single bad one.

    A schema change upstream breaks every posting and still fails loudly,
    because `strict` below raises once nothing at all normalised. But one
    posting missing a field is an anomaly in somebody else's data, and a
    list comprehension turned that into throwing away the other 666 rows of
    a board with no way for the user to continue.

    Returns `(rows, skipped)` where each skipped entry names the posting and
    the field, so the caller can report them instead of losing them quietly.
    """
    rows = []
    skipped = []
    first_error = None
    for job in jobs:
        try:
            rows.append(normalizer(job))
        except MissingFieldError as exc:
            if first_error is None:
                first_error = exc
            skipped.append({"error": str(exc), "job": _identify(job)})
    if jobs and not rows:
        # Nothing normalised: that is a schema change, not one bad posting.
        # Re-raise the FIRST error so the message still names the missing
        # key — a caller needs to know which field moved, not merely that
        # everything failed.
        raise first_error
    if skipped:
        print(
            f"ats.normalize: source={source} rows={len(rows)} skipped={len(skipped)}",
            file=sys.stderr,
        )
    return rows, skipped


def _identify(job):
    """Whatever identifies a posting well enough to look it up by hand."""
    for key in ("title", "text", "id", "jobUrl", "hostedUrl", "absolute_url"):
        value = job.get(key) if isinstance(job, dict) else None
        if value:
            return {key: value}
    return {}


def normalize_greenhouse(path):
    """Read a Greenhouse board JSON file from disk and return queue rows."""
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict) or "jobs" not in payload:
        raise MissingFieldError(SOURCE_GREENHOUSE, "jobs")

    rows, skipped = _normalize_all(
        SOURCE_GREENHOUSE, payload["jobs"], _normalize_greenhouse_job
    )
    return rows if not skipped else _Rows(rows, skipped)


def _normalize_greenhouse_job(job):
    for key in ("title", "company_name", "absolute_url"):
        if not job.get(key):
            raise MissingFieldError(SOURCE_GREENHOUSE, key)

    row = {
        "company": job["company_name"],
        "jobTitle": job["title"],
        "jobDescription": _clean_description(job.get("content")),
        "source": SOURCE_GREENHOUSE,
        "jobUrl": job["absolute_url"],
    }

    location_name = ((job.get("location") or {}).get("name") or "").strip()
    if location_name:
        row["location"] = location_name
        workplace_type = _infer_greenhouse_workplace_type(location_name)
        if workplace_type:
            row["workplaceType"] = workplace_type

    return row


_LEVER_WORKPLACE_TYPES = {"remote": "Remote", "hybrid": "Hybrid", "onsite": "Onsite"}


def normalize_lever(path, company):
    """Read a Lever board JSON file from disk and return queue rows.

    `company` is required — see the module docstring for why Lever's own
    payload cannot supply it.
    """
    if not company:
        raise MissingFieldError(SOURCE_LEVER, "company")

    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, list):
        raise AtsError(f"{SOURCE_LEVER} payload at {path} is not a JSON array")

    rows, skipped = _normalize_all(
        SOURCE_LEVER, payload, lambda p: _normalize_lever_posting(p, company)
    )
    return rows if not skipped else _Rows(rows, skipped)


def _normalize_lever_posting(posting, company):
    for key in ("text", "hostedUrl"):
        if not posting.get(key):
            raise MissingFieldError(SOURCE_LEVER, key)

    row = {
        "company": company,
        "jobTitle": posting["text"],
        "jobDescription": _clean_description(posting.get("descriptionPlain")),
        "source": SOURCE_LEVER,
        "jobUrl": posting["hostedUrl"],
    }

    location = (posting.get("categories") or {}).get("location")
    if location:
        row["location"] = location

    workplace_type = _LEVER_WORKPLACE_TYPES.get(
        (posting.get("workplaceType") or "").strip().lower()
    )
    if workplace_type:
        row["workplaceType"] = workplace_type

    return row


_ASHBY_WORKPLACE_TYPES = {"remote": "Remote", "hybrid": "Hybrid", "onsite": "Onsite"}
_ASHBY_EMPLOYMENT_TYPES = {
    "fulltime": "Full-time",
    "parttime": "Part-time",
    "contract": "Contract",
}


def normalize_ashby(path, company):
    """Read an Ashby board JSON file from disk and return queue rows.

    `company` is required — see the module docstring for why Ashby's own
    payload cannot supply it. Rows with `isListed: false` are not public
    postings and are dropped.
    """
    if not company:
        raise MissingFieldError(SOURCE_ASHBY, "company")

    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict) or "jobs" not in payload:
        raise MissingFieldError(SOURCE_ASHBY, "jobs")

    def normalize_one(job):
        if not isinstance(job, dict):
            raise MissingFieldError(SOURCE_ASHBY, "job object")
        if "isListed" not in job:
            raise MissingFieldError(SOURCE_ASHBY, "isListed")
        return _normalize_ashby_job(job, company)

    # `job.get(...)` on a non-dict raises AttributeError, which neither
    # `_normalize_all` nor the CLI catches, so a stray non-object in the
    # payload escaped as a traceback. Keep such entries in the list and let
    # `normalize_one` reject them by name instead.
    listed = [
        job
        for job in payload["jobs"]
        if not isinstance(job, dict) or job.get("isListed", True)
    ]
    unlisted = len(payload["jobs"]) - len(listed)

    rows, skipped = _normalize_all(SOURCE_ASHBY, listed, normalize_one)
    if unlisted:
        print(f"ats.normalize: source={SOURCE_ASHBY} unlisted_dropped={unlisted}", file=sys.stderr)
    return rows if not skipped else _Rows(rows, skipped)


def _normalize_ashby_job(job, company):
    for key in ("title", "jobUrl"):
        if not job.get(key):
            raise MissingFieldError(SOURCE_ASHBY, key)

    row = {
        "company": company,
        "jobTitle": job["title"],
        "jobDescription": _clean_description(job.get("descriptionPlain")),
        "source": SOURCE_ASHBY,
        "jobUrl": job["jobUrl"],
    }

    location = job.get("location")
    if location:
        row["location"] = location

    workplace_type = _ASHBY_WORKPLACE_TYPES.get(
        (job.get("workplaceType") or "").strip().lower()
    )
    if workplace_type:
        row["workplaceType"] = workplace_type

    employment_type = _ASHBY_EMPLOYMENT_TYPES.get(
        (job.get("employmentType") or "").strip().lower()
    )
    if employment_type:
        row["jobType"] = employment_type

    return row

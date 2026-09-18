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


# A Greenhouse location string counts as "ambiguous" the moment it could
# name more than one place or condition (a list of offices, an "or"/"and"
# between alternatives). An absent optional field is accepted by jobsync; a
# wrong guess is not correctable later, so any of these markers means
# `workplaceType` is left out rather than inferred.
_AMBIGUOUS_SEPARATORS = (",", ";", "/")
_AMBIGUOUS_WORDS = frozenset({"or", "and"})
_UNSET_LOCATION_TEXT = frozenset({"n/a", "na"})


def _infer_greenhouse_workplace_type(location_name):
    """Infer Remote/Hybrid/Onsite from Greenhouse's free-text location, or
    return `None` when the text is empty, unset, or names more than one
    possible place.
    """
    lowered = location_name.strip().lower()
    if not lowered or lowered in _UNSET_LOCATION_TEXT:
        return None
    if any(sep in lowered for sep in _AMBIGUOUS_SEPARATORS):
        return None
    if _AMBIGUOUS_WORDS & set(re.split(r"\s+", lowered)):
        return None
    if "remote" in lowered:
        return "Remote"
    if "hybrid" in lowered:
        return "Hybrid"
    return "Onsite"


def normalize_greenhouse(path):
    """Read a Greenhouse board JSON file from disk and return queue rows."""
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict) or "jobs" not in payload:
        raise MissingFieldError(SOURCE_GREENHOUSE, "jobs")

    return [_normalize_greenhouse_job(job) for job in payload["jobs"]]


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

    return [_normalize_lever_posting(posting, company) for posting in payload]


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

    rows = []
    for job in payload["jobs"]:
        if "isListed" not in job:
            raise MissingFieldError(SOURCE_ASHBY, "isListed")
        if not job["isListed"]:
            continue
        rows.append(_normalize_ashby_job(job, company))
    return rows


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

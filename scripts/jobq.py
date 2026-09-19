"""Local JSONL work queue: append, dedupe by identity, and read back rows.

The queue lives at `.jobhunter/queue/jobs.jsonl` in the user's own project
(never inside this repo — that path is gitignored runtime data). This module
only deals with an arbitrary `path` passed in by the caller; it never assumes
or creates that default location itself.
"""

import hashlib
import json
import os
import re
import stat
import tempfile
import urllib.parse

_WHITESPACE_RE = re.compile(r"\s+")


def _collapse(text):
    """Lower-case and collapse runs of whitespace to a single space, trimmed."""
    return _WHITESPACE_RE.sub(" ", text.lower()).strip()


# Query parameters that describe how someone arrived at a posting, never which
# posting it is. Only these are dropped. Stripping the whole query string is
# wrong and was measured to be catastrophic: Greenhouse publishes every job on
# one path and puts the job id in the query (`/jobs/search?gh_jid=8172487`), so
# dropping the query collapsed all 667 Stripe postings into a single key.
_TRACKING_PARAMS = frozenset({
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "ref",
    "referrer",
    "source",
    "src",
    "trk",
    "trackingid",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
})


def _normalize_url(url):
    """Drop tracking parameters and the fragment; keep every identifying param.

    Remaining parameters are sorted so that the same posting linked with its
    parameters in a different order still yields one key.
    """
    parts = urllib.parse.urlsplit(url)
    kept = [
        (name, value)
        for name, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if name.lower() not in _TRACKING_PARAMS
    ]
    query = urllib.parse.urlencode(sorted(kept))
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, query, "")
    )


def row_key(row):
    """Stable identity key for a queue row.

    sha256 of the normalized `jobUrl` when present, else sha256 of
    `company|jobTitle|location`. Either basis is lower-cased with whitespace
    collapsed before hashing, so cosmetic differences (case, extra spaces,
    tracking parameters, parameter order) never produce distinct keys.
    """
    job_url = row.get("jobUrl")
    if job_url:
        basis = _collapse(_normalize_url(job_url))
    else:
        company = _collapse(row.get("company", "") or "")
        job_title = _collapse(row.get("jobTitle", "") or "")
        location = _collapse(row.get("location", "") or "")
        basis = f"{company}|{job_title}|{location}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def load(path):
    """Read all valid rows from a JSONL queue file.

    Returns an empty list when the file is missing or empty. A malformed
    (non-JSON) line is skipped and never aborts the read.
    """
    if not os.path.exists(path):
        return []

    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def append_rows(path, rows):
    """Append new rows to the queue, skipping duplicates and malformed input.

    Duplicate detection is by `row_key` against both the rows already on
    disk and the rows already appended earlier in this same call. Returns
    `(written, skipped_duplicates, malformed)`. Malformed lines already
    present on disk are counted too, since reading them is part of building
    the dedupe index.
    """
    existing_rows = load(path)
    malformed = _count_malformed_lines(path)

    seen_keys = {row_key(row) for row in existing_rows}

    written = 0
    skipped_duplicates = 0
    to_write = []
    for row in rows:
        key = row_key(row)
        if key in seen_keys:
            skipped_duplicates += 1
            continue
        seen_keys.add(key)
        to_write.append(row)
        written += 1

    if to_write:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for row in to_write:
                f.write(json.dumps(row))
                f.write("\n")

    return written, skipped_duplicates, malformed


def _count_malformed_lines(path):
    """Count non-JSON, non-blank lines in an existing queue file."""
    if not os.path.exists(path):
        return 0

    count = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                json.loads(stripped)
            except json.JSONDecodeError:
                count += 1
    return count


def iter_unpromoted(rows):
    """Yield rows not yet marked promoted.

    Without this the `promoted` flag `update_rows` writes is never read, and
    every promote run re-upserts rows already in jobsync — two requests each,
    against a ceiling of sixty an hour, so the budget is spent on old rows
    before a new one is ever sent.
    """
    for row in rows:
        if not row.get("promoted"):
            yield row


def iter_unscored(rows):
    """Yield rows that have no `fit_score` set yet."""
    for row in rows:
        if row.get("fit_score") is None:
            yield row


def _load_entries(path):
    """Every non-blank line, parsed where possible and kept verbatim always.

    `{"text": <original line>, "row": <dict or None>}`. The `text` of a row
    that is updated is replaced; every other line, parseable or not, is
    written back exactly as it was read.
    """
    if not os.path.exists(path):
        return []

    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            text = line.rstrip("\n")
            if not text.strip():
                continue
            try:
                entries.append({"text": text, "row": json.loads(text)})
            except json.JSONDecodeError:
                entries.append({"text": text, "row": None})
    return entries


def update_rows(path, updates, key=row_key):
    """Rewrite the queue in place, merging `updates` into matching rows.

    `updates` maps a row key to the fields to merge into that row. The queue
    is append-only for *new* postings, but a row has to change twice in its
    life: `/ai-jobhunter:score` writes the score onto it, and
    `/ai-jobhunter:promote` marks it promoted so a later run does not spend a
    second request re-promoting it. `append_rows` cannot do either — it would
    see the changed row as a duplicate by `row_key` and drop it.

    A line the parser cannot read is preserved byte for byte rather than
    dropped, so an interrupted append never costs a posting.

    Returns `(updated, unmatched)`. An update whose key matches no row on disk
    is reported rather than silently dropped: a key that matches nothing means
    the caller and the queue disagree about identity, which is worth knowing.

    The rewrite is atomic — a temporary file in the same directory is renamed
    over the original — so an interrupted run leaves the old queue intact
    rather than a half-written one.
    """
    # Read the file as LINES, not as parsed rows. `load` skips a line it
    # cannot parse, and writing back only what parsed would delete it — an
    # interrupted `append_rows` leaves exactly such a half-written tail, so
    # the next score run would silently lose that posting. A line this
    # function cannot understand is passed through untouched.
    entries = _load_entries(path)
    remaining = dict(updates)

    updated = 0
    for entry in entries:
        if entry["row"] is None:
            continue
        fields = remaining.pop(key(entry["row"]), None)
        if fields is not None:
            entry["row"].update(fields)
            entry["text"] = json.dumps(entry["row"])
            updated += 1

    directory = os.path.dirname(path) or "."
    # `mkstemp` creates at 0600 and `os.replace` carries that mode onto the
    # destination, so without this the rewrite would silently narrow the
    # queue file's permissions. Preserving the original mode keeps the
    # rewrite invisible to everything except the row contents.
    existing_mode = None
    if os.path.exists(path):
        existing_mode = stat.S_IMODE(os.stat(path).st_mode)

    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(entry["text"])
                f.write("\n")
        if existing_mode is not None:
            os.chmod(tmp_path, existing_mode)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return updated, sorted(remaining)

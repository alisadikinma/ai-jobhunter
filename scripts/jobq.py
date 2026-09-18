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
import urllib.parse

_WHITESPACE_RE = re.compile(r"\s+")


def _collapse(text):
    """Lower-case and collapse runs of whitespace to a single space, trimmed."""
    return _WHITESPACE_RE.sub(" ", text.lower()).strip()


def _normalize_url(url):
    """Strip query string and fragment so differing query params still dedupe."""
    parts = urllib.parse.urlsplit(url)
    normalized = urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, "", "")
    )
    return normalized


def row_key(row):
    """Stable identity key for a queue row.

    sha256 of the normalized `jobUrl` when present, else sha256 of
    `company|jobTitle|location`. Either basis is lower-cased with whitespace
    collapsed before hashing, so cosmetic differences (case, extra spaces,
    a trailing query string on the URL) never produce distinct keys.
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


def iter_unscored(rows):
    """Yield rows that have no `fit_score` set yet."""
    for row in rows:
        if row.get("fit_score") is None:
            yield row

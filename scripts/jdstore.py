"""Filesystem-safe path resolution for `Data/<source>/<company>/<role>/`.

`company` and `jobTitle` originate from scraped/API JD text (Firecrawl,
Apify) — external, semi-trusted input — and become filesystem path
components. `safe_component` cleans a single component and rejects anything
that would traverse outside the intended `Data/<source>/` subtree (a bare
`.` or `..` after cleaning). `job_dir` resolves the deterministic,
collision-safe directory for one posting.
"""

import datetime
import difflib
import glob
import json
import os
import re

import jobq

_UNSAFE_CHARS_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_WHITESPACE_RE = re.compile(r"\s+")
_APPROVED_RE = re.compile(r"^approved:\s*\S+", re.MULTILINE)
_MAX_COMPONENT_LENGTH = 80


class JdStoreError(Exception):
    """Raised when a path component or directory resolution cannot proceed."""


def safe_component(value):
    """Clean `value` into a single filesystem-safe path component.

    - Replaces path separators and other unsafe characters with `-`.
    - Collapses whitespace runs to a single space, strips.
    - Strips leading/trailing `.` and `-` characters.
    - Truncates to 80 characters.

    Raises `JdStoreError` if the input is empty/whitespace-only, if the
    cleaned result is empty, or if the cleaned result is exactly `.` or
    `..` — the traversal guard: without it, a value that cleans to `..`
    could make `os.path.join(root, "..", ...)` escape the intended
    `Data/<source>/` subtree.
    """
    if value is None or not str(value).strip():
        raise JdStoreError(f"safe_component: input is empty or whitespace-only: {value!r}")

    cleaned = _UNSAFE_CHARS_RE.sub("-", value)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    cleaned = cleaned.strip(".-")
    cleaned = cleaned[:_MAX_COMPONENT_LENGTH]

    if not cleaned:
        raise JdStoreError(f"safe_component: cleaned result is empty for input: {value!r}")
    if cleaned in (".", ".."):
        raise JdStoreError(f"safe_component: cleaned result is a traversal component: {cleaned!r}")

    return cleaned


def job_dir(root, source, company, title, identity_key):
    """Resolve the deterministic directory for one posting.

    `Data/<source>/<company>/<title>/`, with `company`/`title` cleaned via
    `safe_component`. Read-only resolution — never creates the directory
    (that is `write_jd`'s job).

    Collision handling: if the candidate path already exists and belongs to
    a *different* posting (its `.jobmeta.json` is absent, unparseable, or
    names a different `row_key`), the title component is suffixed with
    `-{identity_key[:6]}` and the same check is retried once. If that
    suffixed path ALSO collides with a third, different posting, raises
    `JdStoreError` naming both colliding paths.
    """
    safe_source = safe_component(source)
    safe_company = safe_component(company)
    safe_title = safe_component(title)

    candidate = os.path.join(root, safe_source, safe_company, safe_title)
    if _belongs_to(candidate, identity_key):
        return candidate

    suffixed_title = f"{safe_title}-{identity_key[:6]}"
    suffixed = os.path.join(root, safe_source, safe_company, suffixed_title)
    if _belongs_to(suffixed, identity_key):
        return suffixed

    raise JdStoreError(
        f"job_dir: collision resolving identity_key={identity_key!r} — "
        f"both {candidate!r} and {suffixed!r} are claimed by other postings"
    )


def write_jd(root, row):
    """Materialize `JD.md` + `.jobmeta.json` for one queue row.

    Requires `row["jobDescription"]` to be non-empty (strip-checked) —
    raises `JdStoreError` naming the missing field otherwise, mirroring
    `tailor`'s "reading the JD is mandatory" rule.

    Idempotent: if the resolved folder already belongs to this row's
    identity (via `job_dir`'s `.jobmeta.json` check), nothing is written and
    `{"path": path, "created": False}` is returned — an already-materialized
    posting, which may already carry `tailor` output beside it, is never
    overwritten.

    Otherwise creates the folder, writes `row["jobDescription"]` verbatim to
    `JD.md`, writes an identity marker to `.jobmeta.json`, and returns
    `{"path": path, "created": True}`.
    """
    job_description = row.get("jobDescription")
    if job_description is None or not str(job_description).strip():
        raise JdStoreError(
            f"write_jd: row is missing a non-empty 'jobDescription' field: {job_description!r}"
        )

    for field in ("source", "company", "jobTitle"):
        if not isinstance(row.get(field), str):
            raise JdStoreError(f"write_jd: row is missing a string {field!r} field: {row.get(field)!r}")

    identity_key = jobq.row_key(row)
    path = job_dir(root, row["source"], row["company"], row["jobTitle"], identity_key)

    meta_path = os.path.join(path, ".jobmeta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                existing_meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            existing_meta = None
        if existing_meta is not None and existing_meta.get("row_key") == identity_key:
            return {"path": path, "created": False}

    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "JD.md"), "w", encoding="utf-8") as f:
        f.write(job_description)

    meta = {
        "row_key": identity_key,
        "jobUrl": row.get("jobUrl"),
        "company": row["company"],
        "jobTitle": row["jobTitle"],
        "source": row["source"],
        "written_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f)

    return {"path": path, "created": True}


def write_jd_files(root, rows):
    """Materialize `write_jd` for every row, never aborting the batch on one bad row.

    Returns `{"written": [...], "skipped_existing": [...], "errors": [...]}`.
    `written` and `skipped_existing` hold the resolved path for each row;
    `errors` holds `{"company": ..., "jobTitle": ..., "message": ...}` for
    each row that raised `JdStoreError` or an `OSError` (unwritable folder, a file
    sitting where the folder belongs) — same resilience pattern as
    `ats._normalize_all`.
    """
    result = {"written": [], "skipped_existing": [], "errors": []}
    for row in rows:
        try:
            outcome = write_jd(root, row)
        except (JdStoreError, OSError) as exc:
            result["errors"].append(
                {
                    "company": row.get("company"),
                    "jobTitle": row.get("jobTitle"),
                    "message": str(exc),
                }
            )
            continue

        if outcome["created"]:
            result["written"].append(outcome["path"])
        else:
            result["skipped_existing"].append(outcome["path"])

    return result


def find_similar(root, jd_text, threshold=0.90):
    """Find previously-tailored postings whose JD is a near-duplicate of `jd_text`.

    Only folders whose `requirements-map.md` carries an `approved:` line are
    eligible — an unapproved map is not a finished tailoring worth reusing.
    A folder missing its `JD.md`, or whose `.jobmeta.json` is absent or
    unparseable, is malformed data: it is skipped, never a crash.

    Each side is lowercased, whitespace-collapsed, and has the *candidate's*
    company name removed (from both sides, so an identical JD scores 1.0)
    before `difflib.SequenceMatcher` compares them. Returns
    `[{"path", "company", "role", "ratio"}]` with `ratio >= threshold`,
    highest ratio first. A nonexistent `root` yields `[]`.
    """
    pattern = os.path.join(root, "*", "*", "*", "requirements-map.md")
    matches = []
    for map_path in glob.glob(pattern):
        folder = os.path.dirname(map_path)
        try:
            with open(map_path, "r", encoding="utf-8") as f:
                map_text = f.read()
            if not _APPROVED_RE.search(map_text):
                continue
            with open(os.path.join(folder, "JD.md"), "r", encoding="utf-8") as f:
                candidate_text = f.read()
            with open(os.path.join(folder, ".jobmeta.json"), "r", encoding="utf-8") as f:
                meta = json.load(f)
            company = meta["company"]
            role = meta["jobTitle"]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
            continue

        # autojunk=False: on texts over 200 chars the default heuristic discards
        # common characters and scores a near-identical JD around 0.1.
        ratio = difflib.SequenceMatcher(
            None,
            _normalize_for_compare(jd_text, company),
            _normalize_for_compare(candidate_text, company),
            autojunk=False,
        ).ratio()
        if ratio >= threshold:
            matches.append({"path": folder, "company": company, "role": role, "ratio": ratio})

    matches.sort(key=lambda m: m["ratio"], reverse=True)
    return matches


def _normalize_for_compare(text, company):
    """Lowercase, drop every mention of `company`, collapse whitespace."""
    if company:
        text = re.sub(re.escape(company), "", text, flags=re.IGNORECASE)
    return _WHITESPACE_RE.sub(" ", text.lower()).strip()


def _belongs_to(candidate, identity_key):
    """True if `candidate` is free to use, or already belongs to `identity_key`.

    "Free to use" means it does not exist on disk yet. An existing directory
    with no `.jobmeta.json`, or one that fails to parse, is treated as
    foreign/unrelated data and never claimed.
    """
    if not os.path.isdir(candidate):
        return True

    meta_path = os.path.join(candidate, ".jobmeta.json")
    if not os.path.exists(meta_path):
        return False

    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False

    return meta.get("row_key") == identity_key

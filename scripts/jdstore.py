"""Filesystem-safe path resolution for `Data/<source>/<company>/<role>/`.

`company` and `jobTitle` originate from scraped/API JD text (Firecrawl,
Apify) — external, semi-trusted input — and become filesystem path
components. `safe_component` cleans a single component and rejects anything
that would traverse outside the intended `Data/<source>/` subtree (a bare
`.` or `..` after cleaning). `job_dir` resolves the deterministic,
collision-safe directory for one posting.
"""

import json
import os
import re

_UNSAFE_CHARS_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_WHITESPACE_RE = re.compile(r"\s+")
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

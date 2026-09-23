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

import authgate
import jobq

_UNSAFE_CHARS_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_WHITESPACE_RE = re.compile(r"\s+")
_APPROVED_RE = re.compile(r"^approved:\s*\S+", re.MULTILINE)
_MAX_COMPONENT_LENGTH = 80


_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\((?:[^()\s]|\([^)]*\))*\)")
_HEADING_RE = re.compile(r"[ \t]+(#{1,6} )")
_BULLET_RE = re.compile(r"(?<=\S)[ \t]+[*\u2022][ \t]+")
_BRACKET_HEAD_RE = re.compile(r"[ \t]+(\[[A-Z][^\]\n]{2,40}\])[ \t]+")
_JOB_URL_RE = re.compile(
    r"https?://[^\s)\]]*/jobs?/\d+|https?://jobs\.[^\s)\]]+/[0-9a-f-]{20,}"
)
_MAX_POSTING_URLS = 4
_CHROME_LINK_LIMIT = 12
_MIN_JD_CHARS = 400


class JdStoreError(Exception):
    """Raised when a path component or directory resolution cannot proceed."""


def format_jd(text):
    """Make a scraped JD readable without changing its words.

    Scrapers hand back one long line: headings, bullets and page chrome all
    run together. This drops images, keeps a link's visible text and not its
    URL, and puts headings and bullets on their own lines. Text with none of
    those (a plain paste) comes back unchanged apart from trimmed line ends.
    """
    t = text.replace("\r", "").replace("\\<br>", " ")
    t = _IMAGE_RE.sub("", t)
    t = _LINK_RE.sub(r"\1", t)
    t = _HEADING_RE.sub(r"\n\n\1", t)
    t = _BULLET_RE.sub("\n* ", t)
    t = _BRACKET_HEAD_RE.sub(r"\n\n**\1**\n\n", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def render_jd(row):
    """`JD.md` body: the apply link on top, then the formatted posting."""
    return f"Apply: {row['jobUrl'].strip()}\n\n{format_jd(row['jobDescription'])}"


def jd_problems(text):
    """Return `(errors, warnings)` for a JD text. One JD is one posting.

    Error: the text is shorter than 400 characters (too little to tailor
    against), or it links to five or more distinct job postings. That is a
    company's listing page, not one job. Warning: the text carries a lot of
    links, which means site navigation came along with the posting.
    """
    errors, warnings = [], []
    body = format_jd(text)
    if len(body) < _MIN_JD_CHARS:
        errors.append(
            f"text is only {len(body)} characters (minimum {_MIN_JD_CHARS}); the scrape is "
            "truncated or the posting is a stub - re-scrape it from its apply link, and "
            "drop the posting if it is still short"
        )
    posting_urls = set(_JOB_URL_RE.findall(text))
    if len(posting_urls) > _MAX_POSTING_URLS:
        errors.append(
            f"text links to {len(posting_urls)} different job postings; it is a listing "
            "page, not one JD (one JD = one posting at one company) - scrape the single "
            "posting URL instead"
        )
    status, reason = authgate.classify(text)
    if status == "closed":
        warnings.append(f"work authorization closed - {reason}")
    links = len(_LINK_RE.findall(text))
    if links >= _CHROME_LINK_LIMIT and not errors:
        warnings.append(
            f"{links} links in the text - site navigation or footer probably came with "
            "the posting; check JD.md before tailoring"
        )
    return errors, warnings


def safe_component(value):
    """Clean `value` into a single filesystem-safe path component.

    - Replaces path separators and other unsafe characters with `-`.
    - Collapses whitespace runs to a single space.
    - Truncates to 80 characters, and strips leading/trailing `.`, `-` and space
      (before and after the cut).

    Raises `JdStoreError` if the input is empty/whitespace-only, if the
    cleaned result is empty, or if the cleaned result is exactly `.` or
    `..` — the traversal guard: without it, a value that cleans to `..`
    could make `os.path.join(root, "..", ...)` escape the intended
    `Data/<source>/` subtree.
    """
    if value is None or not str(value).strip():
        raise JdStoreError(f"safe_component: input is empty or whitespace-only: {value!r}")

    cleaned = _UNSAFE_CHARS_RE.sub("-", value)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)
    # Trim dots, dashes and spaces together, after the cut: trimming spaces first
    # left ". ." as " " and cutting last could end a name on a space or dot.
    cleaned = cleaned.strip(". -")[:_MAX_COMPONENT_LENGTH].strip(". -")

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

    renamed = _find_renamed(os.path.join(root, safe_source, safe_company), identity_key)
    if renamed:
        return renamed

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

    job_url = row.get("jobUrl")
    if not isinstance(job_url, str) or not re.match(r"https?://\S+$", job_url.strip()):
        raise JdStoreError(
            f"write_jd: {row['company']!r} / {row['jobTitle']!r} has no apply link "
            f"('jobUrl' must be an http(s) URL): {job_url!r} - ask the user for it"
        )

    problems, _ = jd_problems(job_description)
    if problems:
        raise JdStoreError(f"write_jd: {row['company']!r} / {row['jobTitle']!r}: {problems[0]}")

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
            _refuse_if_jd_differs(path, row)
            return {"path": path, "created": False}

    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "JD.md"), "w", encoding="utf-8") as f:
        f.write(render_jd(row))

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


def _refuse_if_jd_differs(path, row):
    """Same identity, different text: keep the file, but say so.

    A pasted JD has no URL, so its identity is company|title alone. Pasting a
    different JD for the same company and title would otherwise be skipped as
    "already there" and `tailor` would then check the CV against the old text.
    """
    try:
        with open(os.path.join(path, "JD.md"), "r", encoding="utf-8") as f:
            existing = f.read()
    except OSError:
        return
    job_description = row["jobDescription"]
    if existing not in (render_jd(row), job_description, format_jd(job_description)):
        raise JdStoreError(
            f"write_jd: {path!r} already holds a different JD.md for this posting; "
            "it was not overwritten — ask the user whether the posting changed"
        )


def write_jd_files(root, rows):
    """Materialize `write_jd` for every row, never aborting the batch on one bad row.

    Returns `{"written": [...], "skipped_existing": [...], "errors": [...]}`.
    `written` and `skipped_existing` hold the resolved path for each row;
    `errors` holds `{"company": ..., "jobTitle": ..., "message": ...}` for
    each row that raised `JdStoreError` or an `OSError` (unwritable folder, a file
    sitting where the folder belongs) — same resilience pattern as
    `ats._normalize_all`.
    """
    if not isinstance(rows, list):
        raise JdStoreError(f"write_jd_files: rows must be a list, got {type(rows).__name__}")
    result = {"written": [], "skipped_existing": [], "errors": []}
    for row in rows:
        if not isinstance(row, dict):
            result["errors"].append(
                {"company": None, "jobTitle": None,
                 "message": f"write_jd_files: row is not an object: {row!r}"}
            )
            continue
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
            _, warned = jd_problems(row["jobDescription"])
            if warned:
                result.setdefault("warnings", []).append(
                    {"path": outcome["path"], "message": "; ".join(warned)}
                )
        else:
            result["skipped_existing"].append(outcome["path"])

    return result


def find_similar(root, jd_text, threshold=0.90, exclude=None):
    """Find previously-tailored postings whose JD is a near-duplicate of `jd_text`.

    Only folders whose `requirements-map.md` carries an `approved:` line are
    eligible — an unapproved map is not a finished tailoring worth reusing.
    A folder missing its `JD.md`, or whose `.jobmeta.json` is absent or
    unparseable, is malformed data: it is skipped, never a crash.

    Each side is lowercased, whitespace-collapsed, and has the *candidate's*
    company name removed (from both sides, so an identical JD scores 1.0)
    before `difflib.SequenceMatcher` compares them. Returns
    `[{"path", "company", "role", "ratio"}]` with `ratio >= threshold`,
    highest ratio first. A nonexistent `root` yields `[]`. `exclude` is a folder
    to skip — the posting being tailored, which would otherwise match itself.
    """
    pattern = os.path.join(root, "*", "*", "*", "requirements-map.md")
    matches = []
    exclude = os.path.realpath(exclude) if exclude else None
    for map_path in glob.glob(pattern):
        folder = os.path.dirname(map_path)
        if exclude and os.path.realpath(folder) == exclude:
            continue
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
        matcher = difflib.SequenceMatcher(
            None,
            _normalize_for_compare(jd_text, company),
            _normalize_for_compare(candidate_text, company),
            autojunk=False,
        )
        # Both are upper bounds on ratio(); ratio() is quadratic on long texts.
        if matcher.real_quick_ratio() < threshold or matcher.quick_ratio() < threshold:
            continue
        ratio = matcher.ratio()
        if ratio >= threshold:
            matches.append({"path": folder, "company": company, "role": role, "ratio": ratio})

    matches.sort(key=lambda m: m["ratio"], reverse=True)
    return matches


def _normalize_for_compare(text, company):
    """Lowercase, drop every mention of `company`, collapse whitespace."""
    if company:
        text = re.sub(re.escape(company), "", text, flags=re.IGNORECASE)
    return _WHITESPACE_RE.sub(" ", text.lower()).strip()


def company_slug(company):
    """`Acme Corp` -> `Acme-Corp`: letters and digits, hyphen-joined."""
    slug = re.sub(r"[^0-9A-Za-z]+", "-", company or "").strip("-")
    if not slug:
        raise JdStoreError(f"company_slug: nothing usable in company name {company!r}")
    return slug


def application_filename(person, kind, company, ext):
    """The file name a recruiter sees: `Jane-Doe-CV-Acme.pdf`, never a bare `cv.pdf`.

    Every posting folder used to hold identically named `cv.pdf` and
    `cover-letter.pdf`, so the wrong company's file could be uploaded. `kind`
    is `cv` or `cover-letter`.
    """
    label = {"cv": "CV", "cover-letter": "Cover-Letter"}[kind]
    return f"{company_slug(person)}-{label}-{company_slug(company)}.{ext.lstrip('.')}"


def check_output_name(out_path):
    """Refuse an output file inside a posting folder whose name lacks the company.

    Only folders carrying `.jobmeta.json` are posting folders; any other
    destination is left alone.
    """
    directory = os.path.dirname(os.path.abspath(out_path))
    meta_path = os.path.join(directory, ".jobmeta.json")
    if not os.path.isfile(meta_path):
        return
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            company = json.load(f).get("company")
    except (OSError, json.JSONDecodeError):
        return
    if company and company_slug(company).lower() not in os.path.basename(out_path).lower():
        raise JdStoreError(
            f"refusing to write {os.path.basename(out_path)!r}: a file for {company!r} must carry "
            f"'{company_slug(company)}' in its name so it cannot be uploaded to the wrong company. "
            "Use `render-application --dir <folder>`, which names the files."
        )


def _find_renamed(company_dir, identity_key):
    """The existing folder for this posting under `company_dir`, whatever it is now called.

    `tailor` renames a finished folder to `<Role> - DONE`. Path resolution from
    the row alone would then miss it and `jd-write` would recreate an empty
    `<Role>` beside it, so the identity marker, not the name, decides.
    """
    if not os.path.isdir(company_dir):
        return None
    for name in sorted(os.listdir(company_dir)):
        path = os.path.join(company_dir, name)
        if os.path.isdir(path) and _belongs_to(path, identity_key) and os.path.exists(
            os.path.join(path, ".jobmeta.json")
        ):
            return path
    return None


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

"""jobsync payload mapping: `add_job`/`save_match_result` bodies, tag cap, request budget.

Reads a scored queue row (the shape `jobq`/`ats` rows carry once `/ai-jobhunter:score` has
written `fit_score`, `work_authorization`, `suggested_variant` and (optionally)
`score_reasons` / `skills` back into it — see spec §5) and builds the exact payload
dicts the `promote` skill later passes, verbatim, to jobsync's MCP tools. This module makes
no MCP call itself.

## No network I/O

This module imports nothing that can open a socket — no `urllib`, `http`, `socket`,
`requests`, or any MCP client. It only builds and validates plain dicts and strings; the
`promote` skill is the only thing that ever calls `add_job` / `add_jobs_batch` /
`save_match_result` / `save_match_results_batch`. Enforced by
`tests/test_promote.py::TestNoNetworkImports`, which parses this file's own AST rather than
trusting a comment.

## Row fields this module reads

- `company`, `jobTitle`, `jobDescription`, `location`, `source`, `jobType`, `jobUrl`,
  `workplaceType` — as `ats.normalize_*` / `jobq` rows already carry them.
- `fit_score` (int 0-100) and `work_authorization` (`open` / `unclear` / `closed`) — written
  by the scoring step. A row without `fit_score` has not been scored and is refused.
- `suggested_variant` — the scoring step's variant classification; falls back to
  `"unclassified"` when absent rather than refusing the whole row over it, since a missing
  variant is a softer defect than a missing score.
- `skills` — an optional ordered list of matched skill strings, already ranked by the
  scoring step; only the first `MAX_SKILL_TAGS` are kept (see `build_tags`).
- `score_reasons` — an optional `{dimension: reason}` mapping folded into the
  `matchText` body when present.

## Refusal is a gate, not a soft warning

Per spec §5, work authorization is a gate: a `closed` row must never reach jobsync, and an
unscored row cannot be mapped to a `recommendation` at all. Both `to_add_job` and
`to_match_text` call `_require_score`, which raises a named `PromoteError` subclass instead
of emitting a half-built payload.

## workplaceType canonicalisation

jobsync's enum is exactly `Remote` / `Hybrid` / `Onsite`. Postings spell it in whatever way
the source board used (`On-site`, `on site`, `REMOTE`, `in-office`). `_canonicalize_
workplace_type` folds out whitespace/hyphens/underscores and lower-cases before comparing,
so all of those validate — but a value that still does not match one of the three raises
`WorkplaceTypeError` rather than being guessed or silently dropped: `ats.py` treats an
*absent* arrangement as a fact worth leaving absent, but a *present-and-unrecognised* one is
a data problem worth surfacing loudly, not swallowing.

## Tag budget: 1 visa + 1 variant + up to 8 skill tags, hard-capped at 10

jobsync silently drops tags past the 10th. The visa and variant tags carry information this
plugin's own gating logic depends on (`work_authorization`, `suggested_variant`), so they
are always written first and are never at risk of truncation; skill tags fill the remaining
budget and are the ones that get cut when there are more than `MAX_SKILL_TAGS` of them.

## Request budget: 2 requests per job, batch or not

Per the jobsync MCP contract: a batch call costs one request *per item* (never one request
per call), and promoting one job costs `add_job` (or one item of `add_jobs_batch`) *plus*
`save_match_result` (or one item of `save_match_results_batch`) — two requests total,
whether or not either call was itself batched. `plan_budget` also clamps the caller's
`limit` to the jobsync-wide hourly ceiling of 60 requests, since a caller passing a larger
number (a stale config value, say) must not be taken as licence to exceed the real ceiling.

## Never emit a field the contract does not define

`to_add_job` builds its payload by naming each field explicitly rather than copying `row`
wholesale, so an extra key on the row (`fit_score`, `skills`, anything from a future scoring
version) never leaks into the jobsync payload. `allowDuplicate` is part of the jobsync
schema but is deliberately never emitted — the contract states this plugin does not use it
(upsert supersedes it for every re-run case this plugin has).
"""

import re

MAX_TAGS = 10
MAX_SKILL_TAGS = 8
MAX_BATCH_SIZE = 10
REQUESTS_PER_JOB = 2  # add_job (or one batch item) + save_match_result (or one batch item)
MAX_REQUESTS_PER_HOUR = 60
MIN_DESCRIPTION_LEN = 10
NA_DESCRIPTION = "N/A"

# jobsync gives a full match only to a posting of roughly 150 words or more.
# Below that it stores the match but flags it *Provisional*; with no posting
# text at all it refuses to match and tells the agent to fetch the posting
# first. Both thresholds live here so the two behaviours below cannot drift.
FULL_MATCH_MIN_WORDS = 150
MIN_MATCH_TEXT_BODY_LEN = 20

DEFAULT_VARIANT = "unclassified"

# fit_score -> recommendation, checked highest floor first (spec §5's score mapping).
_SCORE_BOUNDARIES = (
    (80, "strong"),
    (65, "good"),
    (50, "partial"),
    (0, "weak"),
)

_WORKPLACE_TYPES = {"remote": "Remote", "hybrid": "Hybrid", "onsite": "Onsite"}
_WORKPLACE_FOLD_RE = re.compile(r"[\s\-_]+")

_VALID_WORK_AUTH = frozenset({"open", "unclear", "closed"})

_WORK_AUTH_SENTENCES = {
    "open": "the posting states visa sponsorship, or the company hires globally.",
    "unclear": (
        "the posting does not state a sponsorship position; treat it as "
        "undetermined until confirmed."
    ),
    "closed": (
        "the posting requires existing work authorization with no sponsorship "
        "offered."
    ),
}

# Fields the jobsync `add_job` / `add_jobs_batch` schema actually defines (contract table,
# plan §"jobsync MCP contract"). Only row values under these keys are ever copied through.
_PASSTHROUGH_FIELDS = (
    "location",
    "source",
    "jobType",
    "status",
    "dueDate",
    "applied",
    "appliedDate",
    "jobUrl",
    "salaryRange",
)

_SLUG_WS_RE = re.compile(r"\s+")


class PromoteError(Exception):
    """Base class for every error this module raises."""


class ScoreMissingError(PromoteError):
    """Raised when a row has no `fit_score` — it has not been through /ai-jobhunter:score."""

    def __init__(self, row):
        ident = row.get("jobUrl") or f"{row.get('company')!r} / {row.get('jobTitle')!r}"
        super().__init__(
            f"row has no fit_score; cannot promote {ident} — run /ai-jobhunter:score first"
        )


class AuthorizationClosedError(PromoteError):
    """Raised when `work_authorization` is `closed` — the gate spec §5 requires."""

    def __init__(self, row):
        ident = row.get("jobUrl") or f"{row.get('company')!r} / {row.get('jobTitle')!r}"
        super().__init__(
            f"row is work_authorization=closed; refusing to promote {ident} "
            "(visa gate — see spec §5)"
        )


class TitleOnlyError(PromoteError):
    """The row carries no posting text, so jobsync would refuse to match it.

    Promoting it would spend two requests to store a job that can never carry
    a score. Re-run `/ai-jobhunter:discover` for the full posting first.
    """

    def __init__(self, row):
        super().__init__(
            "Refusing to promote a title-only row "
            f"({row.get('company')!r} / {row.get('jobTitle')!r}): jobsync needs "
            "the posting text to produce a match. Fetch the full posting first."
        )
        self.row = row


class WorkplaceTypeError(PromoteError):
    """Raised when `workplaceType` cannot be canonicalised to Remote/Hybrid/Onsite."""

    def __init__(self, raw):
        super().__init__(
            f"workplaceType {raw!r} does not canonicalise to Remote/Hybrid/Onsite"
        )


def _require_score(row):
    """Return `(fit_score, work_authorization)`, or raise a named `PromoteError`.

    Refuses a row with no `fit_score` (unscored) and a row whose `work_authorization` is
    `closed` (spec §5's gate) before any payload is built from it.
    """
    fit_score = row.get("fit_score")
    if fit_score is None:
        raise ScoreMissingError(row)
    work_authorization = row.get("work_authorization")
    if work_authorization == "closed":
        raise AuthorizationClosedError(row)
    return fit_score, work_authorization


def _recommendation_for(fit_score):
    if not isinstance(fit_score, int) or isinstance(fit_score, bool):
        raise PromoteError(f"fit_score must be an int 0-100, got {fit_score!r}")
    if not (0 <= fit_score <= 100):
        raise PromoteError(f"fit_score must be 0-100, got {fit_score!r}")
    for floor, label in _SCORE_BOUNDARIES:
        if fit_score >= floor:
            return label
    raise PromoteError(f"fit_score {fit_score} did not match any boundary")  # unreachable


def _canonicalize_workplace_type(raw):
    folded = _WORKPLACE_FOLD_RE.sub("", raw.strip().lower())
    value = _WORKPLACE_TYPES.get(folded)
    if value is None:
        raise WorkplaceTypeError(raw)
    return value


def match_quality(row):
    """Return `"full"` or `"provisional"` for the posting text on this row.

    jobsync flags a match built from a short posting as *Provisional*. Saying
    so up front is the difference between a user reading a low score as a bad
    fit and reading it as a thin posting.
    """
    text = _clean_description(row.get("jobDescription"))
    if text == NA_DESCRIPTION:
        raise TitleOnlyError(row)
    return "full" if len(text.split()) >= FULL_MATCH_MIN_WORDS else "provisional"


def _clean_description(raw):
    text = (raw or "").strip()
    if len(text) < MIN_DESCRIPTION_LEN:
        return NA_DESCRIPTION
    return text


def _slugify(value):
    return _SLUG_WS_RE.sub("-", value.strip().lower())


def _work_auth_bucket(work_authorization):
    bucket = work_authorization or "unclear"
    if bucket not in _VALID_WORK_AUTH:
        raise PromoteError(
            f"work_authorization must be one of {sorted(_VALID_WORK_AUTH)}, got {bucket!r}"
        )
    return bucket


def to_add_job(row):
    """Build the jobsync `add_job` payload for a scored queue row.

    Always sets `upsert: True` (the contract says use upsert on every re-run; `find_job` is
    deliberately not used because it doubles the request cost). Refuses via `PromoteError`
    when `row` has no `fit_score` or is `work_authorization=closed`. Only fields the jobsync
    contract defines are ever emitted. A title-only row is refused too: jobsync needs the
    posting text to produce a match, so storing one would spend two requests on a job that
    can never carry a score.
    """
    _require_score(row)
    match_quality(row)  # raises TitleOnlyError when there is no posting text

    payload = {
        "company": row["company"],
        "jobTitle": row["jobTitle"],
        "jobDescription": _clean_description(row.get("jobDescription")),
        "upsert": True,
        "tags": build_tags(row),
    }

    for key in _PASSTHROUGH_FIELDS:
        if key in row and row[key] is not None:
            payload[key] = row[key]

    workplace_type = row.get("workplaceType")
    if workplace_type:
        payload["workplaceType"] = _canonicalize_workplace_type(workplace_type)

    return payload


def to_match_text(row):
    """Build the `matchText` string for `save_match_result` / `save_match_results_batch`.

    The first line is exactly `SCORES: match=<fit_score> recommendation=<bucket>`, matching
    `^SCORES: match=\\d{1,3} recommendation=(strong|good|partial|weak)$`. The body that
    follows always names the work-authorization bucket and is always well over the 20
    character jobsync minimum, by construction (the fixed sentences below are each already
    longer than that on their own) rather than by padding after the fact.
    """
    fit_score, work_authorization = _require_score(row)
    recommendation = _recommendation_for(fit_score)
    bucket = _work_auth_bucket(work_authorization)
    variant = row.get("suggested_variant") or DEFAULT_VARIANT

    body_lines = [
        f"Work authorization: **{bucket}** — {_WORK_AUTH_SENTENCES[bucket]}",
        f"Suggested variant: {variant}.",
    ]
    if match_quality(row) == "provisional":
        body_lines.append(
            f"Match confidence: **Provisional** — the posting is under "
            f"{FULL_MATCH_MIN_WORDS} words, so jobsync will flag this match "
            "Provisional. A low score here may mean a thin posting rather than "
            "a poor fit."
        )
    reasons = row.get("score_reasons")
    if reasons:
        body_lines.append("")
        body_lines.append("Score breakdown:")
        for dimension, reason in reasons.items():
            body_lines.append(f"- **{dimension}**: {reason}")

    body = "\n".join(body_lines)
    if len(body) < MIN_MATCH_TEXT_BODY_LEN:
        # Defensive only: the fixed sentences above are always long enough on their own.
        # Never ship a short body — pad with the real explanation, not filler characters.
        raise PromoteError(
            f"matchText body is {len(body)} chars, under the {MIN_MATCH_TEXT_BODY_LEN} "
            "jobsync minimum"
        )

    return f"SCORES: match={fit_score} recommendation={recommendation}\n\n{body}"


def build_tags(row):
    """Build at most `MAX_TAGS` (10) tags: 1 visa tag, 1 variant tag, then up to
    `MAX_SKILL_TAGS` (8) skill tags.

    jobsync silently drops tags past the 10th, so the visa and variant tags are always
    written first — they must always survive truncation, which is the entire point of the
    cap. Skill tags are truncated, in row order, when there are more than 8.
    """
    _fit_score, work_authorization = _require_score(row)
    bucket = _work_auth_bucket(work_authorization)
    variant = row.get("suggested_variant") or DEFAULT_VARIANT

    tags = [f"visa:{bucket}", f"variant:{_slugify(variant)}"]
    for skill in (row.get("skills") or [])[:MAX_SKILL_TAGS]:
        tags.append(f"skill:{_slugify(skill)}")
    return tags[:MAX_TAGS]


def chunk(rows, size=MAX_BATCH_SIZE):
    """Split `rows` into batches that never exceed `MAX_BATCH_SIZE` (10) items — jobsync's
    `add_jobs_batch` maximum. `size` is clamped to that ceiling even if a caller asks for
    more; it may ask for fewer.
    """
    if size <= 0:
        raise PromoteError(f"chunk size must be positive, got {size}")
    effective_size = min(size, MAX_BATCH_SIZE)
    rows = list(rows)
    return [rows[i : i + effective_size] for i in range(0, len(rows), effective_size)]


def plan_budget(rows, limit):
    """Return `(sending, waiting, requests_needed)` for promoting `rows` within `limit`
    MCP requests.

    Costing rule from the jobsync contract: a batch costs one request *per item*, and
    promoting one job costs two requests (add-then-save-match), whether or not either call
    is itself batched. `limit` is clamped to `MAX_REQUESTS_PER_HOUR` (60) — the jobsync-wide
    hourly ceiling — regardless of what the caller passes, so a stale or optimistic config
    value can never be read as licence to exceed it.
    """
    rows = list(rows)
    effective_limit = max(0, min(limit, MAX_REQUESTS_PER_HOUR))
    sending = min(len(rows), effective_limit // REQUESTS_PER_JOB)
    waiting = len(rows) - sending
    requests_needed = sending * REQUESTS_PER_JOB
    return sending, waiting, requests_needed

"""LinkedIn postings through the Apify actor bebity/linkedin-jobs-scraper.

Only public guest listings are read; the user's own LinkedIn account is
never used. Auth is a single Bearer token (`APIFY_TOKEN`, see `envfile`),
never a query parameter.
"""

import datetime
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import ats

SOURCE_LINKEDIN = "LinkedIn"

_WORKPLACE_TYPES = {"onsite": "Onsite", "remote": "Remote", "hybrid": "Hybrid"}
_WORKPLACE_FOLD_RE = re.compile(r"[\s\-_]+")

# Verified against docs.apify.com and actor build 0.0.222, 2026-09-22.
_ACTOR = "bebity~linkedin-jobs-scraper"
_API = "https://api.apify.com/v2"
_PRICE_PER_JOB_USD = 0.0015
_CAP_HEADROOM = 1.5
_POLL_WAIT_SECONDS = 60
_CEILING_SECONDS = 900
_WORK_TYPE_CODES = {"on-site": "1", "remote": "2", "hybrid": "3"}
_WINDOWS = (("r86400", 86400), ("r604800", 604800))
_WINDOW_FALLBACK = "r2592000"
_TERMINAL_STATUSES = frozenset({"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"})

# `/jobs/view/<slug>-<id>` and `/jobs/view/<id>/` both carry the numeric
# posting id at the end of the path; `currentJobId=<id>` is the other place
# LinkedIn's own UI carries it (search-results deep links). Six digits is
# the minimum observed on real postings and rules out short unrelated
# numbers appearing elsewhere in a URL.
_JOB_ID_RE = re.compile(r"(?:/jobs/view/(?:[^/?#]*-)?|currentJobId=)(\d{6,})")


class ApifyError(Exception):
    """Base class for every error this module raises."""


class ApifyTokenMissingError(ApifyError):
    """`APIFY_TOKEN` is not set in the environment or in the given .env file."""


class ApifyCreditError(ApifyError):
    """Apify refused or would exceed the account's remaining credit."""


def _request(method, url, token, body=None, timeout=90):
    """Call the Apify REST API and return the parsed JSON response.

    The token goes only in the Authorization header, never the URL or an
    error message — Apify's own URLs already carry a query string
    (`maxItems=...`), so a naive "log the URL" would leak nothing here, but
    the discipline is kept explicit anyway since a future caller could add
    `?token=`.
    """
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", "gaspol-jobhunter/0.3")

    path = urllib.parse.urlsplit(url).path

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raw_body = exc.read()
        message = exc.reason
        try:
            parsed = json.loads(raw_body.decode("utf-8"))
            message = parsed.get("error", {}).get("message", message)
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            pass
        if exc.code == 402:
            raise ApifyCreditError(
                f"Apify {method} {path} failed: HTTP {exc.code} {message}"
            ) from exc
        raise ApifyError(
            f"Apify {method} {path} failed: HTTP {exc.code} {message}"
        ) from exc
    except (TimeoutError, urllib.error.URLError) as exc:
        raise ApifyError(f"Apify {method} {path} failed: {exc}") from exc

    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ApifyError(f"Apify {method} {path} returned a non-JSON response body") from exc


def charge_cap_usd(max_items):
    """The `maxTotalChargeUsd` ceiling for a run of up to `max_items` postings.

    Headroom above the raw per-job price absorbs the actor-start charge and
    any per-GB overage without under-capping a run that would otherwise
    succeed.
    """
    return round(max_items * _PRICE_PER_JOB_USD * _CAP_HEADROOM, 4)


def build_actor_input(linkedin_cfg, max_items, window, *, enrich_company=True):
    """Build the bebity actor input dict for one run.

    `rows` is the per-title×location search size: `max_items` spread evenly
    across every (keyword, location) pair, rounded up so the run's declared
    ceiling is never undershot by integer division.
    """
    keywords = linkedin_cfg["keywords"]
    locations = linkedin_cfg["locations"]
    rows = math.ceil(max_items / (len(keywords) * len(locations)))

    actor_input = {
        "titles": keywords,
        "locations": locations,
        "rows": rows,
        "publishedAt": window,
        "companyProfile": False,
        "enrichCompany": enrich_company,
    }
    work_types = linkedin_cfg.get("work_types") or []
    if work_types:
        actor_input["workTypes"] = [_WORK_TYPE_CODES[w] for w in work_types]
    return actor_input


def remaining_credit_usd(token):
    data = _request("GET", f"{_API}/users/me/limits", token)["data"]
    return data["limits"]["maxMonthlyUsageUsd"] - data["current"]["monthlyUsageUsd"]


def fetch_linkedin(actor_input, max_items, token, dest, *, clock=time.monotonic, sleep=time.sleep):
    """Run the bebity actor to completion and stream its dataset to `dest`.

    Polls with a 60 s server-side long-poll (`waitForFinish=60`) so most runs
    resolve in one or two round trips. `clock` is checked on every loop
    iteration; past `_CEILING_SECONDS` the run is aborted (a best-effort
    POST) and `fetch_linkedin` raises rather than polling forever on a stuck
    run.
    """
    cap = charge_cap_usd(max_items)
    start_url = f"{_API}/acts/{_ACTOR}/runs?maxItems={max_items}&maxTotalChargeUsd={cap}"
    started = _request("POST", start_url, token, body=actor_input)["data"]
    run_id = started["id"]
    status = started["status"]
    usd_charged = started.get("usageTotalUsd", 0)
    polled = started

    deadline_start = clock()
    while status not in _TERMINAL_STATUSES:
        if clock() - deadline_start > _CEILING_SECONDS:
            _request("POST", f"{_API}/actor-runs/{run_id}/abort", token)
            raise ApifyError(f"LinkedIn run {run_id} aborted after {_CEILING_SECONDS} s")
        poll_url = f"{_API}/actor-runs/{run_id}?waitForFinish={_POLL_WAIT_SECONDS}"
        polled = _request("GET", poll_url, token)["data"]
        status = polled["status"]
        usd_charged = polled.get("usageTotalUsd", usd_charged)

    if status != "SUCCEEDED":
        raise ApifyError(f"LinkedIn run {run_id} ended {status}")

    dataset_id = polled["defaultDatasetId"]
    items_url = f"{_API}/datasets/{dataset_id}/items?format=json&clean=true&limit={max_items}"
    items = _request("GET", items_url, token)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(items, f)

    print(
        f"apify.fetch: run={run_id} status={status} returned={len(items)} usd={usd_charged}",
        file=sys.stderr,
    )
    return {"run_id": run_id, "status": status, "returned": len(items), "usd_charged": usd_charged}


def choose_window(state_path, now):
    """Return the Apify `publishedAt` window value for the next fetch.

    A recent last success narrows the window (cutting re-fetch volume); no
    file, or one that cannot be parsed, widens it all the way out rather
    than risk silently missing postings.
    """
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        last_success_at = datetime.datetime.fromisoformat(state["last_success_at"])
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        print(f"apify.choose_window: no usable state at {state_path}, using widest window", file=sys.stderr)
        return _WINDOW_FALLBACK

    elapsed = (now - last_success_at).total_seconds()
    for value, seconds in _WINDOWS:
        if elapsed <= seconds:
            return value
    return _WINDOW_FALLBACK


def write_state(state_path, now):
    """Atomically record the moment of the last successful fetch."""
    tmp_path = f"{state_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({"last_success_at": now.isoformat()}, f)
    os.replace(tmp_path, state_path)


def _canonical_job_url(raw):
    match = _JOB_ID_RE.search(raw or "")
    if not match:
        return None
    return f"https://www.linkedin.com/jobs/view/{match.group(1)}/"


def _fold_workplace_type(raw_value):
    if not raw_value:
        return None
    folded = _WORKPLACE_FOLD_RE.sub("", raw_value.strip().lower())
    return _WORKPLACE_TYPES.get(folded)


def _normalize_linkedin_job(job):
    for key in ("companyName", "title", "description"):
        if not job.get(key):
            raise ats.MissingFieldError(SOURCE_LINKEDIN, key)

    job_id = job.get("id")
    canonical = None
    if isinstance(job_id, str) and job_id.isdigit():
        canonical = f"https://www.linkedin.com/jobs/view/{job_id}/"
    if not canonical:
        canonical = _canonical_job_url(job.get("jobUrl"))
    if not canonical:
        raise ats.MissingFieldError(SOURCE_LINKEDIN, "jobUrl")

    row = {
        "company": job["companyName"],
        "jobTitle": job["title"],
        "jobDescription": ats._clean_description(job["description"]),
        "jobUrl": canonical,
        "source": SOURCE_LINKEDIN,
    }

    location = (job.get("location") or "").strip()
    if location:
        row["location"] = location

    contract_type = (job.get("contractType") or "").strip()
    if contract_type:
        row["jobType"] = contract_type

    workplace_type = _fold_workplace_type(job.get("workType"))
    if workplace_type:
        row["workplaceType"] = workplace_type

    return row


def normalize_linkedin(path):
    """Read an Apify bebity dataset JSON file from disk and return queue rows."""
    with open(path, "r", encoding="utf-8") as f:
        jobs = json.load(f)
    if not isinstance(jobs, list):
        raise ApifyError("LinkedIn dataset is not a JSON array")

    rows, skipped = ats._normalize_all(SOURCE_LINKEDIN, jobs, _normalize_linkedin_job)
    return ats._Rows(rows, skipped)

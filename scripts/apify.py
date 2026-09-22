"""LinkedIn postings through the Apify actor bebity/linkedin-jobs-scraper.

Only public guest listings are read; the user's own LinkedIn account is
never used. Auth is a single Bearer token (`APIFY_TOKEN`, see `envfile`),
never a query parameter.
"""

import json
import re

import ats

SOURCE_LINKEDIN = "LinkedIn"

_WORKPLACE_TYPES = {"onsite": "Onsite", "remote": "Remote", "hybrid": "Hybrid"}
_WORKPLACE_FOLD_RE = re.compile(r"[\s\-_]+")

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

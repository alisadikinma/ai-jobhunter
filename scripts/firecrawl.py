"""Board search/scrape through Firecrawl REST API v2.

Every call is a single Bearer-token POST/GET; the key is never in a URL or
an error message. A run's spend is tracked in a small `Budget` file so a
skill can refuse a call before it happens rather than discovering the
ceiling was passed after the fact.
"""

import json
import math
import os
import time
import urllib.error
import urllib.request

_API = "https://api.firecrawl.dev/v2"
# 3 total attempts means 2 backoff intervals between them (after attempt 1
# and after attempt 2; attempt 3 either succeeds or raises) — a third
# backoff value has nothing to precede, so it is not carried here.
_RETRIES = 3
_BACKOFF_SECONDS = (2, 4)
_RETRY_AFTER_CAP_SECONDS = 60
_RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


class FirecrawlError(Exception):
    """Base class for every error this module raises."""


class FirecrawlKeyMissingError(FirecrawlError):
    """`FIRECRAWL_API_KEY` is not set in the environment or in the given .env file."""


class FirecrawlCreditError(FirecrawlError):
    """Firecrawl rejected the call for insufficient account credit (HTTP 402)."""


class FirecrawlBudgetError(FirecrawlError):
    """This run's own credit ceiling would be exceeded by the next call."""


def _error_text(raw_body):
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
        return parsed.get("error") or parsed.get("details") or ""
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
        return ""


def _request(method, path, key, body=None):
    url = f"{_API}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None

    last_error_text = ""
    last_status = None
    for attempt in range(_RETRIES):
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {key}")
        request.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw_body = exc.read()
            if exc.code == 401:
                raise FirecrawlError("Firecrawl rejected the key (HTTP 401)") from exc
            if exc.code == 402:
                raise FirecrawlCreditError(
                    f"Firecrawl {method} {path} failed: HTTP 402 {_error_text(raw_body)}"
                ) from exc
            if exc.code in _RETRYABLE_STATUSES and attempt < _RETRIES - 1:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                if retry_after is not None:
                    try:
                        delay = min(float(retry_after), _RETRY_AFTER_CAP_SECONDS)
                    except ValueError:
                        delay = _BACKOFF_SECONDS[attempt]
                else:
                    delay = _BACKOFF_SECONDS[attempt]
                time.sleep(delay)
                last_status = exc.code
                last_error_text = _error_text(raw_body)
                continue
            raise FirecrawlError(
                f"Firecrawl {method} {path} failed: HTTP {exc.code} {_error_text(raw_body)}"
            ) from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            if attempt < _RETRIES - 1:
                time.sleep(_BACKOFF_SECONDS[attempt])
                continue
            raise FirecrawlError(f"Firecrawl {method} {path} failed: {exc}") from exc
        else:
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise FirecrawlError(
                    f"Firecrawl {method} {path} returned a non-JSON response body"
                ) from exc
            if not parsed.get("success", False):
                raise FirecrawlError(
                    f"Firecrawl {method} {path} failed: {parsed.get('error', 'success: false')}"
                )
            return parsed

    raise FirecrawlError(
        f"Firecrawl {method} {path} failed after {_RETRIES} attempts: "
        f"HTTP {last_status} {last_error_text}"
    )


def search(key, query, limit, dest, *, tbs=None, location=None):
    if not 1 <= limit <= 100:
        raise ValueError(f"limit must be between 1 and 100, got {limit!r}")

    body = {
        "query": query,
        "limit": limit,
        "scrapeOptions": {
            "formats": ["markdown"],
            "onlyMainContent": True,
            "proxy": "basic",
        },
    }
    if tbs is not None:
        body["tbs"] = tbs
    if location is not None:
        body["location"] = location

    parsed = _request("POST", "/search", key, body=body)
    web = parsed["data"]["web"]
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(web, f)
    return len(web), parsed.get("creditsUsed")


def scrape(key, url, dest):
    body = {
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True,
        "proxy": "basic",
        "timeout": 60000,
    }
    parsed = _request("POST", "/scrape", key, body=body)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(parsed["data"], f)
    return parsed.get("creditsUsed")


def remaining_credits(key):
    parsed = _request("GET", "/team/credit-usage", key)
    return parsed["data"]["remainingCredits"]


def estimate(kind, limit=None):
    if kind == "search":
        return 2 * math.ceil(limit / 10) + limit
    if kind == "scrape":
        return 1
    raise ValueError(f"unknown estimate kind {kind!r}")


class Budget:
    """A run's own credit ceiling, tracked in a small JSON file.

    `reported` accumulates `credits_used` values Firecrawl itself returned;
    `spent()` also cross-checks against the account's remaining-credit delta
    so a call whose response omitted `creditsUsed` (scrape's is documented
    as optional) still counts against the ceiling.
    """

    def __init__(self, path, ceiling, start_remaining, reported=0):
        self.path = path
        self.ceiling = ceiling
        self.start_remaining = start_remaining
        self.reported = reported

    @classmethod
    def open(cls, path, ceiling, remaining_now):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    state = json.load(f)
                return cls(
                    path,
                    state["ceiling"],
                    state["start_remaining"],
                    reported=state.get("reported", 0),
                )
            except (OSError, json.JSONDecodeError, KeyError) as exc:
                raise FirecrawlError(f"corrupted Firecrawl run-state file: {path}") from exc
        budget = cls(path, ceiling, remaining_now)
        budget._save()
        return budget

    def spent(self, remaining_now):
        delta = self.start_remaining - remaining_now
        return max(self.reported, delta)

    def check(self, kind, limit, remaining_now):
        estimated = estimate(kind, limit)
        spent = self.spent(remaining_now)
        if spent + estimated > self.ceiling:
            raise FirecrawlBudgetError(
                f"Firecrawl budget {self.ceiling} credits: {spent} spent, "
                f"next call needs up to {estimated}"
            )

    def record(self, credits_used):
        self.reported += credits_used or 0
        self._save()

    def _save(self):
        tmp_path = f"{self.path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "start_remaining": self.start_remaining,
                    "reported": self.reported,
                    "ceiling": self.ceiling,
                },
                f,
            )
        os.replace(tmp_path, self.path)

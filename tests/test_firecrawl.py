import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import firecrawl  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
SEARCH_FIXTURE = os.path.join(FIXTURES, "firecrawl_search.json")


class _FakeResponse:
    def __init__(self, body_bytes, status=200):
        self.status = status
        self._body = body_bytes

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, size=-1):
        chunk, self._body = self._body, b""
        return chunk


def _json_response(payload, status=200):
    return _FakeResponse(json.dumps(payload).encode("utf-8"), status=status)


def _http_error(url, code, payload, headers=None, reason="Error"):
    body = json.dumps(payload).encode("utf-8") if payload is not None else b""
    from email.message import Message

    hdrs = Message()
    for k, v in (headers or {}).items():
        hdrs[k] = v
    return urllib.error.HTTPError(url, code, reason, hdrs, io.BytesIO(body))


class _FakeUrlopen:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


_SEARCH_SUCCESS = {
    "success": True,
    "data": {
        "web": [
            {"url": "https://a.example.com", "markdown": "# A"},
            {"url": "https://b.example.com", "markdown": "# B"},
        ]
    },
    "creditsUsed": 4,
}


class TestSearch(unittest.TestCase):
    def test_writes_data_web_to_dest(self):
        fake = _FakeUrlopen([_json_response(_SEARCH_SUCCESS)])
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.json")
            with unittest.mock.patch("urllib.request.urlopen", fake):
                count, credits_used = firecrawl.search("key", "software engineer", 2, dest)
            with open(dest, "r", encoding="utf-8") as f:
                data = json.load(f)
        self.assertEqual(data, _SEARCH_SUCCESS["data"]["web"])
        self.assertEqual(count, 2)
        self.assertEqual(credits_used, 4)

    def test_request_body_exact_including_proxy_basic(self):
        fake = _FakeUrlopen([_json_response(_SEARCH_SUCCESS)])
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.json")
            with unittest.mock.patch("urllib.request.urlopen", fake):
                firecrawl.search("key", "software engineer", 2, dest)
        body = json.loads(fake.requests[0].data.decode("utf-8"))
        self.assertEqual(
            body,
            {
                "query": "software engineer",
                "limit": 2,
                "scrapeOptions": {
                    "formats": ["markdown"],
                    "onlyMainContent": True,
                    "proxy": "basic",
                },
            },
        )

    def test_bearer_header_present(self):
        fake = _FakeUrlopen([_json_response(_SEARCH_SUCCESS)])
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.json")
            with unittest.mock.patch("urllib.request.urlopen", fake):
                firecrawl.search("secret-key", "x", 1, dest)
        self.assertEqual(fake.requests[0].get_header("Authorization"), "Bearer secret-key")

    def test_key_absent_from_url_and_error_message(self):
        fake = _FakeUrlopen([_http_error("url", 401, {"error": "bad key"})])
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.json")
            with unittest.mock.patch("urllib.request.urlopen", fake):
                with self.assertRaises(firecrawl.FirecrawlError) as ctx:
                    firecrawl.search("secret-key", "x", 1, dest)
        self.assertNotIn("secret-key", str(ctx.exception))
        self.assertNotIn("secret-key", fake.requests[0].full_url)

    def test_401_raises_firecrawl_error(self):
        fake = _FakeUrlopen([_http_error("url", 401, {"error": "bad key"})])
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.json")
            with unittest.mock.patch("urllib.request.urlopen", fake):
                with self.assertRaises(firecrawl.FirecrawlError) as ctx:
                    firecrawl.search("key", "x", 1, dest)
        self.assertIn("401", str(ctx.exception))

    def test_402_raises_firecrawl_credit_error_and_is_not_retried(self):
        fake = _FakeUrlopen([_http_error("url", 402, {"error": "no credit"})])
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.json")
            with unittest.mock.patch("urllib.request.urlopen", fake):
                with self.assertRaises(firecrawl.FirecrawlCreditError):
                    firecrawl.search("key", "x", 1, dest)
        self.assertEqual(len(fake.requests), 1)

    def test_429_with_retry_after_sleeps_then_succeeds(self):
        fake = _FakeUrlopen(
            [
                _http_error("url", 429, {"error": "rate limited"}, headers={"Retry-After": "3"}),
                _json_response(_SEARCH_SUCCESS),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.json")
            with unittest.mock.patch("urllib.request.urlopen", fake), unittest.mock.patch(
                "firecrawl.time.sleep"
            ) as sleep_mock:
                count, _credits = firecrawl.search("key", "x", 1, dest)
        self.assertEqual(count, 2)
        sleep_mock.assert_called_once_with(3.0)

    def test_5xx_three_times_raises_firecrawl_error(self):
        fake = _FakeUrlopen(
            [
                _http_error("url", 500, {"error": "boom"}),
                _http_error("url", 500, {"error": "boom"}),
                _http_error("url", 500, {"error": "boom"}),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.json")
            with unittest.mock.patch("urllib.request.urlopen", fake), unittest.mock.patch(
                "firecrawl.time.sleep"
            ):
                with self.assertRaises(firecrawl.FirecrawlError):
                    firecrawl.search("key", "x", 1, dest)
        self.assertEqual(len(fake.requests), 3)

    def test_success_false_raises_firecrawl_error(self):
        fake = _FakeUrlopen([_json_response({"success": False, "error": "nope"})])
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.json")
            with unittest.mock.patch("urllib.request.urlopen", fake):
                with self.assertRaises(firecrawl.FirecrawlError):
                    firecrawl.search("key", "x", 1, dest)

    def test_limit_zero_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.json")
            with self.assertRaises(ValueError):
                firecrawl.search("key", "x", 0, dest)

    def test_limit_101_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.json")
            with self.assertRaises(ValueError):
                firecrawl.search("key", "x", 101, dest)


class TestScrape(unittest.TestCase):
    def test_writes_data_to_dest_and_returns_credits(self):
        payload = {"success": True, "data": {"markdown": "# Page"}, "creditsUsed": 1}
        fake = _FakeUrlopen([_json_response(payload)])
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.json")
            with unittest.mock.patch("urllib.request.urlopen", fake):
                credits_used = firecrawl.scrape("key", "https://example.com", dest)
            with open(dest, "r", encoding="utf-8") as f:
                data = json.load(f)
        self.assertEqual(data, {"markdown": "# Page"})
        self.assertEqual(credits_used, 1)

    def test_credits_used_optional_returns_none(self):
        payload = {"success": True, "data": {"markdown": "# Page"}}
        fake = _FakeUrlopen([_json_response(payload)])
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.json")
            with unittest.mock.patch("urllib.request.urlopen", fake):
                credits_used = firecrawl.scrape("key", "https://example.com", dest)
        self.assertIsNone(credits_used)


class TestEstimate(unittest.TestCase):
    def test_search_limit_1(self):
        self.assertEqual(firecrawl.estimate("search", limit=1), 2 * 1 + 1)

    def test_search_limit_10(self):
        self.assertEqual(firecrawl.estimate("search", limit=10), 2 * 1 + 10)

    def test_search_limit_11(self):
        self.assertEqual(firecrawl.estimate("search", limit=11), 2 * 2 + 11)

    def test_scrape_is_1(self):
        self.assertEqual(firecrawl.estimate("scrape"), 1)


class TestBudget(unittest.TestCase):
    def test_fresh_file_created_on_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "run-state.json")
            budget = firecrawl.Budget.open(path, 150, 1000)
            self.assertTrue(os.path.exists(path))
            self.assertEqual(budget.spent(1000), 0)

    def test_over_ceiling_refuses_before_the_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "run-state.json")
            budget = firecrawl.Budget.open(path, 10, 1000)
            with self.assertRaises(firecrawl.FirecrawlBudgetError):
                budget.check("search", 100, 1000)

    def test_spent_uses_max_of_reported_and_delta_reported_higher(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "run-state.json")
            budget = firecrawl.Budget.open(path, 150, 1000)
            budget.record(20)
            self.assertEqual(budget.spent(995), 20)

    def test_spent_uses_max_of_reported_and_delta_delta_higher(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "run-state.json")
            budget = firecrawl.Budget.open(path, 150, 1000)
            budget.record(2)
            self.assertEqual(budget.spent(970), 30)

    def test_corrupted_file_raises_firecrawl_error_naming_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "run-state.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("not json{{{")
            with self.assertRaises(firecrawl.FirecrawlError) as ctx:
                firecrawl.Budget.open(path, 150, 1000)
            self.assertIn(path, str(ctx.exception))

    def test_record_accumulates_across_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "run-state.json")
            budget = firecrawl.Budget.open(path, 150, 1000)
            budget.record(4)
            budget.record(1)
            reopened = firecrawl.Budget.open(path, 150, 1000)
            self.assertEqual(reopened.reported, 5)


class TestRemainingCredits(unittest.TestCase):
    def test_reads_remaining_credits(self):
        payload = {
            "success": True,
            "data": {
                "remainingCredits": 42,
                "planCredits": 1000,
                "billingPeriodStart": "2026-09-01",
                "billingPeriodEnd": "2026-10-01",
            },
        }
        fake = _FakeUrlopen([_json_response(payload)])
        with unittest.mock.patch("urllib.request.urlopen", fake):
            remaining = firecrawl.remaining_credits("key")
        self.assertEqual(remaining, 42)


if __name__ == "__main__":
    unittest.main()

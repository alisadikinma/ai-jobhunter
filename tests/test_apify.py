import datetime
import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import apify  # noqa: E402
import jobq  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
APIFY_LINKEDIN_FIXTURE = os.path.join(FIXTURES, "apify_linkedin.json")
FIRECRAWL_SEARCH_FIXTURE = os.path.join(FIXTURES, "firecrawl_search.json")


def _write_json(tmp_dir, name, data):
    path = os.path.join(tmp_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


class TestApifyLinkedinFixtureShape(unittest.TestCase):
    def test_fixture_is_a_json_list_of_real_postings(self):
        with open(APIFY_LINKEDIN_FIXTURE, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)
        for item in data:
            self.assertIn("title", item)
            self.assertIn("companyName", item)
            self.assertIn("description", item)
            self.assertIn("jobUrl", item)


class TestFirecrawlSearchFixtureShape(unittest.TestCase):
    def test_fixture_is_a_real_search_response(self):
        with open(FIRECRAWL_SEARCH_FIXTURE, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertTrue(data["success"])
        web = data["data"]["web"]
        self.assertIsInstance(web, list)
        self.assertGreaterEqual(len(web), 1)
        for item in web:
            self.assertIn("url", item)
            self.assertIn("markdown", item)


class TestNormalizeLinkedinRealFixture(unittest.TestCase):
    def test_rows_from_real_fixture_have_source_and_canonical_url(self):
        rows = apify.normalize_linkedin(APIFY_LINKEDIN_FIXTURE)
        self.assertGreaterEqual(len(rows), 1)
        for row in rows:
            self.assertEqual(row["source"], apify.SOURCE_LINKEDIN)
            self.assertRegex(
                row["jobUrl"], r"^https://www\.linkedin\.com/jobs/view/\d{6,}/$"
            )


class TestCanonicalJobUrl(unittest.TestCase):
    def test_slug_and_id_with_tracking_params(self):
        self.assertEqual(
            apify._canonical_job_url(
                "https://www.linkedin.com/jobs/view/senior-ai-engineer-at-acme-4012345678?refId=x&trk=y"
            ),
            "https://www.linkedin.com/jobs/view/4012345678/",
        )

    def test_bare_id_path(self):
        self.assertEqual(
            apify._canonical_job_url("https://www.linkedin.com/jobs/view/4012345678/"),
            "https://www.linkedin.com/jobs/view/4012345678/",
        )

    def test_current_job_id_query_param(self):
        self.assertEqual(
            apify._canonical_job_url(
                "https://www.linkedin.com/jobs/search?currentJobId=4012345678"
            ),
            "https://www.linkedin.com/jobs/view/4012345678/",
        )

    def test_no_match_returns_none(self):
        self.assertIsNone(apify._canonical_job_url("https://www.linkedin.com/jobs/"))


class TestNormalizeLinkedinJob(unittest.TestCase):
    def _base_job(self, **overrides):
        job = {
            "title": "Software Engineer",
            "companyName": "Acme",
            "description": "Build things at Acme for a living, every single day.",
            "jobUrl": "https://www.linkedin.com/jobs/view/4012345678/",
        }
        job.update(overrides)
        return job

    def test_prefers_id_field_over_url(self):
        job = self._base_job(
            jobUrl="https://www.linkedin.com/jobs/view/bad-slug/", id="9012345678"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(tmp, "d.json", [job])
            rows = apify.normalize_linkedin(path)
        self.assertEqual(rows[0]["jobUrl"], "https://www.linkedin.com/jobs/view/9012345678/")

    def test_no_canonical_id_skipped_naming_joburl(self):
        job = self._base_job(jobUrl="https://www.linkedin.com/jobs/")
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(tmp, "d.json", [job, self._base_job()])
            rows = apify.normalize_linkedin(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows.skipped), 1)
        self.assertIn("jobUrl", rows.skipped[0]["error"])

    def test_missing_title_skipped_naming_title(self):
        job = self._base_job()
        del job["title"]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(tmp, "d.json", [job, self._base_job()])
            rows = apify.normalize_linkedin(path)
        self.assertEqual(len(rows), 1)
        self.assertIn("title", rows.skipped[0]["error"])

    def test_every_posting_bad_raises_missing_field_error(self):
        job = self._base_job()
        del job["title"]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(tmp, "d.json", [job])
            with self.assertRaises(apify.ats.MissingFieldError):
                apify.normalize_linkedin(path)

    def test_work_type_folds_case_and_separators(self):
        for raw_value in ("Remote", "on-site", "On Site", "HYBRID"):
            job = self._base_job(workType=raw_value)
            with tempfile.TemporaryDirectory() as tmp:
                path = _write_json(tmp, "d.json", [job])
                rows = apify.normalize_linkedin(path)
            self.assertIn("workplaceType", rows[0], f"failed for {raw_value!r}")

    def test_contract_work_type_has_no_workplace_type(self):
        job = self._base_job(workType="Contract")
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(tmp, "d.json", [job])
            rows = apify.normalize_linkedin(path)
        self.assertNotIn("workplaceType", rows[0])

    def test_same_id_different_tracking_yields_same_row_key(self):
        job_a = self._base_job(
            jobUrl="https://www.linkedin.com/jobs/view/senior-eng-4012345678?trk=a"
        )
        job_b = self._base_job(
            jobUrl="https://www.linkedin.com/jobs/view/4012345678/?refId=zzz"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(tmp, "d.json", [job_a, job_b])
            rows = apify.normalize_linkedin(path)
        self.assertEqual(jobq.row_key(rows[0]), jobq.row_key(rows[1]))

    def test_non_list_json_raises_apify_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(tmp, "d.json", {"not": "a list"})
            with self.assertRaises(apify.ApifyError):
                apify.normalize_linkedin(path)


class _FakeAPIResponse:
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
    return _FakeAPIResponse(json.dumps(payload).encode("utf-8"), status=status)


def _http_error(url, code, payload, reason="Error"):
    body = json.dumps(payload).encode("utf-8") if payload is not None else b""
    return urllib.error.HTTPError(url, code, reason, None, io.BytesIO(body))


class _FakeUrlopen:
    """Returns canned responses/exceptions in order; records every Request."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


_RUN_START = {"data": {"id": "run1", "status": "RUNNING", "defaultDatasetId": "ds1"}}
_RUN_POLL_RUNNING = {"data": {"id": "run1", "status": "RUNNING", "defaultDatasetId": "ds1"}}
_RUN_POLL_SUCCEEDED = {
    "data": {
        "id": "run1",
        "status": "SUCCEEDED",
        "defaultDatasetId": "ds1",
        "usageTotalUsd": 0.0075,
    }
}
_ITEMS = [{"title": "Software Engineer", "companyName": "Acme"}]


class TestFetchLinkedinSuccess(unittest.TestCase):
    def _fake(self, extra_responses=()):
        responses = [
            _json_response(_RUN_START, status=201),
            _json_response(_RUN_POLL_RUNNING),
            _json_response(_RUN_POLL_SUCCEEDED),
            _json_response(_ITEMS),
            *extra_responses,
        ]
        return _FakeUrlopen(responses)

    def test_success_path_returns_report_and_writes_dataset(self):
        fake = self._fake()
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "items.json")
            with unittest.mock.patch("urllib.request.urlopen", fake):
                result = apify.fetch_linkedin({"titles": ["x"]}, 5, "secret-token", dest)
            with open(dest, "r", encoding="utf-8") as f:
                self.assertEqual(json.load(f), _ITEMS)
        self.assertEqual(result["run_id"], "run1")
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["returned"], 1)
        self.assertEqual(result["usd_charged"], 0.0075)

    def test_bearer_header_present_on_every_request(self):
        fake = self._fake()
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "items.json")
            with unittest.mock.patch("urllib.request.urlopen", fake):
                apify.fetch_linkedin({"titles": ["x"]}, 5, "secret-token", dest)
        self.assertEqual(len(fake.requests), 4)
        for req in fake.requests:
            self.assertEqual(req.get_header("Authorization"), "Bearer secret-token")

    def test_no_request_url_contains_the_token(self):
        fake = self._fake()
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "items.json")
            with unittest.mock.patch("urllib.request.urlopen", fake):
                apify.fetch_linkedin({"titles": ["x"]}, 5, "secret-token", dest)
        for req in fake.requests:
            self.assertNotIn("secret-token", req.full_url)

    def test_start_url_has_max_items_and_charge_cap_for_100_items(self):
        responses = [
            _json_response(
                {"data": {"id": "r", "status": "SUCCEEDED", "defaultDatasetId": "d", "usageTotalUsd": 0.1}},
                status=201,
            ),
            _json_response([]),
        ]
        fake = _FakeUrlopen(responses)
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "items.json")
            with unittest.mock.patch("urllib.request.urlopen", fake):
                apify.fetch_linkedin({"titles": ["x"]}, 100, "tok", dest)
        start_url = fake.requests[0].full_url
        self.assertIn("maxItems=100", start_url)
        self.assertIn("maxTotalChargeUsd=0.225", start_url)

    def test_empty_dataset_returns_zero_no_error(self):
        responses = [
            _json_response(
                {"data": {"id": "r", "status": "SUCCEEDED", "defaultDatasetId": "d", "usageTotalUsd": 0}},
                status=201,
            ),
            _json_response([]),
        ]
        fake = _FakeUrlopen(responses)
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "items.json")
            with unittest.mock.patch("urllib.request.urlopen", fake):
                result = apify.fetch_linkedin({"titles": ["x"]}, 5, "tok", dest)
        self.assertEqual(result["returned"], 0)


class TestBuildActorInputRows(unittest.TestCase):
    def test_two_keywords_one_location_100_items_gives_50_rows(self):
        cfg = {"keywords": ["a", "b"], "locations": ["US"], "work_types": []}
        actor_input = apify.build_actor_input(cfg, 100, "r604800")
        self.assertEqual(actor_input["rows"], 50)

    def test_three_keywords_one_location_100_items_gives_34_rows(self):
        cfg = {"keywords": ["a", "b", "c"], "locations": ["US"], "work_types": []}
        actor_input = apify.build_actor_input(cfg, 100, "r604800")
        self.assertEqual(actor_input["rows"], 34)

    def test_work_types_omitted_when_empty(self):
        cfg = {"keywords": ["a"], "locations": ["US"], "work_types": []}
        actor_input = apify.build_actor_input(cfg, 10, "r604800")
        self.assertNotIn("workTypes", actor_input)

    def test_work_types_mapped_to_codes(self):
        cfg = {"keywords": ["a"], "locations": ["US"], "work_types": ["remote", "hybrid"]}
        actor_input = apify.build_actor_input(cfg, 10, "r604800")
        self.assertEqual(actor_input["workTypes"], ["2", "3"])


class TestFetchLinkedinErrors(unittest.TestCase):
    def _run_with(self, responses):
        fake = _FakeUrlopen(responses)
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "items.json")
            with unittest.mock.patch("urllib.request.urlopen", fake):
                apify.fetch_linkedin({"titles": ["x"]}, 5, "secret-token", dest)

    def test_401_raises_apify_error_naming_status(self):
        responses = [_http_error("url", 401, {"error": {"message": "bad token"}})]
        with self.assertRaises(apify.ApifyError) as ctx:
            self._run_with(responses)
        self.assertIn("HTTP 401", str(ctx.exception))

    def test_402_raises_apify_credit_error(self):
        responses = [_http_error("url", 402, {"error": {"message": "no credit"}})]
        with self.assertRaises(apify.ApifyCreditError):
            self._run_with(responses)

    def test_404_raises_apify_error(self):
        responses = [_http_error("url", 404, {"error": {"message": "not found"}})]
        with self.assertRaises(apify.ApifyError) as ctx:
            self._run_with(responses)
        self.assertIn("HTTP 404", str(ctx.exception))

    def test_429_raises_apify_error(self):
        responses = [_http_error("url", 429, {"error": {"message": "rate limited"}})]
        with self.assertRaises(apify.ApifyError) as ctx:
            self._run_with(responses)
        self.assertIn("HTTP 429", str(ctx.exception))

    def test_terminal_failed_status_raises_naming_status(self):
        responses = [
            _json_response({"data": {"id": "r", "status": "FAILED", "defaultDatasetId": "d"}}, status=201),
        ]
        with self.assertRaises(apify.ApifyError) as ctx:
            self._run_with(responses)
        self.assertIn("FAILED", str(ctx.exception))

    def test_terminal_aborted_status_raises_naming_status(self):
        responses = [
            _json_response({"data": {"id": "r", "status": "ABORTED", "defaultDatasetId": "d"}}, status=201),
        ]
        with self.assertRaises(apify.ApifyError) as ctx:
            self._run_with(responses)
        self.assertIn("ABORTED", str(ctx.exception))

    def test_terminal_timed_out_status_raises_naming_status(self):
        responses = [
            _json_response({"data": {"id": "r", "status": "TIMED-OUT", "defaultDatasetId": "d"}}, status=201),
        ]
        with self.assertRaises(apify.ApifyError) as ctx:
            self._run_with(responses)
        self.assertIn("TIMED-OUT", str(ctx.exception))

    def test_non_json_body_raises_apify_error(self):
        fake = _FakeUrlopen([_FakeAPIResponse(b"<html>not json</html>", status=201)])
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "items.json")
            with unittest.mock.patch("urllib.request.urlopen", fake):
                with self.assertRaises(apify.ApifyError):
                    apify.fetch_linkedin({"titles": ["x"]}, 5, "tok", dest)

    def test_token_absent_from_error_message_and_stderr(self):
        responses = [_http_error("url", 401, {"error": {"message": "bad token"}})]
        buf = io.StringIO()
        with self.assertRaises(apify.ApifyError) as ctx:
            with unittest.mock.patch("sys.stderr", buf):
                self._run_with(responses)
        self.assertNotIn("secret-token", str(ctx.exception))
        self.assertNotIn("secret-token", buf.getvalue())


class TestFetchLinkedinCeiling(unittest.TestCase):
    def test_ceiling_aborts_and_raises(self):
        responses = [
            _json_response({"data": {"id": "run1", "status": "RUNNING", "defaultDatasetId": "d"}}, status=201),
            _json_response({"data": {"id": "run1", "status": "ok"}}),  # abort POST response
        ]
        fake = _FakeUrlopen(responses)
        fake_clock = iter([0, 1000])  # second call exceeds _CEILING_SECONDS
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "items.json")
            with unittest.mock.patch("urllib.request.urlopen", fake):
                with self.assertRaises(apify.ApifyError) as ctx:
                    apify.fetch_linkedin(
                        {"titles": ["x"]}, 5, "tok", dest, clock=lambda: next(fake_clock)
                    )
        self.assertIn("aborted after 900 s", str(ctx.exception))
        self.assertEqual(len(fake.requests), 2)
        self.assertEqual(fake.requests[1].get_method(), "POST")
        self.assertIn("/abort", fake.requests[1].full_url)


class TestRemainingCreditUsd(unittest.TestCase):
    def test_arithmetic(self):
        payload = {"data": {"limits": {"maxMonthlyUsageUsd": 50}, "current": {"monthlyUsageUsd": 12.5}}}
        fake = _FakeUrlopen([_json_response(payload)])
        with unittest.mock.patch("urllib.request.urlopen", fake):
            remaining = apify.remaining_credit_usd("tok")
        self.assertEqual(remaining, 37.5)


class TestChooseWindow(unittest.TestCase):
    def test_no_file_returns_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            now = datetime.datetime(2026, 9, 22, tzinfo=datetime.timezone.utc)
            self.assertEqual(apify.choose_window(path, now), "r2592000")

    def test_3_hours_ago_returns_24h_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            now = datetime.datetime(2026, 9, 22, 12, 0, tzinfo=datetime.timezone.utc)
            last = now - datetime.timedelta(hours=3)
            apify.write_state(path, last)
            self.assertEqual(apify.choose_window(path, now), "r86400")

    def test_30_hours_ago_returns_7day_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            now = datetime.datetime(2026, 9, 22, 12, 0, tzinfo=datetime.timezone.utc)
            last = now - datetime.timedelta(hours=30)
            apify.write_state(path, last)
            self.assertEqual(apify.choose_window(path, now), "r604800")

    def test_8_days_ago_returns_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            now = datetime.datetime(2026, 9, 22, 12, 0, tzinfo=datetime.timezone.utc)
            last = now - datetime.timedelta(days=8)
            apify.write_state(path, last)
            self.assertEqual(apify.choose_window(path, now), "r2592000")

    def test_garbage_file_returns_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("not json{{{")
            now = datetime.datetime(2026, 9, 22, tzinfo=datetime.timezone.utc)
            self.assertEqual(apify.choose_window(path, now), "r2592000")


class TestWriteStateRoundTrip(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            now = datetime.datetime(2026, 9, 22, 12, 0, tzinfo=datetime.timezone.utc)
            apify.write_state(path, now)
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["last_success_at"], now.isoformat())


if __name__ == "__main__":
    unittest.main()

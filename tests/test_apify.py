import json
import os
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()

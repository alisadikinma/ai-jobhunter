import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
APIFY_LINKEDIN_FIXTURE = os.path.join(FIXTURES, "apify_linkedin.json")
FIRECRAWL_SEARCH_FIXTURE = os.path.join(FIXTURES, "firecrawl_search.json")


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


if __name__ == "__main__":
    unittest.main()

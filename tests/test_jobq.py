import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import jobq  # noqa: E402


class TestAppendRows(unittest.TestCase):
    def test_append_rows_writes_one_jsonl_line_per_row(self):
        rows = [
            {"company": "Acme", "jobTitle": "Engineer", "location": "Remote"},
            {"company": "Beta", "jobTitle": "Designer", "location": "NYC"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "jobs.jsonl")
            written, skipped, malformed = jobq.append_rows(path, rows)

            self.assertEqual(written, 2)
            self.assertEqual(skipped, 0)
            self.assertEqual(malformed, 0)

            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["company"], "Acme")
            self.assertEqual(json.loads(lines[1])["company"], "Beta")

    def test_load_empty_file_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "jobs.jsonl")
            with open(path, "w", encoding="utf-8"):
                pass
            self.assertEqual(jobq.load(path), [])

    def test_load_missing_file_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "does-not-exist.jsonl")
            self.assertEqual(jobq.load(path), [])

    def test_row_key_without_job_url_uses_company_title_location(self):
        row = {"company": "Acme", "jobTitle": "Engineer", "location": "Remote"}
        key = jobq.row_key(row)
        self.assertEqual(len(key), 64)  # sha256 hex digest length
        # Same identity fields, different casing/whitespace -> same key.
        row2 = {"company": "  ACME ", "jobTitle": "engineer", "location": "remote"}
        self.assertEqual(key, jobq.row_key(row2))

    def test_urls_differing_only_by_query_string_produce_same_key(self):
        row_a = {"jobUrl": "https://boards.example.com/jobs/123?utm_source=li"}
        row_b = {"jobUrl": "https://boards.example.com/jobs/123?utm_source=fb&ref=x"}
        row_c = {"jobUrl": "https://boards.example.com/jobs/123"}
        self.assertEqual(jobq.row_key(row_a), jobq.row_key(row_b))
        self.assertEqual(jobq.row_key(row_a), jobq.row_key(row_c))

    def test_identifying_query_param_keeps_postings_distinct(self):
        """Greenhouse puts the job id in the query, so it must never be stripped.

        Regression: dropping the whole query string collapsed all 667 postings
        on one measured Stripe board into a single key.
        """
        row_a = {"jobUrl": "https://stripe.com/jobs/search?gh_jid=8172487"}
        row_b = {"jobUrl": "https://stripe.com/jobs/search?gh_jid=8172510"}
        self.assertNotEqual(jobq.row_key(row_a), jobq.row_key(row_b))

    def test_identifying_param_survives_alongside_tracking_param(self):
        row_a = {"jobUrl": "https://stripe.com/jobs/search?gh_jid=8172487"}
        row_b = {
            "jobUrl": "https://stripe.com/jobs/search"
            "?gh_jid=8172487&utm_source=linkedin&ref=newsletter"
        }
        self.assertEqual(jobq.row_key(row_a), jobq.row_key(row_b))

    def test_query_param_order_does_not_change_key(self):
        row_a = {"jobUrl": "https://jobs.example.com/p?a=1&b=2"}
        row_b = {"jobUrl": "https://jobs.example.com/p?b=2&a=1"}
        self.assertEqual(jobq.row_key(row_a), jobq.row_key(row_b))

    def test_duplicate_appended_twice_is_skipped(self):
        row = {"jobUrl": "https://boards.example.com/jobs/456"}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "jobs.jsonl")
            written1, skipped1, _ = jobq.append_rows(path, [row])
            self.assertEqual(written1, 1)
            self.assertEqual(skipped1, 0)

            written2, skipped2, _ = jobq.append_rows(path, [row])
            self.assertEqual(written2, 0)
            self.assertEqual(skipped2, 1)

            rows = jobq.load(path)
            self.assertEqual(len(rows), 1)

    def test_malformed_line_is_counted_and_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "jobs.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"company": "Acme", "jobTitle": "Eng", "location": "Remote"}))
                f.write("\n")
                f.write("{this is not valid json\n")
                f.write(json.dumps({"company": "Beta", "jobTitle": "PM", "location": "NYC"}))
                f.write("\n")

            rows = jobq.load(path)
            self.assertEqual(len(rows), 2)

            new_row = {"company": "Gamma", "jobTitle": "SRE", "location": "SF"}
            written, skipped, malformed = jobq.append_rows(path, [new_row])
            self.assertEqual(written, 1)
            self.assertEqual(skipped, 0)
            self.assertEqual(malformed, 1)

    def test_1000_rows_all_written_and_read_back(self):
        rows = [
            {"company": f"Company{i}", "jobTitle": "Engineer", "location": "Remote"}
            for i in range(1000)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "jobs.jsonl")
            written, skipped, malformed = jobq.append_rows(path, rows)
            self.assertEqual(written, 1000)
            self.assertEqual(skipped, 0)
            self.assertEqual(malformed, 0)

            loaded = jobq.load(path)
            self.assertEqual(len(loaded), 1000)

    def test_company_trailing_whitespace_dedupes_with_clean_company(self):
        row_a = {"company": "Acme Inc", "jobTitle": "Engineer", "location": "Remote"}
        row_b = {"company": "Acme Inc   ", "jobTitle": "Engineer", "location": "Remote"}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "jobs.jsonl")
            written1, skipped1, _ = jobq.append_rows(path, [row_a])
            self.assertEqual(written1, 1)
            written2, skipped2, _ = jobq.append_rows(path, [row_b])
            self.assertEqual(written2, 0)
            self.assertEqual(skipped2, 1)

    def test_row_with_no_job_url_falls_back_to_identity_key(self):
        row = {"company": "Acme", "jobTitle": "Engineer", "location": "Remote"}
        key = jobq.row_key(row)
        expected_basis = "acme|engineer|remote"
        import hashlib

        self.assertEqual(key, hashlib.sha256(expected_basis.encode("utf-8")).hexdigest())


class TestIterUnscored(unittest.TestCase):
    def test_iter_unscored_yields_rows_without_fit_score(self):
        rows = [
            {"company": "Acme", "fit_score": 80},
            {"company": "Beta"},
            {"company": "Gamma", "fit_score": None},
        ]
        unscored = list(jobq.iter_unscored(rows))
        self.assertEqual(len(unscored), 2)
        self.assertEqual({r["company"] for r in unscored}, {"Beta", "Gamma"})


if __name__ == "__main__":
    unittest.main()


class TestUpdateRows(unittest.TestCase):
    """The queue is append-only for new postings, but a row changes twice:
    `score` writes the score onto it, `promote` marks it promoted.
    """

    def _seed(self, tmp):
        path = os.path.join(tmp, "jobs.jsonl")
        jobq.append_rows(path, [
            {"company": "Acme", "jobTitle": "AI Engineer", "jobUrl": "https://a.example/1"},
            {"company": "Beta", "jobTitle": "ML Engineer", "jobUrl": "https://a.example/2"},
        ])
        return path

    def test_merges_fields_into_the_matching_row_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._seed(tmp)
            target = jobq.row_key({"jobUrl": "https://a.example/1"})
            updated, unmatched = jobq.update_rows(path, {target: {"fit_score": 88}})
            self.assertEqual((updated, unmatched), (1, []))
            rows = jobq.load(path)
            self.assertEqual(rows[0]["fit_score"], 88)
            self.assertNotIn("fit_score", rows[1])

    def test_updated_row_is_not_dropped_as_a_duplicate(self):
        """The bug `append_rows` would have caused if used for this."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._seed(tmp)
            target = jobq.row_key({"jobUrl": "https://a.example/1"})
            jobq.update_rows(path, {target: {"promoted": True}})
            self.assertEqual(len(jobq.load(path)), 2)

    def test_row_order_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._seed(tmp)
            target = jobq.row_key({"jobUrl": "https://a.example/2"})
            jobq.update_rows(path, {target: {"fit_score": 50}})
            self.assertEqual([r["company"] for r in jobq.load(path)], ["Acme", "Beta"])

    def test_unmatched_key_is_reported_not_swallowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._seed(tmp)
            updated, unmatched = jobq.update_rows(path, {"nosuchkey": {"fit_score": 1}})
            self.assertEqual(updated, 0)
            self.assertEqual(unmatched, ["nosuchkey"])

    def test_empty_updates_rewrites_the_queue_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._seed(tmp)
            before = jobq.load(path)
            self.assertEqual(jobq.update_rows(path, {}), (0, []))
            self.assertEqual(jobq.load(path), before)

    def test_missing_queue_file_is_created_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "absent.jsonl")
            self.assertEqual(jobq.update_rows(path, {}), (0, []))
            self.assertEqual(jobq.load(path), [])

    def test_no_temporary_file_is_left_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._seed(tmp)
            jobq.update_rows(path, {})
            leftovers = [n for n in os.listdir(tmp) if n.endswith(".tmp")]
            self.assertEqual(leftovers, [])

    def test_file_permissions_survive_the_rewrite(self):
        """`mkstemp` creates at 0600 and `os.replace` carries the mode over,
        so without preserving it the rewrite silently narrows the file.
        """
        import stat

        with tempfile.TemporaryDirectory() as tmp:
            path = self._seed(tmp)
            os.chmod(path, 0o644)
            jobq.update_rows(path, {})
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o644)


import json
import os
import sys
import tempfile
import unittest
import unittest.mock
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import ats  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
GREENHOUSE_FIXTURE = os.path.join(FIXTURES, "greenhouse_acme.json")
LEVER_FIXTURE = os.path.join(FIXTURES, "lever_acme.json")
ASHBY_FIXTURE = os.path.join(FIXTURES, "ashby_acme.json")


def _write_json(tmp_dir, name, data):
    path = os.path.join(tmp_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


class FakeResponse:
    """Minimal stand-in for the object `urllib.request.urlopen` returns.

    Supports the context-manager protocol and chunked `.read(size)`, since
    `ats.fetch` streams the body instead of reading it all at once.
    """

    def __init__(self, body_bytes, status=200):
        self.status = status
        self._body = body_bytes

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, size=-1):
        if size is None or size < 0:
            chunk, self._body = self._body, b""
            return chunk
        chunk, self._body = self._body[:size], self._body[size:]
        return chunk


class TestNormalizeGreenhouse(unittest.TestCase):
    def test_normalizes_real_fixture_rows(self):
        rows = ats.normalize_greenhouse(GREENHOUSE_FIXTURE)
        self.assertEqual(len(rows), 3)
        row = next(r for r in rows if r["jobTitle"] == "Abuse Investigator")
        self.assertEqual(row["company"], "Stripe")
        self.assertEqual(row["source"], "Greenhouse")
        self.assertEqual(row["jobUrl"], "https://stripe.com/jobs/search?gh_jid=8172487")
        self.assertEqual(row["location"], "Dublin")
        # A place name states where an office is, not how the role is worked.
        # Greenhouse never states an arrangement, so the field stays absent.
        self.assertNotIn("workplaceType", row)
        self.assertGreaterEqual(len(row["jobDescription"]), 10)
        self.assertNotIn("<", row["jobDescription"])
        self.assertNotIn("&lt;", row["jobDescription"])
        self.assertNotIn("&nbsp;", row["jobDescription"])

    def test_empty_job_list_returns_empty_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(tmp, "empty.json", {"jobs": []})
            self.assertEqual(ats.normalize_greenhouse(path), [])

    def test_posting_with_no_location_omits_location_and_workplace_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(
                tmp,
                "no_location.json",
                {
                    "jobs": [
                        {
                            "title": "Remote-First Role",
                            "company_name": "Acme",
                            "absolute_url": "https://acme.example/jobs/1",
                            "content": "A real job description with enough length.",
                            "location": {"name": ""},
                        }
                    ]
                },
            )
            rows = ats.normalize_greenhouse(path)
            self.assertNotIn("location", rows[0])
            self.assertNotIn("workplaceType", rows[0])

    def test_html_only_description_strips_to_na(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(
                tmp,
                "html_only.json",
                {
                    "jobs": [
                        {
                            "title": "Tag Soup Role",
                            "company_name": "Acme",
                            "absolute_url": "https://acme.example/jobs/2",
                            # Real Greenhouse boards double-escape HTML (verified
                            # on the live Stripe board: "&amp;nbsp;" unescapes
                            # once to "&nbsp;"), so this mirrors that shape for
                            # a posting whose content is pure markup/whitespace.
                            "content": "&lt;p&gt;&amp;nbsp;&lt;/p&gt;",
                            "location": {"name": "Remote"},
                        }
                    ]
                },
            )
            rows = ats.normalize_greenhouse(path)
            self.assertEqual(rows[0]["jobDescription"], "N/A")

    def test_description_under_10_chars_becomes_na(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(
                tmp,
                "short_desc.json",
                {
                    "jobs": [
                        {
                            "title": "Short Desc Role",
                            "company_name": "Acme",
                            "absolute_url": "https://acme.example/jobs/3",
                            "content": "Tiny",
                            "location": {"name": "Paris"},
                        }
                    ]
                },
            )
            rows = ats.normalize_greenhouse(path)
            self.assertEqual(rows[0]["jobDescription"], "N/A")

    def test_location_that_maps_to_no_workplace_type_leaves_field_absent(self):
        """Real fixture case: location.name is "N/A" (Stripe posting 7217048).

        Must not guess Onsite/Remote/Hybrid — the field must be entirely
        absent from the row, because a wrong guess can't be corrected later.
        """
        rows = ats.normalize_greenhouse(GREENHOUSE_FIXTURE)
        row = next(r for r in rows if r["jobTitle"] == "Backend Engineer, Billing/Tax")
        self.assertEqual(row["location"], "N/A")
        self.assertNotIn("workplaceType", row)

    def test_multi_option_location_still_reads_its_arrangement_word(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(
                tmp,
                "ambiguous.json",
                {
                    "jobs": [
                        {
                            "title": "Multi City Role",
                            "company_name": "Acme",
                            "absolute_url": "https://acme.example/jobs/4",
                            "content": "A real job description with enough length.",
                            "location": {"name": "NYC or Remote"},
                        }
                    ]
                },
            )
            rows = ats.normalize_greenhouse(path)
            self.assertEqual(rows[0]["location"], "NYC or Remote")
            # The text names an arrangement, so it is read, comma or not.
            # An earlier rule vetoed any location containing a separator and
            # so discarded 76 of the 107 genuinely remote postings on a live
            # 667-job board.
            self.assertEqual(rows[0]["workplaceType"], "Remote")

    def test_bare_place_name_leaves_workplace_type_absent(self):
        """No arrangement word means no field — never an invented Onsite.

        Measured on a live 667-job Greenhouse board: 560 locations were a
        place name alone, and not one of them said "hybrid" or "onsite".
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(
                tmp,
                "places.json",
                {
                    "jobs": [
                        {
                            "title": "Engineer",
                            "company_name": "Acme",
                            "absolute_url": "https://acme.example/jobs/9",
                            "content": "A real job description with enough length.",
                            "location": {"name": name},
                        }
                        for name in ("Dublin", "New York", "Singapore", "Dublin or Berlin")
                    ]
                },
            )
            for row in ats.normalize_greenhouse(path):
                self.assertNotIn("workplaceType", row, row["location"])

    def test_onsite_is_read_only_when_the_text_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(
                tmp,
                "onsite.json",
                {
                    "jobs": [
                        {
                            "title": "Technician",
                            "company_name": "Acme",
                            "absolute_url": "https://acme.example/jobs/10",
                            "content": "A real job description with enough length.",
                            "location": {"name": "Austin, TX (on-site)"},
                        }
                    ]
                },
            )
            self.assertEqual(
                ats.normalize_greenhouse(path)[0]["workplaceType"], "Onsite"
            )

    def test_unambiguous_remote_location_infers_remote(self):
        rows = ats.normalize_greenhouse(GREENHOUSE_FIXTURE)
        row = next(r for r in rows if r["location"] == "US-Remote")
        self.assertEqual(row["workplaceType"], "Remote")

    def test_missing_company_name_key_names_key_and_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(
                tmp,
                "missing_company.json",
                {
                    "jobs": [
                        {
                            "title": "No Company Role",
                            "absolute_url": "https://acme.example/jobs/5",
                            "content": "A real job description with enough length.",
                        }
                    ]
                },
            )
            with self.assertRaises(ats.MissingFieldError) as ctx:
                ats.normalize_greenhouse(path)
            self.assertEqual(ctx.exception.provider, "Greenhouse")
            self.assertEqual(ctx.exception.key, "company_name")
            self.assertIn("company_name", str(ctx.exception))

    def test_missing_jobs_container_names_key_and_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(tmp, "no_jobs_key.json", {"unexpected": []})
            with self.assertRaises(ats.MissingFieldError) as ctx:
                ats.normalize_greenhouse(path)
            self.assertEqual(ctx.exception.key, "jobs")


class TestNormalizeLever(unittest.TestCase):
    def test_normalizes_real_fixture_rows(self):
        rows = ats.normalize_lever(LEVER_FIXTURE, "Lever Demo Co")
        self.assertEqual(len(rows), 3)
        row = next(r for r in rows if r["jobTitle"] == "Approved Professional 3")
        self.assertEqual(row["company"], "Lever Demo Co")
        self.assertEqual(row["source"], "Lever")
        self.assertEqual(
            row["jobUrl"],
            "https://jobs.lever.co/leverdemo/681fbc53-1e34-4a46-8677-3a78118674eb",
        )
        self.assertEqual(row["location"], "Baltimore, MD")
        self.assertEqual(row["workplaceType"], "Remote")

    def test_requires_company_argument(self):
        with self.assertRaises(ats.MissingFieldError) as ctx:
            ats.normalize_lever(LEVER_FIXTURE, "")
        self.assertEqual(ctx.exception.provider, "Lever")
        self.assertEqual(ctx.exception.key, "company")

    def test_real_empty_description_posting_becomes_na(self):
        """Real fixture case: the "Dentist" posting's descriptionPlain is "" on
        the live leverdemo board.
        """
        rows = ats.normalize_lever(LEVER_FIXTURE, "Lever Demo Co")
        row = next(r for r in rows if r["jobTitle"] == "Dentist")
        self.assertEqual(row["jobDescription"], "N/A")

    def test_unmapped_workplace_type_leaves_field_absent(self):
        """Real fixture case: "Stephanie Test Posting A" has workplaceType
        "unspecified" on the live board, which is not one of Remote/Hybrid/
        Onsite, so the field must be left out rather than guessed.
        """
        rows = ats.normalize_lever(LEVER_FIXTURE, "Lever Demo Co")
        row = next(r for r in rows if r["jobTitle"] == "Stephanie Test Posting A")
        self.assertNotIn("workplaceType", row)

    def test_missing_hosted_url_key_names_key_and_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(
                tmp,
                "no_hosted_url.json",
                [{"text": "Some Role", "descriptionPlain": "A real description."}],
            )
            with self.assertRaises(ats.MissingFieldError) as ctx:
                ats.normalize_lever(path, "Acme")
            self.assertEqual(ctx.exception.provider, "Lever")
            self.assertEqual(ctx.exception.key, "hostedUrl")

    def test_non_array_payload_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(tmp, "not_array.json", {"ok": False, "error": "nope"})
            with self.assertRaises(ats.AtsError):
                ats.normalize_lever(path, "Acme")


class TestNormalizeAshby(unittest.TestCase):
    def test_normalizes_real_fixture_rows(self):
        rows = ats.normalize_ashby(ASHBY_FIXTURE, "Ramp")
        self.assertEqual(len(rows), 3)
        row = next(r for r in rows if r["jobTitle"].strip() == "Security Engineer, Cloud")
        self.assertEqual(row["company"], "Ramp")
        self.assertEqual(row["source"], "Ashby")
        self.assertEqual(row["workplaceType"], "Hybrid")
        self.assertEqual(row["jobType"], "Full-time")
        self.assertEqual(row["location"], "New York, NY (HQ)")

    def test_requires_company_argument(self):
        with self.assertRaises(ats.MissingFieldError) as ctx:
            ats.normalize_ashby(ASHBY_FIXTURE, "")
        self.assertEqual(ctx.exception.provider, "Ashby")
        self.assertEqual(ctx.exception.key, "company")

    def test_unlisted_row_is_dropped(self):
        """Ashby's own schema carries `isListed`; a false value means the
        posting is not public and must not be promoted. No real posting on
        the trimmed `ramp` board happens to be unlisted, so this uses a copy
        of a real row's exact field shape with only `isListed` flipped.
        """
        with tempfile.TemporaryDirectory() as tmp:
            with open(ASHBY_FIXTURE, "r", encoding="utf-8") as f:
                real = json.load(f)
            unlisted_job = dict(real["jobs"][0])
            unlisted_job["isListed"] = False
            path = _write_json(tmp, "unlisted.json", {"jobs": [unlisted_job]})
            rows = ats.normalize_ashby(path, "Ramp")
            self.assertEqual(rows, [])

    def test_missing_is_listed_key_names_key_and_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(
                tmp,
                "no_is_listed.json",
                {
                    "jobs": [
                        {
                            "title": "No isListed Role",
                            "jobUrl": "https://jobs.ashbyhq.com/acme/1",
                            "descriptionPlain": "A real job description with enough length.",
                        }
                    ]
                },
            )
            with self.assertRaises(ats.MissingFieldError) as ctx:
                ats.normalize_ashby(path, "Acme")
            self.assertEqual(ctx.exception.key, "isListed")

    def test_missing_job_url_key_names_key_and_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(
                tmp,
                "no_job_url.json",
                {
                    "jobs": [
                        {
                            "title": "No URL Role",
                            "isListed": True,
                            "descriptionPlain": "A real job description with enough length.",
                        }
                    ]
                },
            )
            with self.assertRaises(ats.MissingFieldError) as ctx:
                ats.normalize_ashby(path, "Acme")
            self.assertEqual(ctx.exception.provider, "Ashby")
            self.assertEqual(ctx.exception.key, "jobUrl")

    def test_unmappable_employment_type_leaves_job_type_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(
                tmp,
                "temp_employment.json",
                {
                    "jobs": [
                        {
                            "title": "Seasonal Role",
                            "jobUrl": "https://jobs.ashbyhq.com/acme/2",
                            "descriptionPlain": "A real job description with enough length.",
                            "isListed": True,
                            "employmentType": "Temporary",
                        }
                    ]
                },
            )
            rows = ats.normalize_ashby(path, "Acme")
            self.assertNotIn("jobType", rows[0])


class TestFetch(unittest.TestCase):
    def test_streams_greenhouse_body_to_dest_and_logs_status_and_row_count(self):
        body = json.dumps({"jobs": [{"id": 1}, {"id": 2}]}).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "gh.json")
            with unittest.mock.patch(
                "urllib.request.urlopen", return_value=FakeResponse(body, status=200)
            ) as mock_urlopen:
                status, row_count = ats.fetch("greenhouse", "acme", dest)
            mock_urlopen.assert_called_once()
            self.assertEqual(status, 200)
            self.assertEqual(row_count, 2)
            with open(dest, "rb") as f:
                self.assertEqual(json.load(f), {"jobs": [{"id": 1}, {"id": 2}]})

    def test_streams_lever_array_body_and_counts_rows(self):
        body = json.dumps([{"id": "a"}, {"id": "b"}, {"id": "c"}]).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "lv.json")
            with unittest.mock.patch(
                "urllib.request.urlopen", return_value=FakeResponse(body, status=200)
            ):
                status, row_count = ats.fetch("lever", "leverdemo", dest)
            self.assertEqual(status, 200)
            self.assertEqual(row_count, 3)

    def test_non_json_response_body_raises_ats_error(self):
        body = b"<html><body>not json</body></html>"
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "bad.json")
            with unittest.mock.patch(
                "urllib.request.urlopen", return_value=FakeResponse(body, status=200)
            ):
                with self.assertRaises(ats.AtsError) as ctx:
                    ats.fetch("greenhouse", "acme", dest)
            self.assertIn("non-JSON", str(ctx.exception))

    def test_http_404_carrying_lever_style_error_body_raises_ats_error(self):
        error_body = json.dumps({"ok": False, "error": "Document not found"}).encode("utf-8")
        http_error = urllib.error.HTTPError(
            url="https://api.lever.co/v0/postings/nonexistent?mode=json",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=__import__("io").BytesIO(error_body),
        )
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "lv.json")
            with unittest.mock.patch("urllib.request.urlopen", side_effect=http_error):
                with self.assertRaises(ats.AtsError) as ctx:
                    ats.fetch("lever", "nonexistent", dest)
            self.assertIn("404", str(ctx.exception))
            self.assertIn("Document not found", str(ctx.exception))

    def test_timeout_raises_ats_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "gh.json")
            with unittest.mock.patch(
                "urllib.request.urlopen", side_effect=TimeoutError("timed out")
            ):
                with self.assertRaises(ats.AtsError) as ctx:
                    ats.fetch("greenhouse", "acme", dest)
            self.assertIn("timed out", str(ctx.exception))

    def test_unknown_board_raises_before_any_network_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.json")
            with unittest.mock.patch("urllib.request.urlopen") as mock_urlopen:
                with self.assertRaises(ats.AtsError):
                    ats.fetch("indeed", "acme", dest)
            mock_urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()

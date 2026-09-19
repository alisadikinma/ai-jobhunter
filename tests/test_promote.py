import ast
import os
import re
import sys
import pathlib
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import promote  # noqa: E402

PROMOTE_SOURCE_PATH = os.path.join(os.path.dirname(__file__), "..", "scripts", "promote.py")

SCORES_LINE_RE = re.compile(
    r"^SCORES: match=\d{1,3} recommendation=(strong|good|partial|weak)$"
)

# A real row, produced by `ats.normalize_ashby` from the committed Ashby fixture (see
# tests/fixtures/ashby_acme.json) via the exact command in the plan:
#   python3 -c "import sys;sys.path.insert(0,'scripts');import ats,json;
#   print(json.dumps(ats.normalize_ashby('/tmp/ab.json','Ramp')[0],indent=2))"
# run here against the committed fixture instead of a re-fetched /tmp file. `fit_score`,
# `work_authorization`, `suggested_variant` and `skills` are not produced by `ats.py` — they
# are the scoring step's output (spec §5) — and are added here exactly as `/ai-jobhunter:score`
# would write them back onto this same row.
REAL_ASHBY_ROW = {
    "company": "Ramp",
    "jobTitle": " Security Engineer, Cloud",
    "jobDescription": (
        "ABOUT RAMP Ramp is building the smart infrastructure for finance teams, "
        "embedded in the transaction flow of every dollar a business spends. We "
        "automate how over $200B in annualized spend flows in and out of 70,000+ "
        "companies: authorizing payments, flagging risk, categorizing spend, and "
        "closing books. WHAT YOU NEED - Minimum 5 years of experience building "
        "software - Minimum 3 years of experience building in AWS (with Terraform)"
    ),
    "source": "Ashby",
    "jobUrl": "https://jobs.ashbyhq.com/ramp/34413f8d-26bf-4bbc-8ade-eb309a0e2245",
    "location": "New York, NY (HQ)",
    "workplaceType": "Hybrid",
    "jobType": "Full-time",
    "fit_score": 72,
    "work_authorization": "unclear",
    "suggested_variant": "ai_product_lead",
    "skills": ["aws", "terraform", "python", "cloud security"],
}


def _scored_row(**overrides):
    row = {
        "company": "Acme",
        "jobTitle": "Staff Engineer",
        "jobDescription": "A real job description with enough length to pass validation.",
        "jobUrl": "https://acme.example/jobs/1",
        "source": "Greenhouse",
        "fit_score": 85,
        "work_authorization": "open",
        "suggested_variant": "ai_product_lead",
        "skills": ["python", "distributed systems"],
    }
    row.update(overrides)
    return row


class TestToAddJobUpsertAndWorkplaceType(unittest.TestCase):
    def test_always_sets_upsert_true(self):
        payload = promote.to_add_job(_scored_row())
        self.assertIs(payload["upsert"], True)

    def test_canonicalises_workplace_type_on_site(self):
        payload = promote.to_add_job(_scored_row(workplaceType="On-site"))
        self.assertEqual(payload["workplaceType"], "Onsite")

    def test_canonicalises_workplace_type_remote_upper(self):
        payload = promote.to_add_job(_scored_row(workplaceType="REMOTE"))
        self.assertEqual(payload["workplaceType"], "Remote")

    def test_canonicalises_workplace_type_hybrid_lower_with_spaces(self):
        payload = promote.to_add_job(_scored_row(workplaceType="  hybrid  "))
        self.assertEqual(payload["workplaceType"], "Hybrid")

    def test_missing_workplace_type_is_absent_not_guessed(self):
        row = _scored_row()
        self.assertNotIn("workplaceType", row)
        payload = promote.to_add_job(row)
        self.assertNotIn("workplaceType", payload)

    def test_unmappable_workplace_type_raises(self):
        with self.assertRaises(promote.WorkplaceTypeError):
            promote.to_add_job(_scored_row(workplaceType="Remote-ish someday maybe"))

    def test_never_emits_field_the_contract_does_not_define(self):
        row = _scored_row(fit_score=85, invented_field="should never appear")
        payload = promote.to_add_job(row)
        self.assertNotIn("invented_field", payload)
        self.assertNotIn("fit_score", payload)
        self.assertNotIn("work_authorization", payload)
        self.assertNotIn("suggested_variant", payload)
        self.assertNotIn("skills", payload)
        self.assertNotIn("allowDuplicate", payload)


class TestJobDescriptionFallback(unittest.TestCase):
    """Text too short to match is refused, not stored as "N/A".

    Spec section 8 refuses a title-only row. `ats.normalize_*` still writes
    "N/A" into the queue for such a posting, so the row exists and can be
    re-fetched later; what must not happen is spending two jobsync requests
    on a job that can never carry a score.
    """

    def test_missing_description_is_refused(self):
        row = _scored_row()
        del row["jobDescription"]
        with self.assertRaises(promote.TitleOnlyError):
            promote.to_add_job(row)

    def test_description_of_exactly_9_chars_is_refused(self):
        self.assertEqual(len("123456789"), 9)
        with self.assertRaises(promote.TitleOnlyError):
            promote.to_add_job(_scored_row(jobDescription="123456789"))

    def test_description_of_exactly_10_chars_is_kept_verbatim(self):
        ten_chars = "1234567890"
        self.assertEqual(len(ten_chars), 10)
        payload = promote.to_add_job(_scored_row(jobDescription=ten_chars))
        self.assertEqual(payload["jobDescription"], ten_chars)

    def test_empty_string_description_is_refused(self):
        with self.assertRaises(promote.TitleOnlyError):
            promote.to_add_job(_scored_row(jobDescription=""))

    def test_a_literal_na_from_the_normalizer_is_refused(self):
        with self.assertRaises(promote.TitleOnlyError):
            promote.to_add_job(_scored_row(jobDescription="N/A"))


class TestRecommendationBoundaries(unittest.TestCase):
    def test_score_100_is_strong(self):
        self.assertEqual(self._recommendation(100), "strong")

    def test_score_80_is_strong(self):
        self.assertEqual(self._recommendation(80), "strong")

    def test_score_79_is_good(self):
        self.assertEqual(self._recommendation(79), "good")

    def test_score_65_is_good(self):
        self.assertEqual(self._recommendation(65), "good")

    def test_score_64_is_partial(self):
        self.assertEqual(self._recommendation(64), "partial")

    def test_score_50_is_partial(self):
        self.assertEqual(self._recommendation(50), "partial")

    def test_score_49_is_weak(self):
        self.assertEqual(self._recommendation(49), "weak")

    def test_score_0_is_weak(self):
        self.assertEqual(self._recommendation(0), "weak")

    @staticmethod
    def _recommendation(fit_score):
        row = _scored_row(fit_score=fit_score)
        match_text = promote.to_match_text(row)
        first_line = match_text.splitlines()[0]
        m = SCORES_LINE_RE.match(first_line)
        assert m, f"first line {first_line!r} did not match SCORES regex"
        return m.group(1)


class TestMatchTextShape(unittest.TestCase):
    def test_every_boundary_first_line_matches_regex(self):
        for fit_score in (0, 49, 50, 64, 65, 79, 80, 100):
            row = _scored_row(fit_score=fit_score)
            match_text = promote.to_match_text(row)
            first_line = match_text.splitlines()[0]
            self.assertRegex(first_line, SCORES_LINE_RE)

    def test_first_line_exact_format_for_known_score(self):
        match_text = promote.to_match_text(_scored_row(fit_score=85))
        self.assertEqual(
            match_text.splitlines()[0], "SCORES: match=85 recommendation=strong"
        )

    def test_body_names_work_authorization_bucket(self):
        match_text = promote.to_match_text(_scored_row(work_authorization="unclear"))
        self.assertIn("unclear", match_text)

    def test_body_is_at_least_20_chars_after_first_line(self):
        match_text = promote.to_match_text(_scored_row())
        _first_line, _blank, body = match_text.partition("\n\n")
        self.assertGreaterEqual(len(body), promote.MIN_MATCH_TEXT_BODY_LEN)

    def test_missing_work_authorization_defaults_to_unclear(self):
        row = _scored_row()
        del row["work_authorization"]
        match_text = promote.to_match_text(row)
        self.assertIn("unclear", match_text)

    def test_real_ashby_row_match_text_matches_regex(self):
        match_text = promote.to_match_text(REAL_ASHBY_ROW)
        first_line = match_text.splitlines()[0]
        self.assertRegex(first_line, SCORES_LINE_RE)
        self.assertIn("unclear", match_text)


class TestRefusals(unittest.TestCase):
    def test_row_with_no_score_is_refused_by_to_add_job(self):
        row = _scored_row()
        del row["fit_score"]
        with self.assertRaises(promote.ScoreMissingError):
            promote.to_add_job(row)

    def test_row_with_no_score_is_refused_by_to_match_text(self):
        row = _scored_row()
        del row["fit_score"]
        with self.assertRaises(promote.ScoreMissingError):
            promote.to_match_text(row)

    def test_row_with_no_score_is_refused_by_build_tags(self):
        row = _scored_row()
        del row["fit_score"]
        with self.assertRaises(promote.ScoreMissingError):
            promote.build_tags(row)

    def test_score_missing_error_names_the_reason(self):
        row = _scored_row()
        del row["fit_score"]
        with self.assertRaises(promote.ScoreMissingError) as ctx:
            promote.to_add_job(row)
        self.assertIn("fit_score", str(ctx.exception))

    def test_closed_work_authorization_is_refused_by_to_add_job(self):
        row = _scored_row(work_authorization="closed")
        with self.assertRaises(promote.AuthorizationClosedError):
            promote.to_add_job(row)

    def test_closed_work_authorization_is_refused_by_to_match_text(self):
        row = _scored_row(work_authorization="closed")
        with self.assertRaises(promote.AuthorizationClosedError):
            promote.to_match_text(row)

    def test_closed_work_authorization_error_names_the_reason(self):
        row = _scored_row(work_authorization="closed")
        with self.assertRaises(promote.AuthorizationClosedError) as ctx:
            promote.to_add_job(row)
        self.assertIn("closed", str(ctx.exception))


class TestBuildTagsCap(unittest.TestCase):
    def test_visa_and_variant_tags_always_present(self):
        tags = promote.build_tags(_scored_row(work_authorization="open"))
        self.assertIn("visa:open", tags)
        self.assertIn("variant:ai_product_lead", tags)

    def test_eleven_skill_tags_truncate_to_eight_and_keep_visa_and_variant(self):
        skills = [f"skill{i}" for i in range(11)]
        row = _scored_row(skills=skills)
        tags = promote.build_tags(row)
        self.assertLessEqual(len(tags), promote.MAX_TAGS)
        self.assertEqual(len(tags), 10)
        self.assertEqual(tags[0], "visa:open")
        self.assertEqual(tags[1], "variant:ai_product_lead")
        skill_tags = tags[2:]
        self.assertEqual(len(skill_tags), promote.MAX_SKILL_TAGS)
        self.assertEqual(skill_tags, [f"skill:skill{i}" for i in range(8)])

    def test_no_skills_still_produces_visa_and_variant_tags(self):
        row = _scored_row()
        del row["skills"]
        tags = promote.build_tags(row)
        self.assertEqual(tags, ["visa:open", "variant:ai_product_lead"])

    def test_missing_suggested_variant_defaults_to_unclassified(self):
        row = _scored_row()
        del row["suggested_variant"]
        tags = promote.build_tags(row)
        self.assertIn("variant:unclassified", tags)

    def test_tags_never_exceed_ten_even_with_many_more_skills(self):
        row = _scored_row(skills=[f"skill{i}" for i in range(50)])
        tags = promote.build_tags(row)
        self.assertLessEqual(len(tags), promote.MAX_TAGS)


class TestChunk(unittest.TestCase):
    def test_batch_of_exactly_ten_is_one_chunk(self):
        rows = list(range(10))
        chunks = promote.chunk(rows)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(chunks[0]), 10)

    def test_batch_of_eleven_is_two_chunks_of_ten_and_one(self):
        rows = list(range(11))
        chunks = promote.chunk(rows)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(chunks[0]), 10)
        self.assertEqual(len(chunks[1]), 1)
        for c in chunks:
            self.assertLessEqual(len(c), 10)

    def test_empty_rows_produce_no_chunks(self):
        self.assertEqual(promote.chunk([]), [])

    def test_requested_size_above_ten_is_clamped_to_ten(self):
        rows = list(range(25))
        chunks = promote.chunk(rows, size=25)
        for c in chunks:
            self.assertLessEqual(len(c), 10)


class TestPlanBudget(unittest.TestCase):
    def test_budget_of_zero_sends_nothing(self):
        rows = [_scored_row() for _ in range(5)]
        sending, waiting, requests_needed = promote.plan_budget(rows, 0)
        self.assertEqual(sending, 0)
        self.assertEqual(waiting, 5)
        self.assertEqual(requests_needed, 0)

    def test_budget_covers_all_rows_costs_two_requests_per_job(self):
        rows = [_scored_row() for _ in range(3)]
        sending, waiting, requests_needed = promote.plan_budget(rows, 60)
        self.assertEqual(sending, 3)
        self.assertEqual(waiting, 0)
        self.assertEqual(requests_needed, 6)

    def test_partial_budget_splits_sending_and_waiting(self):
        rows = [_scored_row() for _ in range(10)]
        # 10 requests -> 5 jobs fit (2 requests each)
        sending, waiting, requests_needed = promote.plan_budget(rows, 10)
        self.assertEqual(sending, 5)
        self.assertEqual(waiting, 5)
        self.assertEqual(requests_needed, 10)

    def test_odd_limit_rounds_down_to_whole_jobs(self):
        rows = [_scored_row() for _ in range(10)]
        # 9 requests -> only 4 whole jobs fit (8 requests); 1 request would be wasted
        sending, waiting, requests_needed = promote.plan_budget(rows, 9)
        self.assertEqual(sending, 4)
        self.assertEqual(waiting, 6)
        self.assertEqual(requests_needed, 8)

    def test_limit_above_hourly_ceiling_is_clamped_to_sixty(self):
        rows = [_scored_row() for _ in range(100)]
        sending, waiting, requests_needed = promote.plan_budget(rows, 1000)
        self.assertEqual(sending, 30)  # 60 // 2
        self.assertEqual(waiting, 70)
        self.assertEqual(requests_needed, 60)

    def test_empty_rows_with_positive_limit(self):
        sending, waiting, requests_needed = promote.plan_budget([], 60)
        self.assertEqual((sending, waiting, requests_needed), (0, 0, 0))


class TestNoNetworkImports(unittest.TestCase):
    def test_module_has_no_network_imports(self):
        with open(PROMOTE_SOURCE_PATH, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=PROMOTE_SOURCE_PATH)
        network_module_roots = {
            "urllib",
            "urllib2",
            "urllib3",
            "http",
            "httplib",
            "socket",
            "ssl",
            "requests",
            "httpx",
            "aiohttp",
            "ftplib",
            "smtplib",
            "asyncio",
        }
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        offending = imported & network_module_roots
        self.assertFalse(
            offending,
            f"promote.py must perform no network I/O; found imports: {offending}",
        )

    def test_source_never_mentions_urlopen(self):
        with open(PROMOTE_SOURCE_PATH, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("urlopen", source)


class TestRealAshbyRow(unittest.TestCase):
    """Built from a real row produced by `ats.normalize_ashby` against the committed Ashby
    fixture, augmented with the scoring fields `/ai-jobhunter:score` would have written."""

    def test_to_add_job_payload_shape(self):
        payload = promote.to_add_job(REAL_ASHBY_ROW)
        self.assertEqual(payload["company"], "Ramp")
        # Trimmed, like the description already was. The leading space is
        # real in Ashby's payload and travelled into jobsync untouched.
        self.assertEqual(payload["jobTitle"], "Security Engineer, Cloud")
        self.assertEqual(payload["workplaceType"], "Hybrid")
        self.assertIs(payload["upsert"], True)
        self.assertEqual(
            payload["jobUrl"],
            "https://jobs.ashbyhq.com/ramp/34413f8d-26bf-4bbc-8ade-eb309a0e2245",
        )
        self.assertGreaterEqual(len(payload["jobDescription"]), 10)
        self.assertNotIn("fit_score", payload)

    def test_build_tags_from_real_row(self):
        tags = promote.build_tags(REAL_ASHBY_ROW)
        self.assertEqual(tags[0], "visa:unclear")
        self.assertEqual(tags[1], "variant:ai_product_lead")
        self.assertIn("skill:aws", tags)
        self.assertIn("skill:cloud-security", tags)
        self.assertLessEqual(len(tags), 10)




class TestScoreReasonsContractName(unittest.TestCase):
    """Regression: `promote.py` once read `dimension_reasons`, a name nothing
    else in the repo used, so the per-dimension breakdown never reached
    jobsync. Spec section 5: a bare number nobody can audit is not useful.
    """

    def _row(self, **extra):
        row = {
            "company": "Acme",
            "jobTitle": "AI Engineer",
            "jobDescription": " ".join(["word"] * 200),
            "fit_score": 90,
            "work_authorization": "open",
            "suggested_variant": "genai_agents",
            "skills": ["python"],
        }
        row.update(extra)
        return row

    def test_score_reasons_reaches_match_text(self):
        text = promote.to_match_text(
            self._row(score_reasons={"skill": "36/40", "role": "22/25"})
        )
        self.assertIn("Score breakdown:", text)
        self.assertIn("36/40", text)
        self.assertIn("22/25", text)

    def test_the_old_field_name_is_gone_from_the_source(self):
        source = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "promote.py"
        self.assertNotIn("dimension_reasons", source.read_text())

    def test_absent_salary_key_simply_does_not_appear(self):
        """The salary rule is only visible if the breakdown travels at all."""
        text = promote.to_match_text(
            self._row(score_reasons={"skill": "36/40", "remote": "15/15"})
        )
        self.assertIn("Score breakdown:", text)
        self.assertNotIn("salary", text.lower())


class TestTitleOnlyRefusal(unittest.TestCase):
    """Spec section 8: refuse to promote a title-only row and say why."""

    def _row(self, **extra):
        row = {
            "company": "Acme",
            "jobTitle": "AI Engineer",
            "fit_score": 70,
            "work_authorization": "open",
            "suggested_variant": "genai_agents",
            "skills": [],
        }
        row.update(extra)
        return row

    def test_missing_description_is_refused_by_to_add_job(self):
        with self.assertRaises(promote.TitleOnlyError) as ctx:
            promote.to_add_job(self._row())
        self.assertIn("title-only", str(ctx.exception))
        self.assertIn("AI Engineer", str(ctx.exception))

    def test_description_under_ten_chars_is_refused(self):
        with self.assertRaises(promote.TitleOnlyError):
            promote.to_add_job(self._row(jobDescription="short"))

    def test_description_of_exactly_ten_chars_is_accepted(self):
        payload = promote.to_add_job(self._row(jobDescription="a" * 10))
        self.assertEqual(payload["jobDescription"], "a" * 10)

    def test_match_text_also_refuses_a_title_only_row(self):
        with self.assertRaises(promote.TitleOnlyError):
            promote.to_match_text(self._row())


class TestProvisionalMatchQuality(unittest.TestCase):
    """Spec section 8: a posting under ~150 words still promotes, but the
    user must be told the match will be flagged Provisional.
    """

    def _row(self, words):
        return {
            "company": "Acme",
            "jobTitle": "AI Engineer",
            "jobDescription": " ".join(["word"] * words),
            "fit_score": 55,
            "work_authorization": "unclear",
            "suggested_variant": "genai_agents",
            "skills": [],
        }

    def test_long_posting_is_full_quality_and_says_nothing(self):
        self.assertEqual(promote.match_quality(self._row(200)), "full")
        self.assertNotIn("Provisional", promote.to_match_text(self._row(200)))

    def test_short_posting_is_provisional_and_says_so(self):
        self.assertEqual(promote.match_quality(self._row(40)), "provisional")
        text = promote.to_match_text(self._row(40))
        self.assertIn("Provisional", text)
        self.assertIn("150", text)

    def test_exactly_the_threshold_counts_as_full(self):
        self.assertEqual(
            promote.match_quality(self._row(promote.FULL_MATCH_MIN_WORDS)), "full"
        )

    def test_one_word_under_the_threshold_is_provisional(self):
        self.assertEqual(
            promote.match_quality(self._row(promote.FULL_MATCH_MIN_WORDS - 1)),
            "provisional",
        )

    def test_a_provisional_row_is_still_promotable(self):
        payload = promote.to_add_job(self._row(40))
        self.assertTrue(payload["upsert"])


class TestScoreValidationIsSymmetric(unittest.TestCase):
    """`to_add_job` validated only `is None` while `to_match_text` checked the
    range, so a score of 105 reached jobsync through add_jobs_batch and only
    then threw — one request spent, a job in the tracker with no match, no
    rollback.
    """

    def _row(self, score):
        return {
            "company": "Acme",
            "jobTitle": "AI Engineer",
            "jobDescription": " ".join(["word"] * 200),
            "fit_score": score,
            "work_authorization": "open",
            "suggested_variant": "v",
            "skills": [],
        }

    def test_out_of_range_score_is_refused_by_to_add_job(self):
        with self.assertRaises(promote.PromoteError):
            promote.to_add_job(self._row(150))

    def test_non_integer_score_is_refused_by_to_add_job(self):
        with self.assertRaises(promote.PromoteError):
            promote.to_add_job(self._row("high"))

    def test_both_entry_points_refuse_the_same_row(self):
        for score in (150, -1, "high", True):
            with self.assertRaises(promote.PromoteError):
                promote.to_add_job(self._row(score))
            with self.assertRaises(promote.PromoteError):
                promote.to_match_text(self._row(score))


class TestRequiredTextFields(unittest.TestCase):
    def _row(self, **extra):
        row = {
            "company": "Acme",
            "jobTitle": "AI Engineer",
            "jobDescription": " ".join(["word"] * 200),
            "fit_score": 80,
            "work_authorization": "open",
            "suggested_variant": "v",
            "skills": [],
        }
        row.update(extra)
        return row

    def test_missing_company_raises_a_promote_error_not_keyerror(self):
        row = self._row()
        del row["company"]
        with self.assertRaises(promote.FieldMissingError):
            promote.to_add_job(row)

    def test_blank_job_title_is_refused(self):
        with self.assertRaises(promote.FieldMissingError):
            promote.to_add_job(self._row(jobTitle="   "))

    def test_company_and_title_are_trimmed(self):
        payload = promote.to_add_job(self._row(company="  Acme ", jobTitle=" Engineer "))
        self.assertEqual(payload["company"], "Acme")
        self.assertEqual(payload["jobTitle"], "Engineer")


class TestSkillTagDeduplication(unittest.TestCase):
    def test_case_variants_of_one_skill_take_one_slot(self):
        row = {
            "company": "Acme",
            "jobTitle": "AI Engineer",
            "jobDescription": " ".join(["word"] * 200),
            "fit_score": 80,
            "work_authorization": "open",
            "suggested_variant": "v",
            "skills": ["Python", "python", "PYTHON", "sql"],
        }
        tags = promote.build_tags(row)
        self.assertEqual(tags.count("skill:python"), 1)
        self.assertIn("skill:sql", tags)

    def test_eight_distinct_skills_still_fill_the_cap(self):
        row = {
            "company": "Acme",
            "jobTitle": "AI Engineer",
            "jobDescription": " ".join(["word"] * 200),
            "fit_score": 80,
            "work_authorization": "open",
            "suggested_variant": "v",
            "skills": [f"skill{i}" for i in range(12)],
        }
        tags = promote.build_tags(row)
        self.assertEqual(len(tags), promote.MAX_TAGS)
        self.assertTrue(tags[0].startswith("visa:"))
        self.assertTrue(tags[1].startswith("variant:"))


if __name__ == "__main__":
    unittest.main()

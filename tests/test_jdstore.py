import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import jdstore  # noqa: E402
import jobq  # noqa: E402


class TestSafeComponent(unittest.TestCase):
    def test_safe_component_replaces_path_separators(self):
        result = jdstore.safe_component("AI/ML Corp")
        self.assertNotIn("/", result)
        self.assertNotIn("\\", result)

    def test_safe_component_rejects_dot_dot(self):
        with self.assertRaises(jdstore.JdStoreError):
            jdstore.safe_component("..")

    def test_safe_component_rejects_bare_dot(self):
        with self.assertRaises(jdstore.JdStoreError):
            jdstore.safe_component(".")

    def test_safe_component_rejects_empty_string(self):
        with self.assertRaises(jdstore.JdStoreError):
            jdstore.safe_component("")

    def test_safe_component_rejects_whitespace_only(self):
        with self.assertRaises(jdstore.JdStoreError):
            jdstore.safe_component("   ")

    def test_safe_component_strips_all_unsafe_characters(self):
        result = jdstore.safe_component('a/b\\c:d*e?f"g<h>i|j')
        for char in '/\\:*?"<>|':
            self.assertNotIn(char, result)

    def test_safe_component_truncates_long_title_to_80_chars(self):
        result = jdstore.safe_component("A" * 300)
        self.assertLessEqual(len(result), 80)

    def test_safe_component_all_unsafe_characters_raises(self):
        with self.assertRaises(jdstore.JdStoreError):
            jdstore.safe_component("////")

    def test_safe_component_strips_leading_trailing_whitespace_and_dots(self):
        self.assertEqual(jdstore.safe_component("  .foo.  "), "foo")

    def test_safe_component_passes_unicode_through_unchanged(self):
        self.assertEqual(jdstore.safe_component("Ingénieur IA"), "Ingénieur IA")

    def test_safe_component_collapses_whitespace_runs(self):
        self.assertEqual(jdstore.safe_component("AI   Engineer"), "AI Engineer")

    def test_safe_component_rejects_none(self):
        with self.assertRaises(jdstore.JdStoreError):
            jdstore.safe_component(None)


class TestJobDir(unittest.TestCase):
    def test_job_dir_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path1 = jdstore.job_dir(tmp, "LinkedIn", "Acme Corp", "AI Engineer", "abc123")
            path2 = jdstore.job_dir(tmp, "LinkedIn", "Acme Corp", "AI Engineer", "abc123")
            self.assertEqual(path1, path2)

    def test_job_dir_shape_is_root_source_company_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = jdstore.job_dir(tmp, "LinkedIn", "Acme Corp", "AI Engineer", "abc123")
            self.assertEqual(
                path, os.path.join(tmp, "LinkedIn", "Acme Corp", "AI Engineer")
            )

    def test_job_dir_different_identity_key_gets_suffixed_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_path = jdstore.job_dir(tmp, "LinkedIn", "Acme", "AI Engineer", "aaa111")
            # Materialize the first posting so the second call sees a real collision.
            os.makedirs(first_path)
            with open(os.path.join(first_path, ".jobmeta.json"), "w", encoding="utf-8") as f:
                json.dump({"row_key": "aaa111"}, f)

            second_path = jdstore.job_dir(tmp, "LinkedIn", "Acme", "AI Engineer", "bbb222")
            self.assertNotEqual(first_path, second_path)
            self.assertTrue(second_path.endswith("-bbb222"))
            # First posting's resolved path is untouched.
            self.assertEqual(
                jdstore.job_dir(tmp, "LinkedIn", "Acme", "AI Engineer", "aaa111"),
                first_path,
            )

    def test_job_dir_returns_same_path_for_pre_existing_matching_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            expected = os.path.join(tmp, "LinkedIn", "Acme", "AI Engineer")
            os.makedirs(expected)
            with open(os.path.join(expected, ".jobmeta.json"), "w", encoding="utf-8") as f:
                json.dump({"row_key": "abc123"}, f)

            path = jdstore.job_dir(tmp, "LinkedIn", "Acme", "AI Engineer", "abc123")
            self.assertEqual(path, expected)

    def test_job_dir_does_not_create_missing_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "does-not-exist-yet")
            path = jdstore.job_dir(root, "LinkedIn", "Acme", "AI Engineer", "abc123")
            self.assertFalse(os.path.exists(root))
            self.assertEqual(path, os.path.join(root, "LinkedIn", "Acme", "AI Engineer"))

    def test_job_dir_raises_on_double_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "LinkedIn", "Acme", "AI Engineer")
            suffixed = base + "-bbb222"
            for folder, key in ((base, "aaa111"), (suffixed, "ccc333")):
                os.makedirs(folder)
                with open(os.path.join(folder, ".jobmeta.json"), "w", encoding="utf-8") as f:
                    json.dump({"row_key": key}, f)

            with self.assertRaises(jdstore.JdStoreError):
                jdstore.job_dir(tmp, "LinkedIn", "Acme", "AI Engineer", "bbb222")

    def test_job_dir_treats_folder_with_no_jobmeta_as_foreign(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "LinkedIn", "Acme", "AI Engineer")
            os.makedirs(base)  # no .jobmeta.json at all — foreign data

            path = jdstore.job_dir(tmp, "LinkedIn", "Acme", "AI Engineer", "abc123")
            self.assertTrue(path.endswith("-abc123"))

    def test_job_dir_treats_malformed_jobmeta_as_foreign(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "LinkedIn", "Acme", "AI Engineer")
            os.makedirs(base)
            with open(os.path.join(base, ".jobmeta.json"), "w", encoding="utf-8") as f:
                f.write("{not valid json")

            path = jdstore.job_dir(tmp, "LinkedIn", "Acme", "AI Engineer", "abc123")
            self.assertTrue(path.endswith("-abc123"))


class TestWriteJd(unittest.TestCase):
    def test_write_jd_creates_jd_and_meta_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = {
                "company": "Acme",
                "jobTitle": "AI Engineer",
                "jobDescription": "Full posting text...",
                "jobUrl": "https://x/1",
                "source": "LinkedIn",
            }
            result = jdstore.write_jd(tmp, row)

            jd_path = os.path.join(result["path"], "JD.md")
            meta_path = os.path.join(result["path"], ".jobmeta.json")
            with open(jd_path, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), row["jobDescription"])
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            self.assertEqual(meta["row_key"], jobq.row_key(row))

    def test_write_jd_is_idempotent_for_same_posting(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = {
                "company": "Acme",
                "jobTitle": "AI Engineer",
                "jobDescription": "Full posting text...",
                "jobUrl": "https://x/1",
                "source": "LinkedIn",
            }
            first = jdstore.write_jd(tmp, row)
            self.assertTrue(first["created"])

            second = jdstore.write_jd(tmp, row)
            self.assertFalse(second["created"])
            self.assertEqual(first["path"], second["path"])

            # Only one directory was created.
            source_dir = os.path.join(tmp, "LinkedIn", "Acme")
            self.assertEqual(os.listdir(source_dir), ["AI Engineer"])

            with open(os.path.join(second["path"], "JD.md"), "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), row["jobDescription"])

    def test_write_jd_rejects_missing_job_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = {
                "company": "Acme",
                "jobTitle": "AI Engineer",
                "jobDescription": "",
                "jobUrl": "https://x/1",
                "source": "LinkedIn",
            }
            with self.assertRaises(jdstore.JdStoreError):
                jdstore.write_jd(tmp, row)

    def test_write_jd_rejects_missing_job_description_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = {
                "company": "Acme",
                "jobTitle": "AI Engineer",
                "jobUrl": "https://x/1",
                "source": "LinkedIn",
            }
            with self.assertRaises(jdstore.JdStoreError):
                jdstore.write_jd(tmp, row)


class TestWriteJdFiles(unittest.TestCase):
    def test_write_jd_files_reports_per_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [
                {
                    "company": "Acme",
                    "jobTitle": "AI Engineer",
                    "jobDescription": "Acme posting text.",
                    "jobUrl": "https://x/1",
                    "source": "LinkedIn",
                },
                {
                    "company": "Globex",
                    "jobTitle": "ML Engineer",
                    "jobDescription": "",
                    "jobUrl": "https://x/2",
                    "source": "LinkedIn",
                },
                {
                    "company": "Initech",
                    "jobTitle": "Data Engineer",
                    "jobDescription": "Initech posting text.",
                    "jobUrl": "https://x/3",
                    "source": "LinkedIn",
                },
            ]

            result = jdstore.write_jd_files(tmp, rows)

            self.assertEqual(len(result["written"]), 2)
            self.assertEqual(result["skipped_existing"], [])
            self.assertEqual(len(result["errors"]), 1)
            self.assertEqual(result["errors"][0]["company"], "Globex")
            self.assertEqual(result["errors"][0]["jobTitle"], "ML Engineer")

            for path in result["written"]:
                self.assertTrue(os.path.isfile(os.path.join(path, "JD.md")))

            globex_dir = os.path.join(tmp, "LinkedIn", "Globex")
            self.assertFalse(os.path.exists(globex_dir))

    def test_write_jd_files_empty_list_returns_all_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = jdstore.write_jd_files(tmp, [])
            self.assertEqual(result, {"written": [], "skipped_existing": [], "errors": []})

    def test_write_jd_files_duplicate_within_batch_is_skipped_not_errored(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = {
                "company": "Acme",
                "jobTitle": "AI Engineer",
                "jobDescription": "Acme posting text.",
                "jobUrl": "https://x/1",
                "source": "LinkedIn",
            }
            rows = [row, dict(row)]

            result = jdstore.write_jd_files(tmp, rows)

            self.assertEqual(len(result["written"]), 1)
            self.assertEqual(len(result["skipped_existing"]), 1)
            self.assertEqual(result["written"][0], result["skipped_existing"][0])
            self.assertEqual(result["errors"], [])


if __name__ == "__main__":
    unittest.main()


_JD_BODY = (
    "We are looking for an AI Engineer to join {company}. You will design, build and "
    "operate machine learning services in production. Requirements: five years of Python, "
    "experience with PyTorch, strong SQL, and a track record of shipping models to "
    "customers. You will work with product managers and designers, review code, mentor "
    "junior engineers, and own the reliability of the inference platform. Nice to have: "
    "Kubernetes, Terraform, and experience with retrieval augmented generation systems. "
    "{company} offers remote work, a learning budget, and a small friendly team."
)


def _make_folder(root, source, company, role, jd_text, approved=True, meta="ok", write_jd_file=True):
    folder = os.path.join(root, source, company, role)
    os.makedirs(folder)
    if write_jd_file:
        with open(os.path.join(folder, "JD.md"), "w", encoding="utf-8") as f:
            f.write(jd_text)
    if meta == "ok":
        with open(os.path.join(folder, ".jobmeta.json"), "w", encoding="utf-8") as f:
            json.dump({"company": company, "jobTitle": role, "row_key": "k-" + company}, f)
    elif meta == "malformed":
        with open(os.path.join(folder, ".jobmeta.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
    with open(os.path.join(folder, "requirements-map.md"), "w", encoding="utf-8") as f:
        f.write("approved: 2026-09-01\n" if approved else "draft, not yet approved\n")
    return folder


class TestFindSimilar(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name

    def test_find_similar_detects_near_identical_jd(self):
        _make_folder(self.root, "LinkedIn", "Acme Corp", "AI Engineer",
                     _JD_BODY.format(company="Acme Corp"))
        matches = jdstore.find_similar(
            self.root, _JD_BODY.format(company="Globex Inc"), threshold=0.90
        )
        self.assertTrue(matches)
        self.assertEqual(matches[0]["company"], "Acme Corp")
        self.assertEqual(matches[0]["role"], "AI Engineer")
        self.assertGreaterEqual(matches[0]["ratio"], 0.90)

    def test_missing_root_returns_empty(self):
        self.assertEqual(jdstore.find_similar(os.path.join(self.root, "nope"), "x"), [])

    def test_unapproved_map_is_excluded(self):
        _make_folder(self.root, "LinkedIn", "Acme Corp", "AI Engineer",
                     _JD_BODY.format(company="Acme Corp"), approved=False)
        self.assertEqual(jdstore.find_similar(self.root, _JD_BODY.format(company="X")), [])

    def test_missing_sibling_jd_is_excluded_without_crash(self):
        _make_folder(self.root, "LinkedIn", "Acme Corp", "AI Engineer", "",
                     write_jd_file=False)
        self.assertEqual(jdstore.find_similar(self.root, _JD_BODY.format(company="X")), [])

    def test_malformed_meta_is_skipped_others_still_scanned(self):
        _make_folder(self.root, "LinkedIn", "Bad Co", "AI Engineer",
                     _JD_BODY.format(company="Bad Co"), meta="malformed")
        _make_folder(self.root, "LinkedIn", "Acme Corp", "AI Engineer",
                     _JD_BODY.format(company="Acme Corp"))
        matches = jdstore.find_similar(self.root, _JD_BODY.format(company="Globex Inc"))
        self.assertEqual([m["company"] for m in matches], ["Acme Corp"])

    def test_absent_meta_is_skipped(self):
        _make_folder(self.root, "LinkedIn", "Acme Corp", "AI Engineer",
                     _JD_BODY.format(company="Acme Corp"), meta="absent")
        self.assertEqual(jdstore.find_similar(self.root, _JD_BODY.format(company="X")), [])

    def test_below_threshold_excluded(self):
        _make_folder(self.root, "LinkedIn", "Acme Corp", "AI Engineer",
                     _JD_BODY.format(company="Acme Corp"))
        _make_folder(self.root, "LinkedIn", "Zeta", "Chef",
                     "Cook meals in a busy restaurant kitchen, manage inventory and "
                     "supervise line cooks during dinner service every evening.")
        matches = jdstore.find_similar(self.root, _JD_BODY.format(company="Globex Inc"))
        self.assertEqual([m["company"] for m in matches], ["Acme Corp"])

    def test_multiple_matches_sorted_descending(self):
        _make_folder(self.root, "LinkedIn", "Acme Corp", "AI Engineer",
                     _JD_BODY.format(company="Acme Corp"))
        _make_folder(self.root, "Lever", "Initech", "AI Engineer",
                     _JD_BODY.format(company="Initech") + " Extra perk: free lunch.")
        matches = jdstore.find_similar(
            self.root, _JD_BODY.format(company="Globex Inc"), threshold=0.80
        )
        self.assertEqual(len(matches), 2)
        self.assertGreaterEqual(matches[0]["ratio"], matches[1]["ratio"])
        self.assertEqual(matches[0]["company"], "Acme Corp")

    def test_self_comparison_ratio_is_one(self):
        text = _JD_BODY.format(company="Acme Corp")
        _make_folder(self.root, "LinkedIn", "Acme Corp", "AI Engineer", text)
        matches = jdstore.find_similar(self.root, text)
        self.assertEqual(matches[0]["ratio"], 1.0)

    def test_unrelated_jd_far_below_threshold(self):
        _make_folder(self.root, "LinkedIn", "Acme Corp", "AI Engineer",
                     _JD_BODY.format(company="Acme Corp"))
        self.assertEqual(
            jdstore.find_similar(self.root, "Sell insurance door to door in rural areas."), []
        )

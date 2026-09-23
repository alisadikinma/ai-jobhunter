import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import jdstore  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()

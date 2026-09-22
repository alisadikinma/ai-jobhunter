import json
import os
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import envfile  # noqa: E402


class TestReadKeyEnvWinsOverFile(unittest.TestCase):
    def test_env_wins_over_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("APIFY_TOKEN=from-file\n")
            with unittest.mock.patch.dict(
                os.environ, {"APIFY_TOKEN": "from-env"}, clear=False
            ):
                self.assertEqual(envfile.read_key("APIFY_TOKEN", path), "from-env")


class TestReadKeyFileFallback(unittest.TestCase):
    def test_file_fallback_when_env_absent(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("APIFY_TOKEN=from-file\n")
            with unittest.mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("APIFY_TOKEN", None)
                self.assertEqual(envfile.read_key("APIFY_TOKEN", path), "from-file")


class TestReadKeyExportPrefix(unittest.TestCase):
    def test_export_prefix_stripped(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("export APIFY_TOKEN=from-file\n")
            with unittest.mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("APIFY_TOKEN", None)
                self.assertEqual(envfile.read_key("APIFY_TOKEN", path), "from-file")


class TestReadKeyDoubleQuoted(unittest.TestCase):
    def test_double_quoted_value_stripped(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write('APIFY_TOKEN="from-file"\n')
            with unittest.mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("APIFY_TOKEN", None)
                self.assertEqual(envfile.read_key("APIFY_TOKEN", path), "from-file")


class TestReadKeySingleQuoted(unittest.TestCase):
    def test_single_quoted_value_stripped(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("APIFY_TOKEN='from-file'\n")
            with unittest.mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("APIFY_TOKEN", None)
                self.assertEqual(envfile.read_key("APIFY_TOKEN", path), "from-file")


class TestReadKeySplitsOnFirstEquals(unittest.TestCase):
    def test_value_with_equals_sign_kept_whole(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("APIFY_TOKEN=a=b\n")
            with unittest.mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("APIFY_TOKEN", None)
                self.assertEqual(envfile.read_key("APIFY_TOKEN", path), "a=b")


class TestReadKeyCommentIgnored(unittest.TestCase):
    def test_commented_line_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("# APIFY_TOKEN=x\n")
            with unittest.mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("APIFY_TOKEN", None)
                self.assertIsNone(envfile.read_key("APIFY_TOKEN", path))


class TestReadKeyBlankEnvFallsThroughToFile(unittest.TestCase):
    def test_blank_env_value_falls_through_to_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("APIFY_TOKEN=from-file\n")
            with unittest.mock.patch.dict(
                os.environ, {"APIFY_TOKEN": "   "}, clear=False
            ):
                self.assertEqual(envfile.read_key("APIFY_TOKEN", path), "from-file")


class TestReadKeyMissingFile(unittest.TestCase):
    def test_missing_file_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "does-not-exist.env")
            with unittest.mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("APIFY_TOKEN", None)
                self.assertIsNone(envfile.read_key("APIFY_TOKEN", path))


class TestReadKeyAbsentInFile(unittest.TestCase):
    def test_key_absent_in_file_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("OTHER_KEY=x\n")
            with unittest.mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("APIFY_TOKEN", None)
                self.assertIsNone(envfile.read_key("APIFY_TOKEN", path))


class TestReadKeyMismatchedQuotesKeptVerbatim(unittest.TestCase):
    def test_mismatched_quotes_kept_verbatim(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("APIFY_TOKEN=\"from-file'\n")
            with unittest.mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("APIFY_TOKEN", None)
                self.assertEqual(
                    envfile.read_key("APIFY_TOKEN", path), "\"from-file'"
                )


class TestReadKeyUnreadableFileRaises(unittest.TestCase):
    def test_unreadable_file_raises_envfileerror_without_content(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "secret.env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("APIFY_TOKEN=super-secret-value\n")
            os.chmod(path, 0o000)
            try:
                with unittest.mock.patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("APIFY_TOKEN", None)
                    with self.assertRaises(envfile.EnvFileError) as ctx:
                        envfile.read_key("APIFY_TOKEN", path)
                    self.assertNotIn("super-secret-value", str(ctx.exception))
                    self.assertIn(path, str(ctx.exception))
            finally:
                os.chmod(path, 0o644)


class TestKeyStatusNeverContainsValue(unittest.TestCase):
    def test_key_status_never_contains_value(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("APIFY_TOKEN=super-secret-value\n")
            with unittest.mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("APIFY_TOKEN", None)
                os.environ.pop("FIRECRAWL_API_KEY", None)
                result = envfile.key_status(
                    ["APIFY_TOKEN", "FIRECRAWL_API_KEY"], path
                )
                self.assertNotIn("super-secret-value", json.dumps(result))
                self.assertEqual(result["APIFY_TOKEN"], "present")
                self.assertEqual(result["FIRECRAWL_API_KEY"], "missing")
                self.assertEqual(result["env_file"], os.path.abspath(path))


class TestKeyStatusEnvFileNotFound(unittest.TestCase):
    def test_key_status_env_file_not_found(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "missing.env")
            with unittest.mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("APIFY_TOKEN", None)
                result = envfile.key_status(["APIFY_TOKEN"], path)
                self.assertEqual(result["env_file"], "not found")
                self.assertEqual(result["APIFY_TOKEN"], "missing")


if __name__ == "__main__":
    unittest.main()

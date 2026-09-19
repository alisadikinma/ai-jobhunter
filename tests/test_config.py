import os
import sys
import tempfile
import unittest
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import config  # noqa: E402


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class TestLoadDefaults(unittest.TestCase):
    def test_load_fills_budget_defaults_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.toml")
            _write(path, "[targets]\ngeo = []\n")
            cfg = config.load(path)
            self.assertEqual(cfg["budgets"]["firecrawl_credits_per_run"], 150)
            self.assertEqual(cfg["budgets"]["jobsync_requests_per_run"], 50)

    def test_load_budgets_from_file_override_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.toml")
            _write(
                path,
                "[budgets]\nfirecrawl_credits_per_run = 30\n"
                "jobsync_requests_per_run = 10\n",
            )
            cfg = config.load(path)
            self.assertEqual(cfg["budgets"]["firecrawl_credits_per_run"], 30)
            self.assertEqual(cfg["budgets"]["jobsync_requests_per_run"], 10)


class TestLoadErrors(unittest.TestCase):
    def test_missing_config_file_raises_named_error_naming_profile_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "does-not-exist.toml")
            with self.assertRaises(config.ConfigMissingError) as ctx:
                config.load(path)
            self.assertIn("/ai-jobhunter:profile", str(ctx.exception))

    def test_malformed_toml_surfaces_underlying_tomllib_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.toml")
            _write(path, "this is not [valid toml\n===")
            with self.assertRaises(config.TOML_DECODE_ERROR):
                config.load(path)

    def test_unknown_top_level_key_warns_and_does_not_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.toml")
            _write(path, "[totally_unknown_section]\nfoo = 1\n")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                cfg = config.load(path)
            self.assertTrue(
                any("totally_unknown_section" in str(w.message) for w in caught)
            )
            # still loads, defaults still filled
            self.assertEqual(cfg["budgets"]["firecrawl_credits_per_run"], 150)


class TestMinSalaryUnset(unittest.TestCase):
    def test_min_salary_absent_is_unset(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.toml")
            _write(path, "[targets]\ngeo = []\n")
            cfg = config.load(path)
            self.assertIsNone(cfg["targets"]["min_salary_usd"])

    def test_min_salary_literal_zero_is_unset(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.toml")
            _write(path, "[targets]\nmin_salary_usd = 0\n")
            cfg = config.load(path)
            self.assertIsNone(cfg["targets"]["min_salary_usd"])

    def test_min_salary_real_value_is_preserved_and_not_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.toml")
            _write(path, "[targets]\nmin_salary_usd = 120000\n")
            cfg = config.load(path)
            self.assertEqual(cfg["targets"]["min_salary_usd"], 120000)
            self.assertIsNotNone(cfg["targets"]["min_salary_usd"])


class TestRelativePathResolution(unittest.TestCase):
    def test_relative_linkedin_pdf_resolves_against_config_dir_not_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = os.path.join(tmp, "project")
            os.makedirs(config_dir)
            path = os.path.join(config_dir, "config.toml")
            _write(
                path,
                '[profile_sources]\nlinkedin_pdf = "./linkedin-profile.pdf"\n',
            )
            # Run from an unrelated cwd to prove resolution ignores it.
            other_cwd = os.path.join(tmp, "somewhere-else")
            os.makedirs(other_cwd)
            original_cwd = os.getcwd()
            os.chdir(other_cwd)
            try:
                cfg = config.load(path)
            finally:
                os.chdir(original_cwd)
            expected = os.path.normpath(os.path.join(config_dir, "linkedin-profile.pdf"))
            self.assertEqual(cfg["profile_sources"]["linkedin_pdf"], expected)

    def test_absolute_linkedin_pdf_passes_through_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.toml")
            abs_pdf = os.path.join(tmp, "elsewhere", "cv.pdf")
            _write(path, f'[profile_sources]\nlinkedin_pdf = "{abs_pdf}"\n')
            cfg = config.load(path)
            self.assertEqual(cfg["profile_sources"]["linkedin_pdf"], abs_pdf)


class TestProvenance(unittest.TestCase):
    def test_provenance_reports_file_vs_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.toml")
            _write(path, "[budgets]\nfirecrawl_credits_per_run = 30\n")
            cfg = config.load(path)
            prov = cfg["_provenance"]
            self.assertEqual(prov["budgets.firecrawl_credits_per_run"], "file")
            self.assertEqual(prov["budgets.jobsync_requests_per_run"], "default")
            self.assertEqual(prov["targets.min_salary_usd"], "default")


class TestResolveProfileSourcesOrdering(unittest.TestCase):
    def test_returns_entries_in_configured_precedence_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.toml")
            _write(
                path,
                '[profile_sources]\n'
                'sites = ["https://example.com/"]\n'
                'linkedin_pdf = "./linkedin.pdf"\n'
                'local = ["./notes/a.md"]\n'
                'primary = "./notes/card.md"\n'
                'precedence = ["local-primary", "local", "linkedin-pdf", "site"]\n',
            )
            cfg = config.load(path)
            sources = config.resolve_profile_sources(cfg)
            tiers = [tier for tier, _ in sources]
            self.assertEqual(tiers, ["local-primary", "local", "linkedin-pdf", "site"])

    def test_unknown_precedence_tier_raises(self):
        """A tier naming no config field must fail loudly, not resolve to nothing.

        Resolving it to zero entries means one typo drops a whole class of
        source while the compiled profile still looks complete.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.toml")
            _write(
                path,
                '[profile_sources]\n'
                'sites = ["https://example.com/"]\n'
                'precedence = ["site", "prodcut-site"]\n',
            )
            cfg = config.load(path)
            with self.assertRaises(config.PrecedenceError) as ctx:
                config.resolve_profile_sources(cfg)
            self.assertIn("prodcut-site", str(ctx.exception))
            self.assertIn("Known tiers:", str(ctx.exception))

    def test_known_tier_with_nothing_configured_contributes_no_entries(self):
        """A known tier whose field is empty is legitimate and stays silent."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.toml")
            _write(
                path,
                '[profile_sources]\n'
                'local = []\n'
                'sites = ["https://example.com/"]\n'
                'precedence = ["local", "site"]\n',
            )
            cfg = config.load(path)
            sources = config.resolve_profile_sources(cfg)
            self.assertEqual(sources, [("site", "https://example.com/")])


class TestResolveProfileSourcesProjectAllowList(unittest.TestCase):
    def _make_root(self, tmp, dirnames):
        root = os.path.join(tmp, "projects")
        os.makedirs(root)
        for name in dirnames:
            os.makedirs(os.path.join(root, name))
        return root

    def test_only_allowlisted_directories_are_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp, ["project-a", "project-b"])
            path = os.path.join(tmp, "config.toml")
            _write(
                path,
                '[profile_sources]\nprecedence = ["project"]\n'
                f'[profile_sources.projects]\nroot = "{root}"\n'
                'allowed = ["project-a"]\n',
            )
            cfg = config.load(path)
            sources = config.resolve_profile_sources(cfg)
            self.assertEqual(sources, [("project", os.path.join(root, "project-a"))])

    def test_directory_on_disk_but_not_allowlisted_is_never_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp, ["project-a", "project-secret-client"])
            path = os.path.join(tmp, "config.toml")
            _write(
                path,
                '[profile_sources]\nprecedence = ["project"]\n'
                f'[profile_sources.projects]\nroot = "{root}"\n'
                'allowed = ["project-a"]\n',
            )
            cfg = config.load(path)
            sources = config.resolve_profile_sources(cfg)
            returned_paths = [p for _, p in sources]
            self.assertNotIn(os.path.join(root, "project-secret-client"), returned_paths)
            self.assertEqual(len(sources), 1)

    def test_allowlisted_name_missing_on_disk_raises_named_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp, ["project-a"])
            path = os.path.join(tmp, "config.toml")
            _write(
                path,
                '[profile_sources]\nprecedence = ["project"]\n'
                f'[profile_sources.projects]\nroot = "{root}"\n'
                'allowed = ["project-a", "project-ghost"]\n',
            )
            cfg = config.load(path)
            with self.assertRaises(config.ProjectSourceError) as ctx:
                config.resolve_profile_sources(cfg)
            self.assertIn("project-ghost", str(ctx.exception))

    def test_allowed_entry_with_dotdot_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp, ["project-a"])
            path = os.path.join(tmp, "config.toml")
            _write(
                path,
                '[profile_sources]\nprecedence = ["project"]\n'
                f'[profile_sources.projects]\nroot = "{root}"\n'
                'allowed = ["../outside"]\n',
            )
            cfg = config.load(path)
            with self.assertRaises(config.ProjectSourceError):
                config.resolve_profile_sources(cfg)

    def test_allowed_entry_with_path_separator_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp, ["project-a"])
            os.makedirs(os.path.join(root, "sub"))
            path = os.path.join(tmp, "config.toml")
            _write(
                path,
                '[profile_sources]\nprecedence = ["project"]\n'
                f'[profile_sources.projects]\nroot = "{root}"\n'
                'allowed = ["project-a/sub"]\n',
            )
            cfg = config.load(path)
            with self.assertRaises(config.ProjectSourceError):
                config.resolve_profile_sources(cfg)

    def test_allowed_entry_with_absolute_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp, ["project-a"])
            path = os.path.join(tmp, "config.toml")
            absolute_entry = os.path.join(root, "project-a")
            _write(
                path,
                '[profile_sources]\nprecedence = ["project"]\n'
                f'[profile_sources.projects]\nroot = "{root}"\n'
                f'allowed = ["{absolute_entry}"]\n',
            )
            cfg = config.load(path)
            with self.assertRaises(config.ProjectSourceError):
                config.resolve_profile_sources(cfg)

    def test_empty_allowed_returns_no_project_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp, ["project-a"])
            path = os.path.join(tmp, "config.toml")
            _write(
                path,
                '[profile_sources]\nprecedence = ["project"]\n'
                f'[profile_sources.projects]\nroot = "{root}"\n'
                'allowed = []\n',
            )
            cfg = config.load(path)
            sources = config.resolve_profile_sources(cfg)
            self.assertEqual(sources, [])

    def test_allowed_names_match_exactly_no_glob_expansion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp, ["project-a", "project-ab", "project-abc"])
            path = os.path.join(tmp, "config.toml")
            _write(
                path,
                '[profile_sources]\nprecedence = ["project"]\n'
                f'[profile_sources.projects]\nroot = "{root}"\n'
                'allowed = ["project-a*"]\n',
            )
            cfg = config.load(path)
            # "project-a*" is a literal name, and no directory is literally
            # named that, so it must raise rather than glob-match anything.
            with self.assertRaises(config.ProjectSourceError):
                config.resolve_profile_sources(cfg)

    def test_root_directory_itself_is_never_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(
                tmp, ["project-a", "project-b", "project-c", "project-secret"]
            )
            path = os.path.join(tmp, "config.toml")
            _write(
                path,
                '[profile_sources]\nprecedence = ["project"]\n'
                f'[profile_sources.projects]\nroot = "{root}"\n'
                'allowed = ["project-a"]\n',
            )
            cfg = config.load(path)
            sources = config.resolve_profile_sources(cfg)
            # Only exactly what was allow-listed comes back, never the
            # other three directories that also exist on disk.
            self.assertEqual(len(sources), 1)


if __name__ == "__main__":
    unittest.main()


class TestBudgetTypeValidation(unittest.TestCase):
    """A budget is spent, so it must be a number before anything spends it."""

    def _load_with(self, tmp, line):
        path = os.path.join(tmp, "config.toml")
        _write(path, "[budgets]\n" + line + "\n")
        return config.load(path)

    def test_quoted_number_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(config.BudgetTypeError) as ctx:
                self._load_with(tmp, 'firecrawl_credits_per_run = "150"')
            self.assertIn("firecrawl_credits_per_run", str(ctx.exception))
            self.assertIn("str", str(ctx.exception))

    def test_float_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(config.BudgetTypeError):
                self._load_with(tmp, "jobsync_requests_per_run = 12.5")

    def test_boolean_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(config.BudgetTypeError):
                self._load_with(tmp, "jobsync_requests_per_run = true")

    def test_negative_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(config.BudgetTypeError) as ctx:
                self._load_with(tmp, "firecrawl_credits_per_run = -1")
            self.assertIn("negative", str(ctx.exception))

    def test_zero_is_accepted_as_a_real_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._load_with(tmp, "firecrawl_credits_per_run = 0")
            self.assertEqual(cfg["budgets"]["firecrawl_credits_per_run"], 0)

    def test_a_valid_integer_passes_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._load_with(tmp, "firecrawl_credits_per_run = 42")
            self.assertEqual(cfg["budgets"]["firecrawl_credits_per_run"], 42)


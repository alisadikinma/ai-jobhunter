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
            # The RESOLVED path is returned, so the containment guarantee
            # travels with the value rather than being left behind at the
            # check. On macOS /var is itself a symlink to /private/var, so
            # comparing against the unresolved path would fail here for a
            # reason that has nothing to do with the allow-list.
            self.assertEqual(
                sources,
                [("project", os.path.realpath(os.path.join(root, "project-a")))],
            )

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


class TestAllowListCannotResolveToTheRoot(unittest.TestCase):
    """The allow-list is a privacy control. An entry that resolves to the
    root turns it into "read everything", which is the one mode the design
    rules out — unlisted project notes hold third parties' confidential
    material.
    """

    def _cfg(self, root, allowed):
        return {
            "profile_sources": {
                "precedence": ["project"],
                "projects": {"root": root, "allowed": allowed},
            }
        }

    def _root(self, tmp):
        root = os.path.join(tmp, "root")
        os.makedirs(os.path.join(root, "allowed"))
        os.makedirs(os.path.join(root, "secret-client"))
        return root

    def test_dot_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(config.ProjectSourceError):
                config.resolve_profile_sources(self._cfg(self._root(tmp), ["."]))

    def test_empty_string_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(config.ProjectSourceError):
                config.resolve_profile_sources(self._cfg(self._root(tmp), [""]))

    def test_whitespace_only_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(config.ProjectSourceError):
                config.resolve_profile_sources(self._cfg(self._root(tmp), ["   "]))

    def test_symlink_pointing_outside_the_root_is_rejected(self):
        """A symlink's NAME is allow-listed; what it points at is not."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            outside = os.path.join(tmp, "client-files")
            os.makedirs(outside)
            os.symlink(outside, os.path.join(root, "innocent-name"))
            with self.assertRaises(config.ProjectSourceError) as ctx:
                config.resolve_profile_sources(self._cfg(root, ["innocent-name"]))
            self.assertIn("not to", str(ctx.exception))

    def test_symlink_to_a_sibling_under_the_root_is_also_rejected(self):
        """This test used to assert the opposite, and asserting the opposite
        was the seventh allow-list bypass.

        `alias -> allowed` stays inside the root, so the old "resolves under
        the root" check passed it — and handed back `allowed`, a directory
        the config never named. Measured on the pre-fix tree, reading
        `root/not-allowlisted/nda.md` through an allow-list entry called
        `allowed`. Inside-the-root is not the contract; being the directory
        of that name is.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            os.symlink(os.path.join(root, "allowed"), os.path.join(root, "alias"))
            with self.assertRaises(config.ProjectSourceError) as ctx:
                config.resolve_profile_sources(self._cfg(root, ["alias"]))
            self.assertIn("resolves to", str(ctx.exception))

    def test_an_unlisted_sibling_is_still_never_returned(self):
        """The real assertion the old test of this name never made: reach for
        the root and confirm the unlisted directory does not come back.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            sources = config.resolve_profile_sources(self._cfg(root, ["allowed"]))
            returned = [path for _, path in sources]
            self.assertEqual(len(returned), 1)
            self.assertTrue(returned[0].endswith("allowed"))
            self.assertFalse(any("secret-client" in p for p in returned))

    def test_allowed_without_root_names_the_missing_key(self):
        with self.assertRaises(config.ProjectSourceError) as ctx:
            config.resolve_profile_sources(self._cfg(None, ["allowed"]))
        self.assertIn("projects.root", str(ctx.exception))


class TestSalaryAndSectionTypos(unittest.TestCase):
    def _load(self, tmp, body):
        path = os.path.join(tmp, "config.toml")
        _write(path, body)
        return config.load(path)

    def test_quoted_salary_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(config.SalaryTypeError):
                self._load(tmp, '[targets]\nmin_salary_usd = "120000"\n')

    def test_negative_salary_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(config.SalaryTypeError):
                self._load(tmp, "[targets]\nmin_salary_usd = -5\n")

    def test_typo_inside_a_section_warns_instead_of_failing_silently(self):
        """`precedance` left precedence empty and the profile compiled from
        zero sources with no error anywhere.
        """
        with tempfile.TemporaryDirectory() as tmp:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                self._load(tmp, '[profile_sources]\nprecedance = ["site"]\n')
            messages = [str(w.message) for w in caught]
            self.assertTrue(any("precedance" in m for m in messages), messages)


class TestNestedLinksCannotEscapeTheAllowList(unittest.TestCase):
    """Checking only the allow-listed entry protects one level. A link INSIDE
    it has an innocent name, is never inspected, and any ordinary walk
    follows it — measured reading a file out of a client directory through
    `projects/allowed/notes -> /client-work`.
    """

    def _cfg(self, root, allowed=("allowed",)):
        return {
            "profile_sources": {
                "precedence": ["project"],
                "projects": {"root": root, "allowed": list(allowed)},
            }
        }

    def test_a_link_inside_an_allowed_directory_leading_out_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "root")
            os.makedirs(os.path.join(root, "allowed"))
            outside = os.path.join(tmp, "client-work")
            os.makedirs(outside)
            with open(os.path.join(outside, "nda.md"), "w", encoding="utf-8") as f:
                f.write("confidential")
            os.symlink(outside, os.path.join(root, "allowed", "notes"))
            with self.assertRaises(config.ProjectSourceError) as ctx:
                config.resolve_profile_sources(self._cfg(root))
            self.assertIn("leading outside it", str(ctx.exception))

    def test_a_link_pointing_back_inside_the_root_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "root")
            os.makedirs(os.path.join(root, "allowed", "sub"))
            os.symlink(
                os.path.join(root, "allowed", "sub"),
                os.path.join(root, "allowed", "alias"),
            )
            self.assertEqual(len(config.resolve_profile_sources(self._cfg(root))), 1)

    def test_a_nested_link_to_the_root_itself_is_refused(self):
        """`ln -s ..` inside an allow-listed directory, named `archive`.

        One character, an innocent name, and the whole root is readable at
        `allowed/archive/<anything>`. The guard that measured containment
        against the root whitelisted this case explicitly.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "root")
            os.makedirs(os.path.join(root, "allowed"))
            secret = os.path.join(root, "client-acme-pricing")
            os.makedirs(secret)
            with open(os.path.join(secret, "negotiation.md"), "w", encoding="utf-8") as f:
                f.write("undecided negotiation")
            os.symlink("..", os.path.join(root, "allowed", "archive"))
            with self.assertRaises(config.ProjectSourceError) as ctx:
                config.resolve_profile_sources(self._cfg(root))
            self.assertIn("leading outside it", str(ctx.exception))

    def test_a_nested_link_to_an_unlisted_sibling_is_refused(self):
        """Staying under the root is not staying inside the allow-list.

        `allowed/peek -> ../client-work` never leaves the root, and the
        pre-fix guard returned it. Measured reading `client-work/nda.md`.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "root")
            os.makedirs(os.path.join(root, "allowed"))
            sibling = os.path.join(root, "client-work")
            os.makedirs(sibling)
            with open(os.path.join(sibling, "nda.md"), "w", encoding="utf-8") as f:
                f.write("client pricing")
            os.symlink(sibling, os.path.join(root, "allowed", "peek"))
            with self.assertRaises(config.ProjectSourceError) as ctx:
                config.resolve_profile_sources(self._cfg(root))
            self.assertIn("leading outside it", str(ctx.exception))

    def test_a_subtree_that_cannot_be_listed_is_refused_not_skipped(self):
        """`os.walk`'s default `onerror=None` discards every OSError from
        `scandir`, so a directory the guard cannot enumerate is a directory
        whose links are never inspected — and the walk returns as though it
        had checked them. Measured before the fix: the guard said ALLOWED and
        the planted file was readable through the entry it handed back.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "root")
            sub = os.path.join(root, "allowed", "sub")
            os.makedirs(sub)
            secret = os.path.join(root, "client-work")
            os.makedirs(secret)
            with open(os.path.join(secret, "nda.md"), "w", encoding="utf-8") as f:
                f.write("client pricing")
            os.symlink(secret, os.path.join(sub, "out"))
            os.chmod(sub, 0o311)  # traversable, not listable
            try:
                with self.assertRaises(config.ProjectSourceError) as ctx:
                    config.resolve_profile_sources(self._cfg(root))
                self.assertIn("could not be inspected", str(ctx.exception))
            finally:
                os.chmod(sub, 0o755)

    def test_a_deeply_nested_escaping_link_is_still_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "root")
            deep = os.path.join(root, "allowed", "a", "b", "c")
            os.makedirs(deep)
            outside = os.path.join(tmp, "elsewhere")
            os.makedirs(outside)
            os.symlink(outside, os.path.join(deep, "escape"))
            with self.assertRaises(config.ProjectSourceError):
                config.resolve_profile_sources(self._cfg(root))

    def test_allowed_given_as_a_bare_string_says_so(self):
        """`allowed = "notes"` — brackets forgotten — was exploded into
        ["n","o","t","e","s"] and refused by naming a directory the author
        never wrote. It failed closed either way; this makes the diagnosis
        match the mistake."""
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "root")
            os.makedirs(os.path.join(root, "allowed"))
            cfg = {
                "profile_sources": {
                    "precedence": ["project"],
                    "projects": {"root": root, "allowed": "allowed"},
                }
            }
            with self.assertRaises(config.ProjectSourceError) as ctx:
                config.resolve_profile_sources(cfg)
            self.assertIn("not a single string", str(ctx.exception))

    def test_returned_paths_are_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "root")
            os.makedirs(os.path.join(root, "allowed"))
            (tier, path), = config.resolve_profile_sources(self._cfg(root))
            self.assertEqual(path, os.path.realpath(path))


class TestNestedSectionTypos(unittest.TestCase):
    """`alowed` left `allowed` empty, and because an empty list is falsy even
    the "allowed without root" guard stayed quiet.
    """

    def _load(self, tmp, body):
        path = os.path.join(tmp, "config.toml")
        _write(path, body)
        return config.load(path)

    def test_typo_in_projects_table_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                self._load(tmp, '[profile_sources.projects]\nalowed = ["a"]\nroot = "/tmp"\n')
            self.assertTrue(any("alowed" in str(w.message) for w in caught))

    def test_typo_in_tracking_table_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                self._load(tmp, '[tracking]\njobsync_mpc = "required"\n')
            self.assertTrue(any("jobsync_mpc" in str(w.message) for w in caught))

    def test_root_slash_does_not_produce_a_false_outside_claim(self):
        self.assertTrue(config._is_under("/Users", "/"))
        self.assertFalse(config._is_under("/Users", "/etc"))


if __name__ == "__main__":
    unittest.main()

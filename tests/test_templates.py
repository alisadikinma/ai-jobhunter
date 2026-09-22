"""Tests for `scripts/templates.py` — CV template loader and `check_cv`.

`sys.path` is pointed at `scripts/` the same way every other test module in
this repository does it. That also settles a naming question the plan calls
out explicitly: this repository has a `templates/` directory at its root
(holding the actual `.md` template files) sitting right next to `scripts/`,
and a `scripts/templates.py` module. Because `scripts/` is inserted at the
front of `sys.path` (not the repo root), `import templates` resolves to the
*module*, never the directory — proven below rather than assumed.
"""

import os
import re
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import pdf  # noqa: E402
import templates  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CV_TEMPLATE_NAMES = ("hybrid", "leadership", "technical")

# A section-only heading: `## `, not `### ` (the experience-entry skeleton
# inside Work Experience, which is not a section of its own).
_SECTION_HEADING_RE = re.compile(r"^##(?!#)\s+(.*)$", re.M)


class TestModuleIdentity(unittest.TestCase):
    def test_templates_import_resolves_to_the_scripts_module_not_the_directory(self):
        # The repo also has a `templates/` directory (the template files
        # themselves) at the repo root. If `sys.path` ever put the repo root
        # ahead of `scripts/`, `import templates` would resolve to that
        # directory (a namespace package) instead of `scripts/templates.py`,
        # and every function below would silently vanish rather than fail
        # loudly. Pin it down explicitly.
        self.assertTrue(
            templates.__file__.replace(os.sep, "/").endswith("scripts/templates.py")
        )


class TestListCvTemplates(unittest.TestCase):
    def test_lists_all_three_sorted(self):
        self.assertEqual(templates.list_cv_templates(), ["hybrid", "leadership", "technical"])


class TestLoadCvTemplate(unittest.TestCase):
    def test_technical_first_section_is_professional_summary_aliased_summary(self):
        loaded = templates.load_cv_template("technical")
        self.assertEqual(
            loaded["sections"][0],
            {"name": "Professional Summary", "aliases": ["Summary"], "optional": False},
        )

    def test_all_three_load_without_error(self):
        for name in CV_TEMPLATE_NAMES:
            with self.subTest(name=name):
                loaded = templates.load_cv_template(name)
                self.assertEqual(loaded["name"], name)
                self.assertTrue(loaded["sections"])

    def test_leadership_board_positions_alias_and_optional(self):
        loaded = templates.load_cv_template("leadership")
        section = next(s for s in loaded["sections"] if s["name"] == "Board Positions")
        self.assertEqual(section["aliases"], ["Advisory Roles"])
        self.assertTrue(section["optional"])

    def test_hybrid_certifications_is_optional_with_no_aliases(self):
        loaded = templates.load_cv_template("hybrid")
        section = next(s for s in loaded["sections"] if s["name"] == "Certifications")
        self.assertEqual(section["aliases"], [])
        self.assertTrue(section["optional"])

    def test_technical_work_experience_is_not_optional(self):
        loaded = templates.load_cv_template("technical")
        section = next(s for s in loaded["sections"] if s["name"] == "Work Experience")
        self.assertFalse(section["optional"])

    def test_unknown_name_raises_template_error(self):
        with self.assertRaises(templates.TemplateError):
            templates.load_cv_template("does-not-exist")

    def test_file_without_comment_block_raises_and_names_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "broken.md")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("# Not a template\n\nJust prose.\n")
            with unittest.mock.patch.object(templates, "_CV_DIR", tmp):
                with self.assertRaises(templates.TemplateError) as caught:
                    templates.load_cv_template("broken")
            self.assertIn(path, str(caught.exception))

    def test_malformed_sections_line_empty_name_names_the_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "broken.md")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "<!-- gaspol-jobhunter cv-template\n"
                    "name: broken\n"
                    "sections:\n"
                    "- | Something\n"
                    "-->\n"
                    "# <Full name>\n"
                )
            with unittest.mock.patch.object(templates, "_CV_DIR", tmp):
                with self.assertRaises(templates.TemplateError) as caught:
                    templates.load_cv_template("broken")
            self.assertIn(":4:", str(caught.exception))


class TestTemplateFilesRenderCleanly(unittest.TestCase):
    """Every template's own file, taken exactly as it sits on disk, must
    render through `pdf.render` with no refusal and no leak of the comment
    block's own machine-readable text — the thing Phase A's multi-line
    comment strip exists to guarantee for exactly this file shape."""

    def test_each_template_renders_with_no_refusal_and_no_leaked_comment(self):
        for name in CV_TEMPLATE_NAMES:
            with self.subTest(name=name):
                path = os.path.join(REPO_ROOT, "templates", "cv", "%s.md" % name)
                with open(path, "r", encoding="utf-8") as handle:
                    markdown = handle.read()
                with tempfile.TemporaryDirectory() as tmp:
                    out = os.path.join(tmp, "%s.pdf" % name)
                    # No refusal is the assertion: `pdf.render` raises on an
                    # unverified marker, an unsupported character, or an
                    # empty document, and this call must not.
                    pdf.render(markdown, out)
                    with open(out, "rb") as fh:
                        data = fh.read()
                # The rendered PDF is a binary stream with escaped text
                # operators — decoding permissively is enough to grep for
                # the two machine-readable words that must never appear.
                text = data.decode("latin-1")
                self.assertNotIn("sections:", text)
                self.assertNotIn("cv-template", text)


class TestTemplateHeadingsMatchDefinition(unittest.TestCase):
    """The file's own `## ` headings, read straight off disk, must equal
    `load_cv_template(name)["sections"]`'s canonical names in the same
    order — the file and its machine-readable definition cannot drift."""

    def test_headings_equal_canonical_section_names_in_order(self):
        for name in CV_TEMPLATE_NAMES:
            with self.subTest(name=name):
                loaded = templates.load_cv_template(name)
                expected = [section["name"] for section in loaded["sections"]]
                path = os.path.join(REPO_ROOT, "templates", "cv", "%s.md" % name)
                with open(path, "r", encoding="utf-8") as handle:
                    body = handle.read()
                found = _SECTION_HEADING_RE.findall(body)
                self.assertEqual(found, expected)


if __name__ == "__main__":
    unittest.main()

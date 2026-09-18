"""Structural tests for the plugin manifest and the six skill files.

These tests never judge skill *prose quality* (that is what the Phase G evals are
for) — they only enforce the mechanical contract Phase F's plan pins down:
`.claude-plugin/plugin.json` parses, every `skills/<name>/` directory has a
`SKILL.md` whose YAML front matter declares `name`/`description`, the declared
`name` matches its directory, nothing candidate-specific leaks into `skills/`,
and four specific hard rules are stated in prose (JD-reading is mandatory for
`tailor`, `outreach` has no send path, `profile` states the `verified: false`
suppression rule and the project allow-list rule).
"""

import json
import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_JSON = os.path.join(REPO_ROOT, ".claude-plugin", "plugin.json")
SKILLS_DIR = os.path.join(REPO_ROOT, "skills")

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.*?\n)---[ \t]*\n", re.DOTALL)
_FIELD_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):[ \t]*(.*)$")

# Mirrors the exact hard-rule grep from the plan:
#   grep -rniE "alisadikin|indusia|obsidian|Drive-D" skills/
_CANDIDATE_SPECIFIC_RE = re.compile(r"alisadikin|indusia|obsidian|drive-d", re.IGNORECASE)

_EXPECTED_SKILLS = frozenset(
    {"profile", "discover", "score", "promote", "tailor", "outreach"}
)


def _parse_front_matter(text):
    """Return a dict of the YAML front-matter's flat `key: value` fields, or
    `None` if `text` does not open with a `---` front-matter block.

    This is a deliberately minimal parser (no nested structures, no lists) —
    every field this project's SKILL.md front matter needs (`name`,
    `description`) is a single scalar line.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None
    fields = {}
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        field_match = _FIELD_RE.match(line)
        if not field_match:
            continue
        key, value = field_match.group(1), field_match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[key] = value
    return fields


def _skill_dirs():
    return sorted(
        name
        for name in os.listdir(SKILLS_DIR)
        if os.path.isdir(os.path.join(SKILLS_DIR, name))
    )


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class TestPluginJson(unittest.TestCase):
    def test_parses_and_has_required_fields(self):
        data = json.loads(_read(PLUGIN_JSON))
        self.assertEqual(data["name"], "ai-jobhunter")
        self.assertEqual(data["version"], "0.1.0")
        self.assertTrue(data.get("description"))
        self.assertTrue(data.get("keywords"))
        license_value = data.get("license")
        author = data.get("author")
        author_license = author.get("license") if isinstance(author, dict) else None
        self.assertIn("MIT", (license_value, author_license))
        self.assertTrue(author, "plugin.json must declare an author")


class TestSkillDirectories(unittest.TestCase):
    def test_expected_skill_directories_exist(self):
        self.assertEqual(set(_skill_dirs()), set(_EXPECTED_SKILLS))

    def test_every_skill_dir_has_skill_md(self):
        for name in _skill_dirs():
            skill_md = os.path.join(SKILLS_DIR, name, "SKILL.md")
            self.assertTrue(os.path.isfile(skill_md), f"missing SKILL.md for {name!r}")


class TestSkillFrontMatter(unittest.TestCase):
    def test_front_matter_declares_name_and_description(self):
        for name in _skill_dirs():
            text = _read(os.path.join(SKILLS_DIR, name, "SKILL.md"))
            fields = _parse_front_matter(text)
            self.assertIsNotNone(fields, f"{name}: no YAML front-matter block found")
            self.assertIn("name", fields, f"{name}: front matter missing 'name'")
            self.assertIn(
                "description", fields, f"{name}: front matter missing 'description'"
            )
            self.assertTrue(fields["name"].strip(), f"{name}: empty 'name'")
            self.assertTrue(fields["description"].strip(), f"{name}: empty 'description'")

    def test_declared_name_matches_directory(self):
        for name in _skill_dirs():
            text = _read(os.path.join(SKILLS_DIR, name, "SKILL.md"))
            fields = _parse_front_matter(text)
            self.assertEqual(fields["name"], name)


class TestNoCandidateSpecificContent(unittest.TestCase):
    def test_no_candidate_specific_strings_under_skills(self):
        offenders = []
        for root, _dirs, files in os.walk(SKILLS_DIR):
            for fname in files:
                path = os.path.join(root, fname)
                text = _read(path)
                if _CANDIDATE_SPECIFIC_RE.search(text):
                    offenders.append(os.path.relpath(path, REPO_ROOT))
        self.assertEqual(offenders, [], f"candidate-specific strings found in: {offenders}")


class TestNamedHardRulesInProse(unittest.TestCase):
    def test_tailor_states_jd_reading_is_mandatory_and_cv_never_sent_as_is(self):
        text = _read(os.path.join(SKILLS_DIR, "tailor", "SKILL.md")).lower()
        self.assertIn("mandatory", text)
        self.assertIn("master-cv.md", text)
        self.assertIn("never sent as-is", text)

    def test_outreach_states_no_send_path(self):
        text = _read(os.path.join(SKILLS_DIR, "outreach", "SKILL.md"))
        lowered = text.lower()
        self.assertIn("draft", lowered)
        self.assertIn("no send path", lowered)
        # Belt and braces: no literal send-style MCP tool name should appear.
        self.assertNotRegex(lowered, r"\bsend[_-]?(email|message|mail)\b")

    def test_profile_states_verified_false_rule_and_allow_list_rule(self):
        text = _read(os.path.join(SKILLS_DIR, "profile", "SKILL.md")).lower()
        self.assertIn("verified: false", text)
        self.assertIn("allow-list", text)


if __name__ == "__main__":
    unittest.main()

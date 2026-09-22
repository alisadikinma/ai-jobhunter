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
import pathlib
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_JSON = os.path.join(REPO_ROOT, ".claude-plugin", "plugin.json")
SKILLS_DIR = os.path.join(REPO_ROOT, "skills")

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.*?\n)---[ \t]*\n", re.DOTALL)
_FIELD_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):[ \t]*(.*)$")

# Mirrors the exact hard-rule grep from the plan:
#   grep -rniE "alisadikin|indusia|obsidian|Drive-D" skills/
# "sadikin" was added during AJOB-3 verifier round 1: the plugin author's
# real surname reached tests/ and scripts/ written as "Ali Sadikin" (a space
# between given name and surname), which "alisadikin" — one unbroken word —
# never matched.
_CANDIDATE_SPECIFIC_RE = re.compile(
    r"alisadikin|sadikin|indusia|obsidian|drive-d", re.IGNORECASE
)

# tests/test_manifest.py itself is excluded from the scan below — it has to
# hold the pattern (in the comment above and in the regex literal itself) to
# define it, and neither occurrence is a leak.
_MANIFEST_TEST_PATH = os.path.abspath(__file__)
_EXTRA_SCAN_ROOTS = ("tests", "scripts", os.path.join("docs", "evals"), "templates")

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
        self.assertEqual(data["name"], "gaspol-jobhunter")
        self.assertEqual(data["version"], "0.3.0")
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


class TestNoCandidateSpecificContentBeyondSkills(unittest.TestCase):
    """`TestNoCandidateSpecificContent` above only ever walked `skills/` —
    nothing stopped a real candidate's name from sitting in a test fixture
    or a script's own comment. AJOB-3 verifier round 1 found "Ali Sadikin"
    written out in tests/test_cli.py, tests/test_docx.py, tests/test_pdf.py,
    and two comments in scripts/docx.py explaining a markdown-parsing bug
    with the author's own name as the example. This widens the same regex
    to tests/, scripts/ and docs/evals/ — everywhere but this file itself,
    which has to hold the pattern to define it.
    """

    def test_no_candidate_specific_strings_outside_skills(self):
        offenders = []
        scanned = {}

        def _raise(error):
            raise error

        for rel_root in _EXTRA_SCAN_ROOTS:
            root_dir = os.path.join(REPO_ROOT, rel_root)
            # `os.walk` on a missing directory yields nothing and the guard
            # reports clean on a tree it never saw — the AJOB-1 fail-open.
            # Hence the explicit isdir, `onerror` that raises, and a count.
            self.assertTrue(os.path.isdir(root_dir), f"scan root missing: {rel_root}")
            scanned[rel_root] = 0
            for root, dirs, files in os.walk(root_dir, onerror=_raise):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for fname in files:
                    path = os.path.join(root, fname)
                    if os.path.abspath(path) == _MANIFEST_TEST_PATH:
                        continue
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            text = f.read()
                    except (UnicodeDecodeError, OSError):
                        continue  # a binary fixture (e.g. the sample .docx)
                    scanned[rel_root] += 1
                    if _CANDIDATE_SPECIFIC_RE.search(text):
                        offenders.append(os.path.relpath(path, REPO_ROOT))
        for rel_root, count in scanned.items():
            self.assertGreater(count, 0, f"guard read no file under {rel_root}")
        self.assertEqual(
            offenders, [], f"candidate-specific strings found in: {offenders}"
        )


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

    def test_profile_states_pdf_in_any_tier_uses_xberg(self):
        """AJOB-3 Phase F: a `.pdf` source in ANY tier — not just linkedin-pdf
        — is extracted with `mcp__xberg__extract_file`. The three fragments
        must appear together in the same paragraph, not just somewhere in the
        file, so the rule reads as one sentence rather than three unrelated
        mentions."""
        text = _read(os.path.join(SKILLS_DIR, "profile", "SKILL.md")).lower()
        paragraphs = text.split("\n\n")
        matches = [
            p
            for p in paragraphs
            if "mcp__xberg__extract_file" in p and "any tier" in p and ".pdf" in p
        ]
        self.assertTrue(
            matches,
            "no paragraph in profile/SKILL.md states the any-tier .pdf -> "
            "mcp__xberg__extract_file rule",
        )

    def test_tailor_states_agreement_gate(self):
        """AJOB-3 Phase G: tailor must name the requirements map, the
        `approved:` line, the pasted-JD file, `render-pdf`, and state plainly
        that no CV or cover letter is written before every row is agreed."""
        text = _read(os.path.join(SKILLS_DIR, "tailor", "SKILL.md")).lower()
        self.assertIn("requirements-map.md", text)
        self.assertIn("approved:", text)
        self.assertIn("jd.md", text)
        self.assertIn("render-pdf", text)
        self.assertIn("no cv.md or cover-letter.md is written until", text)

    def test_tailor_states_the_quantified_metric_preference_and_table_flattening(self):
        """AJOB-3 verifier round 1: the AJOB-2 tailor SKILL.md had two rules
        this rewrite dropped — "prefer bullets carrying a quantified metric"
        (a selection rule) and the explanation of what `render-pdf` flattens
        (tables to one bullet per row, keeping each cell's header). Both must
        be back, in words a reader would actually recognise."""
        text = _read(os.path.join(SKILLS_DIR, "tailor", "SKILL.md")).lower()
        self.assertIn("quantified metric", text)
        # A bare "table" matched "stable across re-runs" and passed with the
        # whole flattening paragraph deleted. Whitespace is collapsed first
        # because the prose wraps mid-phrase.
        prose = " ".join(text.split())
        self.assertIn("a table becomes one bullet per row", prose)
        self.assertIn("every cell keeping its own header", prose)

    def test_tailor_renders_docx_only_for_enterprise_portals(self):
        """AJOB-4 reverses AJOB-3's blanket ban: `render-docx` is back in
        tailor's SKILL.md, but only inside the portal-detection / render
        prose that names it as an enterprise-portal thing, alongside the
        word "enterprise" — not a bare, unconditional call."""
        text = _read(os.path.join(SKILLS_DIR, "tailor", "SKILL.md")).lower()
        self.assertIn("render-docx", text)
        # EVERY paragraph naming it, not just one: "some paragraph pairs them"
        # stayed green with an unconditional render-docx paragraph added
        # beside the conditional one (plan-verifier round 1).
        unconditional = [
            p
            for p in text.split("\n\n")
            if "render-docx" in p and "enterprise" not in p
        ]
        self.assertEqual(
            unconditional,
            [],
            "tailor/SKILL.md names 'render-docx' without 'enterprise'",
        )

    def test_tailor_states_templates_and_letter_format(self):
        """AJOB-4 Phase F: tailor must name the CV templates directory, the
        fixed cover-letter format, the deterministic check, portal detection
        (never guessed), the letter level, and that no personal detail is
        invented when the user gives none."""
        text = _read(os.path.join(SKILLS_DIR, "tailor", "SKILL.md")).lower()
        prose = " ".join(text.split())
        for fragment in (
            "templates/cv/",
            "templates/cover-letter.md",
            "template-check",
            "myworkdayjobs.com",
            "taleo.net",
            "icims.com",
            # The portal sentence itself: a bare "never guess" also matched
            # the AJOB-3 "never guesses a company or title" line, so deleting
            # the portal rule left this test green.
            "never guess one from the company name",
            "letter-level:",
            "template:",
            "portal:",
            "nothing is invented",
            "render-docx",
        ):
            self.assertIn(fragment, prose, f"tailor/SKILL.md is missing {fragment!r}")

    def test_tailor_states_the_universal_cv_and_letter_rules(self):
        """Spec §3 puts the universal CV rules "into every template and into
        `tailor`", and §4 the two letter prohibitions; plan-verifier round 1
        found tailor carrying none of them."""
        text = _read(os.path.join(SKILLS_DIR, "tailor", "SKILL.md")).lower()
        prose = " ".join(text.split())
        for fragment in (
            "directly under the name",
            "header or footer",
            "mon yyyy – mon yyyy",
            "`present`",
            "action verb",
            "no first-person pronouns",
            "1 page under about 10 years",
            "work authorization is stated only if the user supplies it",
            "never restates the cv bullet list",
            "what the job would do for the candidate",
        ):
            self.assertIn(fragment, prose, f"tailor/SKILL.md is missing {fragment!r}")

    def test_tailor_section_order_comes_from_the_template_not_the_variant(self):
        """The AJOB-3 line "let that variant's framing ... shape the summary
        and section ordering" contradicted the template rule next to it."""
        text = _read(os.path.join(SKILLS_DIR, "tailor", "SKILL.md")).lower()
        prose = " ".join(text.split())
        self.assertNotIn("summary and section ordering", prose)


class TestSkillsNameARunnableEntrypoint(unittest.TestCase):
    """Before `scripts/jobhunter.py` existed, the skills named Python
    functions and nothing in the repository said how to reach them. The only
    code that knew was the test suite's own `sys.path.insert`.
    """

    def test_the_cli_exists_and_is_importable_as_a_module(self):
        cli = pathlib.Path(REPO_ROOT) / "scripts" / "jobhunter.py"
        self.assertTrue(cli.is_file())
        self.assertIn('if __name__ == "__main__":', cli.read_text())

    def test_every_skill_names_the_plugin_root_variable(self):
        for skill_md in sorted(pathlib.Path(SKILLS_DIR).glob("*/SKILL.md")):
            self.assertIn(
                "CLAUDE_PLUGIN_ROOT",
                skill_md.read_text(),
                f"{skill_md.parent.name} gives no runnable command",
            )

    def test_no_skill_hardcodes_an_absolute_path(self):
        for skill_md in sorted(pathlib.Path(SKILLS_DIR).glob("*/SKILL.md")):
            text = skill_md.read_text()
            self.assertNotIn("/Users/", text, skill_md.parent.name)
            self.assertNotIn("/home/", text, skill_md.parent.name)

    def _cli_help(self, *args):
        import subprocess
        import sys

        return subprocess.run(
            [sys.executable, str(pathlib.Path(REPO_ROOT) / "scripts" / "jobhunter.py")]
            + list(args)
            + ["--help"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    # The path is quoted in the skills, so splitting on whitespace made
    # parts[0] the closing quote and every documented name an empty string.
    # The set was {""}, assertTrue passed on a non-empty set and
    # assertIn("", help_text) passed trivially — a guard that would have
    # accepted a completely fictional subcommand.
    # Two ways a skill names a command, and the guard has to read both.
    #
    # A fenced block anchors on the script path:
    #     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" queue-list \\
    #       --queue .jobhunter/queue/jobs.jsonl --unscored
    #
    # Prose names it in backticks, with no path at all:
    #     `queue-list --unpromoted`: a row already in jobsync costs two requests
    #
    # Anchoring only on `jobhunter.py` left the second style unread, and
    # `--unpromoted` — the flag the previous round used as its own mutation
    # subject — is documented ONLY that way. Typos planted in both prose
    # mentions left the suite green.
    # `_` belongs in the name class even though no subcommand uses one
    # today: the help-text parse reads underscores, so a documented
    # `queue_purge` would otherwise be invisible to BOTH documentation
    # patterns and never asserted against the CLI at all — the parse side
    # and the documentation side disagreeing about what a name may contain.
    _FENCED_RE = re.compile(r'jobhunter\.py"?\s+([a-z][a-z0-9_-]+)(.*)')
    _INLINE_RE = re.compile(r"`([a-z][a-z0-9_-]+)((?:\s+--?[a-z][a-z0-9-]*[^`]*?)?)`")

    # The tail captures the REST of the logical line, not a run of adjacent
    # flags: `--queue .jobhunter/queue/jobs.jsonl --unscored` puts a value
    # between the two flags, so a repetition group stops after the first one
    # and collected exactly one flag per command. But "rest of the line"
    # over-reads once a shell operator appears — `… --queue q.jsonl | jq
    # --raw-output` attributed `--raw-output` to `queue-list`. No current
    # SKILL.md does that, and over-capture can only ADD a false assertion,
    # never drop a real one; still, piping a board to `jq` is an obvious
    # future edit and it would fail the build for no reason.
    #
    # `>` is deliberately NOT a stop character. Including it cut the tail at
    # the placeholder `<slug>`, silently dropping `--dest` and `--company`
    # from `ats-fetch` — trading one blind spot for another. A redirection
    # introduces no flags, so there is nothing to stop for.
    _TAIL_END_RE = re.compile(r"[|`]|(?<=\s)#")

    @staticmethod
    def _join_continuations(text):
        """Fold shell backslash-continuations into single logical lines.

        Scanning raw lines collected ZERO flags, because every real command
        block in every SKILL.md is written across continuations:

            python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jobhunter.py" queue-list \\
              --queue .jobhunter/queue/jobs.jsonl --unscored

        A line-scoped regex sees the subcommand on one line and the flags on
        the next, so `for flag in flags` never ran a single assertion. The
        mutation test that "proved" the guard put its typo on the same line
        as the subcommand — the one style no skill actually uses. That is
        the same defect this guard was written to catch, one level down.
        """
        return re.sub(r"\\\s*\n\s*", " ", text)

    @classmethod
    def _flags_in(cls, tail):
        """Long flags in `tail`, stopping at the first shell operator."""
        stop = cls._TAIL_END_RE.search(tail)
        if stop:
            tail = tail[: stop.start()]
        return re.findall(r"--[a-z][a-z0-9-]*", tail)

    def _documented_commands(self):
        """Map each documented subcommand to the long flags shown with it.

        Out of scope by design: a flag written in its OWN backtick span, with
        no subcommand beside it — `skills/tailor/SKILL.md:112` says "`--top N`
        changes the cut". There is no pair to assert, so misspelling it there
        stays green. This is a limit of the pair model, recorded here so the
        next audit does not rediscover it as a defect.

        Only names that are real subcommands are kept from the inline form:
        prose is full of backticked identifiers, and every one of them would
        otherwise be asserted to exist in the CLI.
        """
        # The inline branch used to drop every name the CLI does not already
        # know, so a fictional `queue-purge` named in prose could never fail
        # the subcommand test — the filter could only confirm names that
        # existed. Requiring a hyphen AND a long flag right after keeps the 19
        # ordinary backticked prose identifiers out (`batches`, `skipped`,
        # `refused`, `linkedin-pdf`, …) while letting a wrong command name
        # through to be asserted against the CLI.
        real = set(self._cli_subcommands())
        commands = {}
        for skill_md in sorted(pathlib.Path(SKILLS_DIR).glob("*/SKILL.md")):
            joined = self._join_continuations(skill_md.read_text())
            for line in joined.splitlines():
                for match in self._FENCED_RE.finditer(line):
                    name, tail = match.group(1), match.group(2)
                    commands.setdefault(name, set()).update(self._flags_in(tail))
                for match in self._INLINE_RE.finditer(line):
                    name, tail = match.group(1), match.group(2)
                    separated = "-" in name or "_" in name
                    looks_like_a_command = separated and tail.lstrip().startswith("--")
                    if name not in real and not looks_like_a_command:
                        continue
                    commands.setdefault(name, set()).update(self._flags_in(tail))
        return commands

    def _cli_subcommands(self):
        """The subcommand names argparse itself reports, parsed from --help.

        Identified by the ` ...` trailer that argparse puts after the
        subparser metavar.

        Not quite "and after nothing else": a TOP-LEVEL argument combining
        `choices` with `nargs` in `('*', '+')` renders its own `{...} ...`
        group, and it lands before the subparser metavar, so leftmost-match
        takes it:

            usage: jobhunter [-h] [--tag [{remote,onsite} ...]] {…} ...
            -> 'remote,onsite'

        Left as a known limit rather than fixed. Driven end to end with that
        return value forced, coverage was byte-identical — 8 commands, 18
        flags — because the only consumer of this list is the `name not in
        real` half of a condition whose other half already rescues every
        flag-bearing mention. A wrong list can drop the existence check for a
        name that is already correct; it cannot let a documentation error
        ship. This CLI also has no top-level arguments besides `-h`.

        Two earlier attempts both degraded SILENTLY, which is worth writing
        down because the shape keeps recurring. Searching for the first
        lowercase braced token matched a `choices` metavar instead — and
        anchoring that search with `^...re.S` fixed nothing, because `^`
        without `re.M` binds to offset 0 and `.*?` then crosses every
        newline, so the "anchor" only required the text to begin with
        `usage:`. Worse, widening the class to `[^}]+` removed an accidental
        filter: `[a-z0-9,-]` had been rejecting uppercase metavars, so that
        attempt broke a case the naive version got right. Measured against
        real `argparse` output:

            option present        first-token   ^...re.S    ` ...` trailer
            (none, today)         correct       correct     correct
            --mode {fast,slow}    WRONG         WRONG       correct
            --format {JSON,CSV}   correct       WRONG       correct

        A guard that goes quiet instead of failing is this ticket's own
        recurring defect, so the parse fails loudly or not at all.
        `assertTrue`, not a bare `assert`, because `python3 -O` strips the
        latter and a stripped check is the same silence by another route.
        """
        help_text = self._cli_help()
        match = re.search(r"\{([^{}]+)\}\s*\.\.\.", help_text)
        self.assertTrue(
            match, f"could not read the subcommand list out of:\n{help_text}"
        )
        return match.group(1).split(",")

    def test_render_pdf_and_all_four_of_its_flags_are_collected(self):
        """The guard must actually SEE the newest command, not just pass.

        This guard was twice found vacuous during AJOB-1 — checking zero of
        eighteen flags while staying green — so a new subcommand asserts its
        own collection rather than trusting that the general test covers it.
        AJOB-3 replaces `render-docx` here because `tailor` (the only skill
        that used to document it) now documents `render-pdf` instead;
        `render-docx` stays a real CLI subcommand and keeps its own tests in
        test_docx.py / test_cli.py, it is just no longer skill-documented.
        """
        commands = self._documented_commands()
        self.assertIn("render-pdf", commands)
        self.assertEqual(
            commands["render-pdf"],
            {"--in", "--out", "--page", "--allow-unverified"},
        )

    def test_template_check_and_all_six_of_its_flags_are_collected(self):
        """Same reasoning as `test_render_pdf_and_all_four_of_its_flags_are_
        collected` above, one ticket later: AJOB-4's newest subcommand must
        actually be seen by the guard, across its two documented command
        blocks (one for `--cv`/`--template`, one for `--letter`/`--level`/
        `--company`/`--role`) in `tailor/SKILL.md`."""
        commands = self._documented_commands()
        self.assertIn("template-check", commands)
        self.assertEqual(
            commands["template-check"],
            {"--cv", "--template", "--letter", "--level", "--company", "--role"},
        )

    def test_every_documented_subcommand_exists_in_the_cli(self):
        help_text = self._cli_help()
        documented = self._documented_commands()
        self.assertTrue(documented, "no skill documents a subcommand")
        self.assertNotIn("", documented)
        for name in sorted(documented):
            self.assertIn(
                name,
                help_text,
                f"{name} is documented in a skill but is not a real subcommand",
            )

    def test_every_documented_flag_exists_on_its_subcommand(self):
        """Names alone were guarded, so a typo like `--unpromted` stayed
        green — the same class of silent miss as the quoting bug above, one
        level down. Checks each flag against that subcommand's own --help.
        """
        for name, flags in sorted(self._documented_commands().items()):
            sub_help = self._cli_help(name)
            for flag in sorted(flags):
                self.assertIn(
                    flag,
                    sub_help,
                    f"{name} {flag} is documented in a skill but "
                    f"{name} accepts no such flag",
                )


class TestConfigTemplateMatchesTheSpec(unittest.TestCase):
    """`templates/config.toml` and the spec's §4 block are the same text.

    The plan instructs "write templates/config.toml containing the commented
    example from spec §4 verbatim", and the plan now embeds it too. Three
    copies of one contract drift, and a config key documented in one place
    and absent from another is exactly the kind of gap four review rounds
    kept finding by hand. This checks it in 3 milliseconds.
    """

    def _template(self):
        path = pathlib.Path(REPO_ROOT) / "templates" / "config.toml"
        return path.read_text().strip()

    def _toml_blocks(self, path):
        text = pathlib.Path(path).read_text()
        return [
            block.strip()
            for block in re.findall(r"```toml\n(.*?)```", text, re.S)
            if "profile_sources" in block
        ]

    def _blocks_of_the_one_document_carrying_them(self, pattern):
        """The TOML blocks of the single doc matching `pattern` that has any.

        Selecting on "exactly one file matching the glob" was wrong the
        moment a second ticket landed its own plan: the config template
        lives in AJOB-1's documents, and later tickets' plans carry no TOML
        block at all, so the count assertion fired on a repo that had not
        drifted. `glob(...).__next__()` would have been worse — a bare
        `StopIteration` on zero matches, and whichever file sorts first on
        two, which is how this guard would silently check the wrong
        document while staying green.

        The "exactly one" guarantee still holds, but over the copies of the
        contract rather than over the number of tickets the repo has had.
        Zero matches fail too: a deleted block is drift, not absence of it.
        """
        matches = [
            (path, blocks)
            for path in sorted(pathlib.Path(REPO_ROOT).glob(pattern))
            if (blocks := self._toml_blocks(path))
        ]
        self.assertEqual(
            len(matches),
            1,
            f"expected exactly one {pattern} carrying a profile_sources TOML "
            f"block, found {len(matches)}: {[str(path) for path, _ in matches]}",
        )
        return matches[0][1]

    def test_the_spec_carries_the_template_verbatim(self):
        blocks = self._blocks_of_the_one_document_carrying_them(
            "docs/plans/*-spec.md"
        )
        self.assertIn(
            self._template(),
            blocks,
            "templates/config.toml and the spec's §4 TOML block have drifted",
        )

    def test_the_plan_carries_the_template_verbatim(self):
        blocks = self._blocks_of_the_one_document_carrying_them(
            "docs/plans/*-plan.md"
        )
        self.assertIn(
            self._template(),
            blocks,
            "templates/config.toml and the plan's embedded copy have drifted",
        )


if __name__ == "__main__":
    unittest.main()


class TestGitignore(unittest.TestCase):
    def test_data_dir_is_ignored(self):
        """`data/` is where a user drops their own CV PDF. This repo is public,
        so one `git add .` would publish a real person's CV."""
        lines = _read(os.path.join(REPO_ROOT, ".gitignore")).splitlines()
        self.assertIn("data/", [line.strip() for line in lines])


class TestClaudeMdNamesEverySubcommand(unittest.TestCase):
    def test_subcommands_line_matches_the_cli(self):
        """CLAUDE.md is the first file a new session reads. A subcommand it
        does not list is one that session will not know to reach for."""
        text = _read(os.path.join(REPO_ROOT, "CLAUDE.md"))
        match = re.search(r"^Subcommands:(.*?)\.\n", text, re.M | re.S)
        self.assertTrue(match, "CLAUDE.md has no 'Subcommands:' line")
        listed = set(re.findall(r"`([a-z-]+)`", match.group(1)))
        cli = set(TestSkillsNameARunnableEntrypoint()._cli_subcommands())
        self.assertEqual(listed, cli)

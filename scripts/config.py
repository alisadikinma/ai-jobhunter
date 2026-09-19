"""Load `.jobhunter/config.toml` and resolve profile source precedence.

The config file lives in the user's own project (never inside this repo —
see `.gitignore`). This module only deals with an arbitrary `path` passed in
by the caller; it never assumes or creates that default location itself.

## `min_salary_usd` — the "unset" representation

An absent `targets.min_salary_usd` key and a literal `0` both mean "no salary
floor configured" (spec §4: "0 means unset, not 'pays zero'"). A real floor
of USD 0 is not a value anyone would configure, but leaving `0` as the
in-memory sentinel would still let a future caller write
`if cfg["targets"]["min_salary_usd"]:` and get it right by accident while a
caller who writes `if cfg["targets"]["min_salary_usd"] is not None:` gets it
wrong — the two spellings disagree.

To remove that ambiguity, `load()` normalises both "absent" and `0` to the
Python singleton `None` in the returned dict. `None` cannot be confused with
a real floor (any real floor is a positive int), so every caller can use the
single, unambiguous test `cfg["targets"]["min_salary_usd"] is None` to mean
"no floor configured" and never has to special-case `0`.
"""

import os
import tomllib
import warnings

TOML_DECODE_ERROR = tomllib.TOMLDecodeError

_KNOWN_TOP_LEVEL_KEYS = frozenset({"profile_sources", "targets", "budgets", "tracking"})

_BUDGET_DEFAULTS = {
    "firecrawl_credits_per_run": 150,
    "jobsync_requests_per_run": 50,
}

# tier name (as it appears in profile_sources.precedence) -> how to resolve
# it to a list of (tier, path_or_url) entries. "project" is handled
# separately by resolve_profile_sources because it needs the allow-list
# validation; every other tier here just reads one or more fields.
_TIER_FIELD_MAP = {
    "local-primary": ("single", "primary"),
    "local": ("list", "local"),
    "linkedin-pdf": ("single", "linkedin_pdf"),
    "site": ("list", "sites"),
}


class ConfigError(Exception):
    """Base class for all config-loading errors."""


class ConfigMissingError(ConfigError):
    """Raised when `.jobhunter/config.toml` does not exist."""


class ProjectSourceError(ConfigError):
    """Raised when `profile_sources.projects.allowed` names something unsafe
    or something that does not exist on disk."""


class PrecedenceError(ConfigError):
    """A `profile_sources.precedence` entry names no known tier."""


class BudgetTypeError(ConfigError):
    """A budget value is not a non-negative whole number."""


class SalaryTypeError(ConfigError):
    """`targets.min_salary_usd` is not a non-negative whole number."""


def _is_url(value):
    return "://" in value


def _resolve_path(base_dir, value):
    """Resolve a relative filesystem path against `base_dir`.

    URLs (containing `://`) and already-absolute paths pass through
    unchanged. `base_dir` is the directory containing the config file
    itself, never the process's current working directory.
    """
    if not value:
        return value
    if _is_url(value):
        return value
    if os.path.isabs(value):
        return value
    return os.path.normpath(os.path.join(base_dir, value))


def _normalize_min_salary(raw_targets, provenance):
    """Fold absent-or-0 into `None`; a positive int stays a real floor."""
    if "min_salary_usd" not in raw_targets:
        provenance["targets.min_salary_usd"] = "default"
        return None
    value = raw_targets["min_salary_usd"]
    provenance["targets.min_salary_usd"] = "file"
    # Same reasoning as the budgets: a quoted number in TOML is a string and
    # would compare wrongly against a real salary rather than failing.
    if isinstance(value, bool) or not isinstance(value, int):
        raise SalaryTypeError(
            f"targets.min_salary_usd must be a whole number, got {value!r} "
            f"({type(value).__name__})."
        )
    if value < 0:
        raise SalaryTypeError(
            f"targets.min_salary_usd must not be negative, got {value!r}."
        )
    if value == 0:
        return None
    return value


_KNOWN_TARGET_KEYS = frozenset({"geo", "companies", "min_salary_usd"})
_KNOWN_PROFILE_SOURCE_KEYS = frozenset(
    {"sites", "linkedin_pdf", "local", "precedence", "primary", "projects"}
)
_KNOWN_PROJECT_KEYS = frozenset({"root", "allowed"})
_KNOWN_TRACKING_KEYS = frozenset({"jobsync_mcp"})


def _warn_unknown_section_keys(section_name, raw_section, known):
    """A typo inside a section used to fail silently.

    `precedance = [...]` left `precedence` empty, `resolve_profile_sources`
    returned nothing, and the profile compiled from zero sources without an
    error anywhere — the same fail-open shape `PrecedenceError` exists to
    prevent one level up.
    """
    for key in raw_section:
        if key not in known:
            warnings.warn(
                f"Unknown key {key!r} in [{section_name}] — it will be ignored. "
                f"Known keys: {', '.join(sorted(known))}.",
                stacklevel=3,
            )


def _require_budget_int(name, value):
    """Budgets are spent, so they must be numbers before anything spends them.

    TOML makes `150` and `"150"` easy to confuse, and a string reaches
    `plan_budget` as a string and compares wrongly rather than failing. Catch
    it at the boundary, where the file name and key are still in hand.
    `bool` is excluded deliberately: `True` is an `int` in Python and a budget
    of `True` is a typo, not a ceiling of one.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise BudgetTypeError(
            f"budgets.{name} must be a whole number, got {value!r} "
            f"({type(value).__name__}). Quote marks around a number in TOML "
            "make it a string."
        )
    if value < 0:
        raise BudgetTypeError(f"budgets.{name} must not be negative, got {value!r}.")
    return value


def load(path):
    """Read `path` as TOML and return a dict with every default filled in.

    Raises `ConfigMissingError` if `path` does not exist, and lets
    `tomllib.TOMLDecodeError` propagate unmodified for malformed TOML (it is
    never caught and swallowed here). An unknown top-level key triggers a
    `UserWarning` but does not fail the load.

    Relative filesystem paths inside `profile_sources` (`linkedin_pdf`,
    `primary`, entries of `local`, `projects.root`) are resolved against the
    directory containing `path`, not the process's current working
    directory.

    The returned dict carries a `_provenance` key mapping each dotted config
    key to `"file"` or `"default"`, so a caller can report which values came
    from the file and which were filled in.
    """
    if not os.path.exists(path):
        raise ConfigMissingError(
            f"No config file at {path}. Run /ai-jobhunter:profile to create one."
        )

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    for key in raw:
        if key not in _KNOWN_TOP_LEVEL_KEYS:
            warnings.warn(f"Unknown top-level config key: {key!r}", stacklevel=2)

    base_dir = os.path.dirname(os.path.abspath(path))
    provenance = {}

    # budgets, with explicit defaults
    raw_budgets = raw.get("budgets", {})
    _warn_unknown_section_keys("budgets", raw_budgets, set(_BUDGET_DEFAULTS))
    budgets = {}
    for name, default in _BUDGET_DEFAULTS.items():
        if name in raw_budgets:
            budgets[name] = _require_budget_int(name, raw_budgets[name])
            provenance[f"budgets.{name}"] = "file"
        else:
            budgets[name] = default
            provenance[f"budgets.{name}"] = "default"

    # targets
    raw_targets = raw.get("targets", {})
    _warn_unknown_section_keys("targets", raw_targets, _KNOWN_TARGET_KEYS)
    targets = {
        "geo": raw_targets.get("geo", []),
        "companies": raw_targets.get("companies", []),
        "min_salary_usd": _normalize_min_salary(raw_targets, provenance),
    }
    provenance.setdefault("targets.geo", "file" if "geo" in raw_targets else "default")
    provenance.setdefault(
        "targets.companies", "file" if "companies" in raw_targets else "default"
    )

    # profile_sources
    raw_ps = raw.get("profile_sources", {})
    _warn_unknown_section_keys("profile_sources", raw_ps, _KNOWN_PROFILE_SOURCE_KEYS)
    # Nested tables need the same warning. `alowed = [...]` left `allowed`
    # empty, which made even the "allowed without root" guard stay quiet
    # (an empty list is falsy), so the profile compiled from zero project
    # sources with nothing said anywhere.
    _warn_unknown_section_keys(
        "profile_sources.projects", raw_ps.get("projects", {}), _KNOWN_PROJECT_KEYS
    )
    _warn_unknown_section_keys("tracking", raw.get("tracking", {}), _KNOWN_TRACKING_KEYS)
    raw_projects = raw_ps.get("projects", {})
    profile_sources = {
        "sites": list(raw_ps.get("sites", [])),
        "linkedin_pdf": _resolve_path(base_dir, raw_ps.get("linkedin_pdf")),
        "local": [_resolve_path(base_dir, p) for p in raw_ps.get("local", [])],
        "precedence": list(raw_ps.get("precedence", [])),
        "primary": _resolve_path(base_dir, raw_ps.get("primary")),
        "projects": {
            "root": _resolve_path(base_dir, raw_projects.get("root")),
            "allowed": list(raw_projects.get("allowed", [])),
        },
    }
    provenance["profile_sources.linkedin_pdf"] = (
        "file" if "linkedin_pdf" in raw_ps else "default"
    )

    # tracking
    tracking = dict(raw.get("tracking", {}))

    cfg = {
        "budgets": budgets,
        "targets": targets,
        "profile_sources": profile_sources,
        "tracking": tracking,
        "_provenance": provenance,
    }
    return cfg


def _reject_unsafe_name(name):
    """Reject anything that is not a plain directory name.

    This is a privacy control, not tidiness: an entry that resolves to the
    root itself turns the allow-list into "read everything", which is the one
    mode the design rules out. `"."` and `""` both did exactly that before
    this check existed — `os.path.join(root, ".")` is the root.
    """
    if not isinstance(name, str) or not name.strip():
        raise ProjectSourceError(
            f"profile_sources.projects.allowed entry is empty: {name!r}"
        )
    if os.path.isabs(name):
        raise ProjectSourceError(f"profile_sources.projects.allowed entry is absolute: {name!r}")
    if os.sep in name or (os.altsep and os.altsep in name) or "/" in name:
        raise ProjectSourceError(
            f"profile_sources.projects.allowed entry contains a path separator: {name!r}"
        )
    if ".." in name.split(os.sep) or ".." in name.split("/") or name == "..":
        raise ProjectSourceError(
            f"profile_sources.projects.allowed entry contains path traversal: {name!r}"
        )
    if os.path.normpath(name) in (".", "..", os.curdir, os.pardir):
        raise ProjectSourceError(
            f"profile_sources.projects.allowed entry resolves to the root itself: {name!r}"
        )


def _resolve_project_sources(cfg):
    """Allow-listed project directories only. The root is NEVER scanned.

    Every name in `profile_sources.projects.allowed` is validated (no `..`,
    no path separator, no absolute path) and checked to exist under
    `projects.root`. A name that fails validation or does not exist raises
    `ProjectSourceError` — it is never silently skipped, because an unlisted
    directory that goes missing without notice is exactly the failure mode
    this allow-list exists to prevent going unnoticed in the other
    direction (a directory quietly appearing would be silent too).
    """
    projects = cfg["profile_sources"]["projects"]
    root = projects.get("root")
    raw_allowed = projects.get("allowed") or []
    if not isinstance(raw_allowed, (list, tuple)):
        # Three ways to get this wrong, all of which used to fail badly:
        #   allowed = "notes"   exploded into ["n","o","t","e","s"] and
        #                       refused by naming a directory nobody wrote
        #   allowed = 5         TypeError: 'int' object is not iterable —
        #                       a crash wearing a refusal's clothes
        #   [profile_sources.projects.allowed]  a TOML TABLE, whose KEY NAMES
        #                       were then silently treated as directory names
        # The last is the dangerous one: it reads a directory the author
        # never listed, which is the whole thing the allow-list prevents.
        raise ProjectSourceError(
            "profile_sources.projects.allowed must be a list of directory "
            f"names, not {type(raw_allowed).__name__}: got {raw_allowed!r}. "
            'Write allowed = ["project-a", "project-b"].'
        )
    allowed = list(raw_allowed)

    if allowed and not (isinstance(root, str) and root.strip()):
        raise ProjectSourceError(
            "profile_sources.projects.allowed is set but projects.root is missing. "
            "Both are needed: root says where to look, allowed says which "
            "directories under it may be read."
        )

    entries = []
    for name in allowed:
        _reject_unsafe_name(name)
        full_path = os.path.join(root, name)
        if not os.path.isdir(full_path):
            raise ProjectSourceError(
                f"Allow-listed project directory does not exist: {full_path!r}"
            )
        _require_inside_root(root, full_path, name)
        _require_no_escaping_links(root, full_path, name)
        # Return the RESOLVED path. Handing back the unresolved one leaves the
        # containment guarantee behind: a reader could still traverse a link
        # swapped in afterwards, and nothing downstream could tell.
        entries.append(("project", os.path.realpath(full_path)))
    return entries


def _require_no_escaping_links(root, full_path, name):
    """Walk the allow-listed directory and refuse any link leading outside IT.

    Checking only the top-level entry protects one level. A symlink INSIDE an
    allow-listed directory — `projects/allowed/notes -> /client-work` — has an
    innocent name, is never inspected, and is followed by any ordinary walk.
    Measured: a file under such a link was read straight out of the
    allow-listed directory.

    Containment is measured against the allow-listed directory, NOT against
    the root. Measuring against the root was the fifth and sixth bypass: the
    allow-list's whole contract is that a directory under the root which was
    not named is unreadable, so a link that stays "inside the root" has
    escaped just as completely as one that leaves it. Both were measured
    reading a confidential file:

        allowed/archive -> ..          read root/client-acme-pricing/negotiation.md
        allowed/peek    -> ../client-work   read root/client-work/nda.md

    `..` in particular is a one-character escape with an innocent name, and
    the old guard whitelisted it explicitly (`target != real_root`).
    """
    real_entry = os.path.realpath(full_path)

    def _unreadable(exc):
        """Refuse rather than skip a subtree that cannot be enumerated.

        `os.walk`'s default `onerror=None` DISCARDS every `OSError` from
        `scandir`, so a directory the guard cannot list is a directory whose
        links are never inspected — and the function returns as though it had
        checked them. Measured with `allowed/sub` at mode 0o311 (traversable,
        not listable) holding `sub/out -> ../../client-work`: the guard said
        ALLOWED and the planted file was readable through the entry it
        returned. If the allow-listed directory itself is unlistable, the
        loop body never runs at all.

        A guard that goes quiet instead of failing is this ticket's own
        recurring defect, so an un-inspectable subtree is a refusal.
        """
        raise ProjectSourceError(
            f"Allow-listed project directory {name!r} contains something that "
            f"could not be inspected: {exc}. The allow-list cannot vouch for a "
            "subtree it was unable to read."
        ) from exc

    for dirpath, dirnames, filenames in os.walk(
        full_path, followlinks=False, onerror=_unreadable
    ):
        for entry in list(dirnames) + list(filenames):
            candidate = os.path.join(dirpath, entry)
            if not os.path.islink(candidate):
                continue
            target = os.path.realpath(candidate)
            if not _is_under(target, real_entry):
                raise ProjectSourceError(
                    f"Allow-listed project directory {name!r} contains a link "
                    f"leading outside it: {os.path.relpath(candidate, full_path)!r} "
                    f"resolves to {target!r}, which is not under {real_entry!r}. "
                    "Allow-listing a directory does not allow-list what its "
                    "links point at — not even somewhere else under the root."
                )


def _is_under(path, root):
    """True when `path` sits inside `root`.

    `root + os.sep` is wrong when root is `/`: the prefix becomes `//` and
    every real path fails it, so the error message claimed `/Users` is not
    under `/`. `os.path.commonpath` has no such edge.
    """
    if path == root:
        return True
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:  # different drives on Windows
        return False


def _require_inside_root(root, full_path, name):
    """Refuse an allow-listed name that is not the real directory of that name.

    Validating the NAME is not enough. A symlink in the root pointing at a
    client's directory has a perfectly innocent name, and allow-listing that
    name allow-lists whatever it points at — which is not what the person
    writing the config agreed to.

    "Resolves under the root" is too weak a test, and was the seventh bypass:
    `root/alias -> root/client-work` stays inside the root and still hands
    back a directory nobody allow-listed. Measured, it read
    `root/not-allowlisted/nda.md`. So the requirement is exact identity —
    `<root>/<name>` and nothing else. A directory reached through a link is a
    directory the config author did not name.
    """
    real_root = os.path.realpath(root)
    real_path = os.path.realpath(full_path)
    expected = os.path.join(real_root, name)
    if real_path != expected:
        raise ProjectSourceError(
            f"Allow-listed project directory {name!r} resolves to {real_path!r}, "
            f"not to {expected!r}. A symlink's name is allow-listed, but what it "
            "points at is not — including another directory under the same root, "
            "which was never allow-listed either."
        )


def resolve_profile_sources(cfg):
    """Return an ordered `[(tier, path_or_url), ...]` in configured precedence.

    Tiers come from `profile_sources.precedence`. Every tier except
    `"project"` reads directly from a `profile_sources` field (see
    `_TIER_FIELD_MAP`); `"project"` is resolved by `_resolve_project_sources`,
    which allow-lists directory names instead of scanning
    `profile_sources.projects.root`.

    An unknown tier name raises `PrecedenceError`. Resolving it to zero
    entries instead would mean a single typo silently drops a whole class of
    source from the profile, and the compiled CV would look complete while
    missing everything that tier held — the same fail-open shape the project
    allow-list exists to prevent. A tier that is known but has nothing
    configured contributes no entries, which is a different and legitimate
    state.
    """
    ps = cfg["profile_sources"]
    precedence = ps.get("precedence") or []

    ordered = []
    for tier in precedence:
        if tier == "project":
            ordered.extend(_resolve_project_sources(cfg))
            continue
        mapping = _TIER_FIELD_MAP.get(tier)
        if mapping is None:
            known = ", ".join(sorted(list(_TIER_FIELD_MAP) + ["project"]))
            raise PrecedenceError(
                f"Unknown precedence tier {tier!r} in profile_sources.precedence. "
                f"Known tiers: {known}."
            )
        kind, field = mapping
        if kind == "single":
            value = ps.get(field)
            if value:
                ordered.append((tier, value))
        else:
            for value in ps.get(field) or []:
                ordered.append((tier, value))
    return ordered

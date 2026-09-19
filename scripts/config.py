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
    if value == 0:
        return None
    return value


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
    allowed = projects.get("allowed") or []

    entries = []
    for name in allowed:
        _reject_unsafe_name(name)
        full_path = os.path.join(root, name)
        if not os.path.isdir(full_path):
            raise ProjectSourceError(
                f"Allow-listed project directory does not exist: {full_path!r}"
            )
        entries.append(("project", full_path))
    return entries


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

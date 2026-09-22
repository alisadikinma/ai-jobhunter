"""Read provider API keys from the process environment or a local .env file.

The environment always wins over the file, so a shell export overrides a
stale .env without editing it. Values are never echoed anywhere except the
one return of read_key() itself — key_status() reports presence only.
"""

import os


class EnvFileError(Exception):
    pass


def _find_in_env_file(env_file, name):
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key != name:
                continue
            if len(value) >= 2 and (
                (value[0] == '"' and value[-1] == '"')
                or (value[0] == "'" and value[-1] == "'")
            ):
                value = value[1:-1]
            if value:
                return value
    return None


def read_key(name, env_file=".env"):
    env_value = os.environ.get(name)
    if env_value is not None and env_value.strip():
        return env_value

    if not os.path.exists(env_file):
        return None

    try:
        return _find_in_env_file(env_file, name)
    except OSError as exc:
        raise EnvFileError(f"cannot read {env_file}: {exc.strerror}") from exc


def key_status(names, env_file=".env"):
    result = {}
    for name in names:
        try:
            value = read_key(name, env_file)
        except EnvFileError:
            value = None
        result[name] = "present" if value else "missing"
    result["env_file"] = (
        os.path.abspath(env_file) if os.path.exists(env_file) else "not found"
    )
    return result

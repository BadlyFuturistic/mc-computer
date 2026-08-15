"""Server configuration: defaults, and a migration that never clobbers your edits.

Deploying must not overwrite settings. But a new release often needs a key that an
existing config has never heard of, and silently falling back to a default leaves the
operator with no idea the setting exists. So `ensure()` appends missing keys with their
defaults and a comment, and touches nothing that is already there.

The file is root-owned: the bot reads it and cannot change it. Anything the bot is
allowed to change at runtime — the active persona, for instance — lives in memory.db
instead.
"""
import shutil
import time
from pathlib import Path

CONFIG = Path("/etc/mcbot/config")
LEGACY = Path("/etc/mcbot/limits")     # pre-0.5 name, still read if config is absent

# key -> (default, comment). Order is preserved when writing a fresh file.
DEFAULTS: dict[str, tuple[str, str]] = {
    "DAILY_USD_LIMIT": (
        "50",
        "Maximum model spend per day, in USD. Read fresh on every check, so a change\n"
        "# takes effect immediately with no restart.",
    ),
    "DEFAULT_PERSONA": (
        "computer",
        "Which file in /opt/mcbot/personas/ supplies the assistant's voice. The active\n"
        "# persona can be changed at runtime; this is what it falls back to.",
    ),
    "PLAYERS_CAN_CHANGE_PERSONA": (
        "true",
        "Whether any player may switch the persona, or only the admin.",
    ),
}


def read() -> dict[str, str]:
    """Current settings, with defaults filled in for anything missing."""
    values = {k: v[0] for k, v in DEFAULTS.items()}
    for path in (CONFIG, LEGACY):
        if not path.exists():
            continue
        try:
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                values[key.strip()] = val.strip()
        except (OSError, PermissionError):
            pass
        break
    return values


def get(key: str, default: str | None = None) -> str:
    return read().get(key, default if default is not None else DEFAULTS.get(key, ("",))[0])


def truthy(key: str) -> bool:
    return get(key).strip().lower() in ("1", "true", "yes", "on")


def ensure() -> list[str]:
    """Add any missing keys to the config, leaving existing values untouched.

    Returns the keys that were added. Run on deploy so a new setting shows up in the
    file — with its default and an explanation — rather than existing only in code.
    """
    CONFIG.parent.mkdir(parents=True, exist_ok=True)

    if not CONFIG.exists() and LEGACY.exists():
        # Carry the old limits file forward rather than stranding its value.
        shutil.copy2(LEGACY, CONFIG)

    existing = CONFIG.read_text() if CONFIG.exists() else ""
    present = {
        line.split("=", 1)[0].strip()
        for line in existing.splitlines()
        if line.strip() and not line.strip().startswith("#") and "=" in line
    }

    added, block = [], []
    for key, (value, comment) in DEFAULTS.items():
        if key in present:
            continue
        added.append(key)
        block.append(f"\n# {comment}\n{key}={value}\n")

    if not existing:
        header = ("# mc-computer configuration.\n"
                  "# Edited by hand; deploying adds new keys but never changes yours.\n")
        CONFIG.write_text(header + "".join(block))
    elif block:
        stamp = time.strftime("%Y-%m-%d")
        CONFIG.write_text(existing.rstrip("\n") + f"\n\n# Added by deploy on {stamp}:\n"
                          + "".join(block))
    return added


if __name__ == "__main__":
    new = ensure()
    print(f"config: added {', '.join(new)}" if new else "config: already up to date")

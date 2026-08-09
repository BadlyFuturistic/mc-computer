# Changelog

Versions are `0.x` while the interface is still moving. Each entry records the
Minecraft version it was developed and tested against, because several dependencies —
NBT syntax, log line formats, datapack layout — change between Minecraft versions and
fail *silently* rather than erroring.

## 0.2.0 — Minecraft 26.2 (NeoForge)

- Runs on the Minecraft host as a hardened systemd service rather than over SSH from a
  workstation. No Docker access; RCON is spoken directly over localhost.
- Persistent memory in SQLite: messages held for offline players, an activity log
  rolled up nightly, and backup health verdicts.
- Join/leave handling. A greeting waits for chunk loading, and a player who drops out
  first keeps their messages pending rather than losing them.
- Nightly backup health check, reported to the admin at their next login and
  summarised across nights rather than listed.
- `mcask`: terminal access through a forked session, sharing the live conversation and
  memory without interrupting in-game work.
- Countdown restarts tick every second for the final five.
- World-specific landmarks moved to a local lore file outside the repo.

## 0.1.0 — Minecraft 26.2 (NeoForge)

- Initial working assistant: chat handling, RCON tooling, structure catalog, safe
  teleports, backpack reading, location resolution.

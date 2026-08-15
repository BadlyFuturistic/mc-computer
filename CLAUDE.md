# mc-computer

An in-game assistant for a Minecraft server. This repo is edited on a workstation and
deployed to the Minecraft host. Nothing here runs locally.

## Deploying is two halves, and only one needs privilege

`./client/deploy.sh` installs `server/bin/` to `/opt/mc` needing no privilege, then
`server/mcbot/` to `/opt/mcbot` needing sudo and a TTY. A run without a terminal lands the
first half and silently skips the second, so the tools and the daemon end up at different
versions. Check with `mchealth` on the host rather than assuming.

## Reads and writes go to different places

- **Writes go through RCON.** Editing region files under a running server corrupts them.
- **Reads come from the region files** via `server/bin/region.py` — far faster than RCON,
  and able to answer "what block is this?", which RCON cannot.
- Region reads see the **last save**. Tools run `save-all flush` first. When verifying a
  change you just made, never pass `--no-flush`: you will read stale data and conclude the
  change failed.

## Things that fail silently

NBT syntax, log line formats, datapack layout, and the chunk format `region.py` decodes all
change between Minecraft versions, then report success while doing nothing. Read **Version
compatibility** in `README.md` before a Minecraft upgrade, and run
`mcblock <a block you can see> --verify` after one.

## Conventions

- Commit messages: imperative subject in sentence case, then prose explaining why the
  change exists and what failure it fixes. No bullet lists, no `feat:` prefixes.
- Bump `VERSION` and add a `CHANGELOG.md` entry for behaviour changes.
- Never commit secrets, `server/personas/frank.md`, or `server/mcbot/local-lore.md`.

Rules for writing the world-editing tools load from `.claude/rules/world-edit-tools.md`
when you open anything under `server/bin/`.

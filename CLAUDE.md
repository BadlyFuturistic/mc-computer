<!-- last-verified: 2026-08-15 -->

# mc-computer

An in-game assistant for a Minecraft server. Edit the repo on a workstation, then deploy
it to the Minecraft host. Nothing here runs on the workstation, so test a change by
deploying it and running it on the host.

## Deploying is two halves, and only one needs privilege

`./client/deploy.sh` installs `server/bin/` to `/opt/mc`, which needs no privilege. It
then installs `server/mcbot/` to `/opt/mcbot`, which needs sudo and a TTY. A run without a
terminal lands the first half and stops at the second, which leaves the tools and the
daemon at different versions. Run `mchealth` on the host after a deploy rather than
assuming it landed.

## Reads and writes go to different places

- **Writes go through RCON.** Editing region files under a running server corrupts them.
- **Reads come from the region files** via `server/bin/region.py`. It is far faster than
  RCON, and it answers "what block is this?", which RCON cannot.
- **A region read sees the last save.** Tools run `save-all flush` first. When you verify
  a change you just made, never pass `--no-flush`. You will read stale data and conclude
  the change failed.

## A config file is not always the source of its own settings

- Before you edit a config file, confirm it is the authoritative source. A containerised
  service regenerates files such as `server.properties` on every start, from the compose
  file, the launch script, and the environment.
- After you apply a change, verify it took effect on the live service, not only on disk.
  A change that only landed on disk looks identical to one that worked.

## Before you change the world

- Run a destructive edit with `--dry-run` first. Read the counts it reports, and stop if
  they are not what you expect.
- Never delete or overwrite a backup in `/opt/mc/backups`. Read them freely: extracting
  one region file is how you recover what was in a place before.
- Read `.claude/rules/world-edit-tools.md` before you write or run a world-editing tool.
  It loads on its own when you open a file under `server/bin/`.

## Minecraft version changes fail silently

NBT syntax, log line formats, datapack layout, and the chunk format `region.py` decodes
all change between Minecraft versions. They fail quietly rather than erroring: a command
reports success and does nothing, or the daemon stops responding to chat. Read **Version
compatibility** in `README.md` before a Minecraft upgrade. After one, run
`mcblock <a block you can see> --verify`.

## Conventions

- Write a commit message as an imperative subject in sentence case, then prose explaining
  why the change exists and what failure it fixes. No bullet lists, no `feat:` prefixes.
- Bump `VERSION` and add a `CHANGELOG.md` entry for a behaviour change.
- Renumber at merge time when two branches claim one version. Every session works in its
  own worktree, so parallel branches rewrite the single line in `VERSION` and insert at the
  same line of `CHANGELOG.md`. If the version a branch claims already exists on the target
  branch, renumber the incoming work to the next free version before you merge. The
  renumber changes `VERSION` and the matching heading in `CHANGELOG.md`.
- Keep both entries when you resolve a `CHANGELOG.md` conflict. If you take one side, you
  drop the other branch's entry and nothing reports it.
- Never commit secrets, `server/mcbot/local-lore.md`, or a local persona
  (`server/personas/*.local.md`).

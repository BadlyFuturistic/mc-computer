# mc-computer

An in-game assistant for a Minecraft server. This repo is edited on a workstation and
deployed to the Minecraft host; nothing here runs locally.

Only project facts that are not obvious from the code belong in this file. Personal
setup and preferences go in `CLAUDE.local.md`, which is gitignored.

## The split that matters

| | |
|---|---|
| `server/bin/` | tools installed to `/opt/mc` on the Minecraft host — no privilege needed |
| `server/mcbot/` | the daemon and its prompt, installed to `/opt/mcbot` — **needs sudo and a TTY** |
| `client/` | deploy script and shell aliases for the workstation |

`./client/deploy.sh` does both halves, but only the second prompts for sudo. A deploy run
without a terminal lands the tools and silently skips the daemon and prompt, so the two
can be different versions. Check with `mchealth` on the host rather than assuming.

## Reads and writes are not symmetric

- **Writes go through RCON.** Editing region files under a running server corrupts them.
- **Reads come from the region files** via `server/bin/region.py` — roughly 185x faster
  than RCON probing, and it can answer "what block is this?", which RCON cannot.
- Region reads see the **last save**. Tools call `save-all flush` (~0.3s) first. When
  verifying a change you just made, do not pass `--no-flush` — you will read stale data
  and conclude the change failed.

## Things that fail silently

Several dependencies change between Minecraft versions and then report success while doing
nothing: NBT syntax, log line formats, datapack layout, and the chunk format the region
reader decodes. See **Version compatibility** in `README.md` before upgrading Minecraft,
and run `mcblock <a block you can see> --verify` afterwards.

## Conventions

- Commit messages: imperative subject in sentence case, then prose explaining *why* the
  change exists and what failure it fixes. No bullet lists, no `feat:` prefixes.
- Bump `VERSION` and add a `CHANGELOG.md` entry for behaviour changes.
- Never commit secrets, `server/personas/frank.md`, or `server/mcbot/local-lore.md` — all
  gitignored, all containing private or world-specific content.
- Tools are standalone scripts with no extension; shared libraries are `*.py`. `deploy.sh`
  derives file modes from that, so a new tool needs no list updating.

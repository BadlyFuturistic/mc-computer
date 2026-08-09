# mc-computer

An in-game assistant for a small Minecraft server. Players talk to it in chat and it
carries out what they ask — items, structures, teleports, weather, questions about the
world — and stays quiet otherwise. It runs on the Minecraft host as an unprivileged
service with no Docker access and two writable directories.

**Version 0.2 — targets Minecraft 26.2 (NeoForge).** See [Version compatibility](#version-compatibility)
before running it on anything else; several things it depends on are version-specific
and fail *silently* when they change.

---

## What it does

- Answers and acts on chat, deciding for itself whether a message was aimed at it
- Resolves named places (waystones, map waypoints) instead of asking for coordinates
- Places prebuilt `.nbt` structures from a catalog rather than freehanding geometry
- Teleports players somewhere they can actually stand
- Reads Sophisticated Backpack contents, which live outside the item
- Remembers messages for offline players and delivers them on login
- Checks the nightly backup and reports its health to the admin
- Answers from a terminal too, via a forked session that shares its context

## Layout

    server/bin/        tools installed to /opt/mc on the Minecraft host
    server/mcbot/      the daemon, its system prompt, memory module
    server/systemd/    the hardened service unit
    server/setup/      one-time privileged installer
    client/            shell aliases and the deploy script for a workstation

## Requirements

On the Minecraft host:

- Docker-hosted Minecraft server with RCON enabled and bound to localhost
- Python 3.11+ with `venv` (`apt install python3-venv`)
- `acl` (`apt install acl`) — required; see [Permissions](#permissions)
- `pigz` for backups

On the workstation: an SSH alias to the host, and `bash` or `zsh`.

---

## Install

1. Enable RCON in your `compose.yaml`:

       ENABLE_RCON: "true"
       RCON_PORT: "25575"
       RCON_PASSWORD: "<a long random string>"
       BROADCAST_RCON_TO_OPS: "false"
       CREATE_CONSOLE_IN_PIPE: "true"
       OPS: "<your minecraft username>"

   Publish the port to localhost only:

       ports:
         - "127.0.0.1:25575:25575"

2. Put your Anthropic API key on the host at `/tmp/mcbot-stage/api.key`.

3. From the workstation:

       MC_HOST=your-ssh-alias ./client/deploy.sh --setup

The installer creates the `mcbot` account, installs the unit, and starts it. It reads
the RCON password and admin username out of `compose.yaml` so they are not duplicated.

Afterwards, `./client/deploy.sh` pushes code and prompt changes and restarts.

---

## Permissions

This is the part that bites. The service runs as `mcbot`, which is deliberately **not**
in the `docker` group — Docker socket access is root-equivalent and would make the rest
of the sandboxing decorative. Everything below is applied by `mcbot-setup.sh`; it is
documented here because a stale permission produces a *quiet* failure, not an error.

| Path | Access | Why |
| --- | --- | --- |
| `/opt/mc/data` | read (ACL, recursive + default) | world data, mod data, server log |
| `/opt/mc/backups` | read (ACL) | nightly backup health check |
| `/opt/mc/data/world/datapacks/mcbuilds` | **write** | structure catalog |
| `/var/lib/mcbot` | **write** | memory database, logs, session id |
| `/opt/mc/compose.yaml` | none (`InaccessiblePaths`) | holds the RCON password |
| `/etc/mcbot/env` | read, `640 root:mcbot` | API key, RCON password |

**Default ACLs are load-bearing.** The Minecraft server rewrites files such as
`waystones.dat` on every save and recreates them mode `600`, so a plain `chmod` is
undone within minutes. A default ACL on the directory makes newly created files
inherit read access:

    setfacl -R -m u:mcbot:rX -m d:u:mcbot:rX /opt/mc/data /opt/mc/backups

Granting this on all of `data/` rather than per-mod is intentional — otherwise every
new mod whose data the bot needs to read requires another permission fix.

**Backups are readable but not writable.** Read access lets the bot verify the nightly
job. `ProtectSystem=strict` in the unit mounts the whole filesystem read-only except
the two `ReadWritePaths`, so the bot cannot modify or delete a backup regardless of
file permissions. It can create one via `sudo mcbackup`, which never deletes.

**Sudo is four fixed commands**, no wildcards, no arguments the bot controls:

    /usr/bin/docker restart mc
    /usr/bin/docker compose -f /opt/mc/compose.yaml down
    /usr/bin/docker compose -f /opt/mc/compose.yaml up -d
    /opt/mc/mcbackup

### Admin access from a terminal

`mcask` runs as *you*, not as the service, so it needs two extra grants that the
installer applies:

    sudo chgrp -R "$(id -gn)" /opt/mcbot && sudo chmod -R g+rX /opt/mcbot   # reach the venv and prompt
    sudo setfacl -m "u:$(id -un):rx" /etc/mcbot                             # traverse the secrets dir
    sudo setfacl -m "u:$(id -un):r"  /etc/mcbot/env                         # read the API key

Both ACLs are needed. Read on the file is unreachable without traverse on the
directory, and the resulting error points at the file, not the directory.

---

## Local world knowledge

Landmarks, base names and conventions specific to your world go in
`/opt/mcbot/local-lore.md`, which is appended to the system prompt. Start from
`server/mcbot/local-lore.example.md`. It is gitignored, so your world's details stay
out of the repo.

Without it the bot still resolves waystones and waypoints by name; the lore file is
for things no data file records, such as which base is the important one.

---

## Tools

| tool | what it does |
| --- | --- |
| `mccmd` | run RCON commands from stdin, safe with NBT braces and quotes |
| `compsay` | speak in chat as `[comp]`, no `[Rcon]` prefix |
| `mcwhere` | resolve named waystones and waypoints to coordinates |
| `mctp` | teleport a player to somewhere standable |
| `mcbag` | read Sophisticated Backpack contents |
| `mcbuild` | install, describe and place `.nbt` structures |
| `mcnote` | the bot's memory: held messages, activity log, backup verdicts |
| `mcrestart` | announced countdown restart, skippable |
| `mcbackup` | live backup, no downtime, never deletes |
| `mcmotd` | set the MOTD in `compose.yaml` |
| `mcask` | ask from a terminal, in a forked session with full context |

Client-side, from `client/.bash_aliases`: `mccomplog` and `mccompall` for logs,
`mccost` for what each turn costs (`mccost today` for a daily total), `mccompctl` for
the service, plus `mcrestart`, `motd`, `mcwhere`, `mcbag`, `mcask` and `mcdeploy`.

---

## Version compatibility

Targets **Minecraft 26.2**. The pieces below are version-sensitive, and most of them
fail quietly rather than erroring — a command reports success and simply does nothing.
Check these first when moving to a new Minecraft version.

**NBT syntax** (`server/mcbot/minecraft-computer.md`, `<nbt_syntax>`). Since 1.21.5:

    CustomName:{text:"Name"}                         not  CustomName:'{"text":"Name"}'
    attributes:[{id:"minecraft:max_health",base:100}]  not  Attributes:[{Name:"generic.max_health",...}]

The old forms are *accepted and ignored*. Verify with `data get entity` after summoning
rather than trusting the success message.

**Log line formats** (`server/mcbot/comp-daemon.py`). The daemon triggers on regexes
matched against `latest.log`:

| pattern | matches |
| --- | --- |
| `CHAT` | `<Player> message` |
| `JOIN` / `LEAVE` | `Player joined the game` / `left the game` |
| `READY` | `Done (1.234s)!` at startup |

If a version changes these, the bot goes silent with no error. Test with a chat message
and a login after upgrading.

**Datapack format.** `pack_format` in `mcbuild`, and the structure directory is
`data/<ns>/structure/` — **singular**, renamed from `structures/` in 1.21. The plural
form fails to load silently.

**Structure size.** `/place template` ignores the 48-block structure-block limit for
datapack-loaded structures on 26.2. Verified, but worth re-checking on a new version.

**Mod-specific paths.** `mcbag` reads Sophisticated Backpacks' store at
`world/dimensions/minecraft/overworld/data/sophisticatedbackpacks/backpack_storage.dat`
and resolves it by the item's `storage_uuid`. A mod update can move or restructure this.

## Versioning

`0.x` while the interface is still moving. The minor version bumps on behaviour changes;
the Minecraft version it targets is recorded in `CHANGELOG.md` for each release, since a
release that works on one Minecraft version may fail silently on another.

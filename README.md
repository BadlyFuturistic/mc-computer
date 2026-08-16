# mc-computer

An in-game assistant for a small Minecraft server. Players talk to it in chat and it
carries out what they ask — items, structures, teleports, weather, questions about the
world — and stays quiet otherwise. It runs on the Minecraft host as an unprivileged
service with no Docker access and two writable directories.

**Targets Minecraft 26.2 (NeoForge).** See [Version compatibility](#version-compatibility)
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

    setfacl -R -m u:mcbot:rX -m m::rX -m d:u:mcbot:rX -m d:m::rX /opt/mc/data

The `m::rX` part is essential and easy to miss. A file's group-permission bits *are* its
ACL mask, so a file rewritten at mode `0600` gets `mask::---`, which masks the bot's read
entry down to nothing — `getfacl` still lists the entry, marked `#effective:---`, while
granting no access at all.

Because the server rewrites these files at `0600` on every save, this does not hold on its
own. `mcbot-acl.timer` reapplies it every two minutes over the small, frequently-rewritten
data directories.

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
    sudo setfacl -m "u:$(id -un):r"  /etc/mcbot/limits                      # read the spend limit

Both ACLs are needed. Read on the file is unreachable without traverse on the
directory, and the resulting error points at the file, not the directory.

---

## Personas

The assistant's voice lives in `/opt/mcbot/personas/*.md`, separate from everything it
knows how to do. Swapping a voice is dropping in a file; it changes only how the
assistant sounds, never what it will or will not do.

    mcpersona list                      what is available, which is active
    mcpersona set <name> --by <player>  switch
    mcpersona reset --by <player>       back to the configured default

Ships with `computer` (calm and impersonal), `assistant` (a capable first-party
helper), `plain` (no character at all) and `librarian`. Add your own by writing a file with `name` and `description` frontmatter
and the voice below it.

A voice is written as a specification rather than a description: who the speaker is, then
sentence length, lexicon, syntax, and certainty, then the list of what it never says
paired with what it says instead, then sample exchanges. Adjectives such as "calm" or
"warm" name a register without supplying one, and every voice written that way converges
on the same mildly flavoured default. Each file also states a floor — the thing the voice
still communicates however it sounds — because a voice that reads well and loses which
half of the job worked has failed.

`mcpersona` only offers files that carry `name:` frontmatter, so a voice can keep a
supporting file beside it — reference lines it was tuned against, say — without that file
being listed as a voice. Deploying copies every `.md` in the directory either way.

`PLAYERS_CAN_CHANGE_PERSONA` in the config decides whether anyone may switch or only the
admin. It defaults to **true**, on the assumption that most servers would rather let
players play with it.

Deploying installs any persona that is missing and never overwrites one that exists, so
your edits and your own personas survive upgrades.

## Configuration

`/etc/mcbot/config`, root-owned: the bot reads it and cannot change it. Anything the bot
*may* change at runtime — the active persona — lives in its database instead.

Deploying runs a migration that **adds keys introduced by a new version and changes
nothing already in the file**, appending each with its default and a comment explaining
it. A setting therefore shows up in your config rather than existing only in code, and an
edited value is never reverted by an upgrade.

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
| `mchealth` | one-shot health check: service, version, RCON, world data, spend |
| `mcblock` | what block is actually there; survey, search or check a region |
| `mcitem` | the real id for an item or block a player named |
| `mcbore` | cut a tunnel through a mass, finding both ends itself |
| `mcpave` | carry a carriageway on from the end of a road |
| `mcrepave` | restore a road surface by cloning an intact slice along |
| `mcbranch` | turn a road off an existing one at a right angle |
| `mcshape` | build a sphere, dome, cylinder, torus, ramp and nine more |
| `mcmark` | read a build marked out with blocks placed in the world |
| `mcpersona` | list, show and switch the assistant's voice |
| `mcdoing` | name the current job, so progress lines mean something |
| `mctrace` | follow a connected run of pipe, cable or rail; optionally convert it |
| `mcfill` | bulk region edits, sliced past the 32768-block fill limit |
| `mcignite` | prime TNT, finding a real TNT block near the point given |
| `mcthink` | escalate one hard sub-problem to a stronger model |
| `mcfable` | run a request on Fable, gated on admin approval |

Client-side, from `client/.bash_aliases`: `mccomplog` and `mccompall` for logs,
`mccost` for what each turn costs (`mccost today`, `yesterday` or a date such as
`mccost 2026-08-09` for a daily total), `mccompctl` for the service, plus
`mcrestart`, `motd`, `mcwhere`, `mcbag`, `mcask` and `mcdeploy`.

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

**Chunk format** (`server/bin/region.py`). Block reads decode region files directly. The
section layout — palette plus a packed long array, no entry straddling a long since 1.16 —
changes between versions, and a reader that has fallen behind returns *plausible wrong
blocks* rather than failing. `mctrace` spends one RCON call on `Reader.verify()` before
trusting a walk, and `mcblock --verify` does the same on demand. Run one after upgrading:

    mcblock <a block you can see> --verify

**Mod-specific paths.** `mcbag` reads Sophisticated Backpacks' store at
`world/dimensions/minecraft/overworld/data/sophisticatedbackpacks/backpack_storage.dat`
and resolves it by the item's `storage_uuid`. A mod update can move or restructure this.

## Checking a change landed

    mcblock check <x1> <y1> <z1> <x2> <y2> <z2>          JSON: counts, surfaces, voids
    mcblock check <x1> <y1> <z1> <x2> <y2> <z2> --text   the same, to read

Reports what a box is made of, the surface level of every column, columns that are empty
or hollow underneath, and any block id that appears inside the box but nowhere in the
terrain around it — which is what a player's build looks like from a tool's point of
view. It is read-only, and it flushes first, so it describes the world as it is now
rather than as it was at the last save.

There is no list of natural blocks anywhere in this. The surrounding terrain is the
comparison, so a modded block the server gained yesterday does not need adding anywhere.
The cost is that a genuinely rare natural block reads as foreign: treat that field as
something to look at, not a verdict. Entities are not read at all — a box that reports
clean can still have a minecart parked in it.

The writing tools use the same check on themselves. `mcfill`, `mcshape`, `mcpave`,
`mcrepave`, `mcbranch` and `mcbore` each survey the box before they write, flush, survey
it again, and refuse to report a success the world does not support. RCON counts the
commands it accepted, which is not the same question: `mcrepave` once cloned a hillside
into a bored tunnel, 1190 blocks, and every one came back as a success.

## Tests

    python3 -m unittest discover -s tests

Runs anywhere, including a workstation, because everything it covers is arithmetic:
the merge and split in `builder.py`, the road tests in `roads.py`, the `falls` and
`passable` predicates in `region.py`, and the comparisons in `verify.py`. These are the
modules shared by the most tools, so a geometry bug here reaches `mcpave`, `mcrepave`,
`mcbranch`, `mcbore` and `mcshape` at once.

Anything that talks to RCON or reads a region file is tested by deploying it and running
it on the host. There are no region-file fixtures on purpose: `region.py` decodes chunks
and cannot write them, so a fixture world would need an NBT writer first — more code than
the bugs it would catch. Where a test needs a world it supplies a reader backed by a
dict.

## Health checks

    mchealth

Reports service state, the build that is **running** versus the build installed, RCON
reachability, whether world data is readable, spend against the limit, held messages,
and how long since the last activity. Exits non-zero if anything needs attention, so it
works as a check and not only as something to read.

The version line is the one that needs machinery. Comparing files on disk tells you what
was *deployed*; a deploy without a restart looks identical from the filesystem. So
`deploy.sh` stamps `/opt/mcbot/BUILD` with the version, git commit and timestamp, and the
daemon writes what it actually loaded to `/var/lib/mcbot/runtime.json` at startup. A
mismatch between the two is reported as "deployed without a restart".

A commit with uncommitted changes in the tree is stamped `-dirty`, so an ad-hoc deploy is
visible later.

## Versioning

`0.x` while the interface is still moving. The minor version bumps on behaviour changes;
the Minecraft version it targets is recorded in `CHANGELOG.md` for each release, since a
release that works on one Minecraft version may fail silently on another.

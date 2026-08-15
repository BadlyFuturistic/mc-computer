---
paths:
  - "server/bin/**"
---

<!-- last-verified: 2026-08-15 -->

# Writing and running the world-editing tools

Each rule below came from a tool that shipped, ran against the live world, and did
damage a player had to report. They are not style preferences.

## Tool design

**Never truncate silently.** `mcblock find` stopped scanning once it had enough matches
to print. Chunks scan in ascending order, so the dropped matches were always at one end,
and the printed coordinates looked like a complete extent. Two tunnels were bored short.
Scan everything, limit only the printing, and lead with the totals.

**Validate before the dry-run return.** `mcfill`'s preflight and `mcbore`'s falling-block
guard both sat after `if dry: return`. "This would change nothing" and "this would bury
the tunnel" are exactly what a dry run exists to report.

**Fail closed on anything that grants a permission.** An unreadable `/etc/mcbot/config`
was swallowed, every setting became its default, and `PLAYERS_CAN_CHANGE_PERSONA`
defaults permissive — so the admin's `false` never took effect. An input that cannot be
read is not an input.

**Put the arithmetic in the tool, not in the conversation.** Tunnel extents derived from
coordinates in a reply were wrong every time. `mcbore` finds both ends in one pass and has
not been wrong since. A deterministic tool beats a better model here, at no cost per call.

**Derive lists; do not maintain them.** `deploy.sh` had a hand-written `chmod` list.
`mctrace` was never added, so it shipped non-executable and nothing reported it.

## World edits

**Take the anchor from the world, not the player.** A tunnel centred on the player came
out a block north of the road; a dry run seconds later placed it five blocks away because
the player had driven on. Use the player's position to decide *which* road, take the
geometry from the road, and refuse when there is no road.

**Copy block state; never reconstruct it.** Road markings came back wrong three separate
ways — default rotation when placed by name, mirrored on one edge when given a facing by
hand. An intact block nearby already carries the right state, and `clone` copies it
exactly. This converts a reasoning problem into a lookup and is the highest-leverage rule
here. `mcrepave` does it for road surfaces.

**A presence check is not an identity check.** `mcrepave` asked "is there a block here?"
to decide it had found intact road. Air is a block and only an ungenerated chunk reads as
absent, so the test passed on open sky and on solid rock. It copied a hillside into the
tunnel it had just been bored through, 1190 blocks, and reported every one as a success.
Before copying from somewhere, confirm that place is what you think it is — and confirm it
from the world. Road markings stand on the carriageway, so the block underneath says
whether a spot is road; that check costs one extra read and holds for both the place
copied from and the place copied to.

**Order operations so nothing loses its support.** Four incidents, one shape: something
was removed before the thing depending on it was in place. Leaves decay without logs;
kelp and sugar cane stand on the block below; sand and gravel fall. Line a tunnel *before*
hollowing it. Before removing anything, ask what is resting on it.

## Minecraft mechanics that mislead

**A bare `~` from RCON resolves against the console, not the player.**
`tp <player> ~ ~1 ~` teleports them to world spawn. Use absolute coordinates or
`execute as <p> at @s run …`.

**A force-loaded chunk is not readable or writable for a tick or two.** Probing at once
reports every block absent, which reads as "wrong block" rather than "not loaded yet".
One `mcfill` run ground through 129 slices changing nothing. Every tool that force-loads
sleeps ~0.6s afterwards.

**A region read sees the last save.** Every tool that reads the world calls
`save-all flush` (~0.3s) first. Offer `--no-flush` only as an opt-out for bulk reads that
do not follow a write.

## Testing

Test writes with `--dry-run` first. A test run of `mcbore` without it punched a five-block
hole through a tunnel a player was standing in. If you must write, pick empty air far from
anything a player built, confirm it is empty with `mcblock` before you write, then clean up
and verify it is clean.

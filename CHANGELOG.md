# Changelog

Versions are `0.x` while the interface is still moving. Each entry records the
Minecraft version it was developed and tested against, because several dependencies —
NBT syntax, log line formats, datapack layout — change between Minecraft versions and
fail *silently* rather than erroring.

## 0.4.1 — Minecraft 26.2 (NeoForge)

- Chat sent while the server log rotated was silently dropped. The tail seeked to the
  end of the new file on reopen, discarding the ~10 second window between rotation and
  reopen. A player's message vanished with no error, and a later "do the above request"
  then referred to something older. Rotation now reads the new file from the start.
- Replies are public by default. A private reply to a public question reads as being
  ignored by everyone else in the room.

## 0.4.0 — Minecraft 26.2 (NeoForge)

- `mcfill` for bulk region edits. Minecraft caps /fill at 32768 blocks, so large
  requests were dozens of hand-sliced commands; this slices, force-loads each slice,
  runs the fills over one connection and releases the chunks. `--replace` accepts block
  tags, so "every tree" is `#minecraft:logs` rather than a guess at species.
- `mcignite` finds a real TNT block near the point given before priming it. Aiming at a
  coordinate directly fails often, because a converted hillside keeps the cave voids
  that were already in it and the centre is frequently air.
- Fable, on explicit player request only, gated on admin approval. The approval is
  granted by the daemon on seeing the admin agree in raw chat, so the model has no route
  to approving its own request. Single use, expires after 30 minutes.

## 0.3.1 — Minecraft 26.2 (NeoForge)

- `mchealth`: service state, running-versus-installed build, RCON, world data
  readability, spend, held messages, last activity. Non-zero exit on any problem.
- Builds are stamped at deploy and recorded by the daemon at startup, so "is it running
  the version I think it is" has an answer that a file listing cannot give.
- Per-turn cost is recorded as the delta from the session's running total, rather than
  the running total itself. The previous behaviour counted every turn once more for each
  turn that followed and tripped the spend limit at roughly 2.7x actual spend.

## 0.3.0 — Minecraft 26.2 (NeoForge)

- Default model is Sonnet, with `mcthink` to hand one hard sub-problem to a stronger
  model. Escalation passes explicit context rather than forking the session, since the
  transcript is what makes a turn expensive.
- Sessions roll over during silence — after 20 minutes idle, or 5 minutes once a
  session has run 25 turns. Per-turn cost grew linearly with transcript length before
  this; a one-word reply had reached $1.55.
- Daily spend limit in `/etc/mcbot/limits`, read fresh on every check, root-owned so
  the bot cannot raise it.
- Crash reports. A new file in `crash-reports/` triggers an investigation written to
  `/var/lib/mcbot/crash-reports/<ISO8601>.md`. Loop protection is layered: identical
  crashes only bump a counter, reports are capped per day, and a cooldown stops a fast
  loop firing even that many times.
- The server finishing startup now wakes the bot to verify the backup and check for
  crash reports.
- Terminal questions and backup checks appear in the cost log alongside chat turns.

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

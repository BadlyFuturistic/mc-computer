# Changelog

Versions are `0.x` while the interface is still moving. Each entry records the
Minecraft version it was developed and tested against, because several dependencies —
NBT syntax, log line formats, datapack layout — change between Minecraft versions and
fail *silently* rather than erroring.

## 0.9.0 — Minecraft 26.2 (NeoForge)

**`mcblock find` was hiding the extent of what it found, and a tunnel was bored short
twice because of it.** It stopped scanning at the print limit. Chunks are scanned in
ascending order, so truncation always lost the far end — which from the player's side is
the end nearest them — and the coordinates it did print looked like the whole thing. Asked
to open a 1-block road tunnel to full height, the assistant read the truncated list as the
mass's extent and left seven blocks of hill standing right in front of the player. Twice.

- `find` now scans everything and limits only the printing. It leads with the true extent
  and total count, so a truncated listing still tells the truth. The scan costs
  hundredths of a second; ending it early bought nothing.
- New `mcbore`: cuts a tunnel through a mass and finds both ends itself. It steps forward
  from the player, testing the whole cross-section, and takes the first blocked step as the
  entrance and the last as the far side — so the near end is found by the same pass as the
  exit. It clears, lines and lights in one go. The extent arithmetic is out of the model,
  which had got it wrong every time it was asked to do it.
- The floor row does not count when locating the mass. Roads carry a surface, painted
  lines, rails and carpets at exactly that level, and counting those started the tunnel at
  the player's own feet and bricked up open road.
- `region.passable()` decides what stands in the way. Anything unlisted counts as solid,
  which is the safe direction: a tunnel one block too long is harmless, one that stops
  short leaves a wall across the road.

**Progress lines now say what the job is for.** A line built only from the running tool
describes machinery — someone who asked for a tunnel was told "searching for that block".

- New `mcdoing`: the assistant names the job once, in the player's words, and the line
  becomes "cutting the tunnel through the hill — searching for that block". The detail
  still comes from the command actually running, so it cannot drift from the truth.
- The stated goal is cleared at the start and end of every turn, so it can never describe
  the previous request during the next one.

## 0.8.0 — Minecraft 26.2 (NeoForge)

**Fable approval now covers a job, not a single run.** A request is rarely finished in one
go — "actually make it blue" is the same piece of work — and re-approving every follow-up
made the feature unusable. Approving opens a grant that stays open for follow-ups.

- The grant ends at the boundaries the admin's decision was scoped to: the conversation
  being wiped (a session rollover or a persona change), the admin logging out, or the
  daemon restarting. An old yes can never be spent on a later, unrelated conversation.
- `mcfable status` reports whether access is open and how many runs it has covered.
- The request/approve/deny audit trail is unchanged; use no longer closes the approval.

**The bot now says what it is doing during long jobs.** Player-legible, and quiet by
design: nothing for the first 15s, then at most one line every 20s, never the same line
twice in a row, and nothing at all for a turn that runs no real tools.

- Phrases are derived from the command actually running — "following the run to see where
  it goes", "converting the trees, leaves first", "working out what the area is made of".
  Reading the tool call rather than asking the model costs no tokens and cannot narrate a
  step that is not happening.
- The prompt tells the model not to narrate as well, so the two do not double up.
- A failed progress line is logged and skipped rather than silently killing the commentary
  for the rest of the job.

## 0.7.0 — Minecraft 26.2 (NeoForge)

Block reads now come from the world files instead of RCON. RCON has no command that
answers "what block is here?" — only `execute if block <id>`, which tests a guess and
replies yes or no, so a wrong id and empty ground are indistinguishable. Measured on the
live server, 100 blocks in cold chunks: **5.55s over RCON** (2.4s of that force-loading)
against **0.03s from the files** — and the file read returns the actual id.

- New `region.py`: region-file reader with a chunk cache. Handles both world layouts
  (`dimensions/<ns>/<path>/` and the older `DIM-1`/`DIM1`), oversized `.mcc` chunks, and
  distinguishes an ungenerated chunk from air.
- New `mcblock`: point lookup, `survey` for what a region is made of, `find` for where a
  block is. Surveying 35,301 blocks takes 0.06s.
- `mctrace` walks the run from the files. No force-loading, no settle delay, no round trip
  per block: a 78-block pipe run fell from ~10s to **0.01s**. It also reports what the run
  is made of, and a failed start now says what it found instead of only what it wanted.
  `--block 'pipez:*'` matches a family by prefix. Default `--max` raised to 100,000.
- `mcfill` gains a pre-flight check. `validate()` already caught an id the game has never
  heard of; this catches the other half — an id that is real but absent from the box, which
  otherwise runs every fill successfully and changes nothing. It reports what is actually
  there instead. Both checks now run under `--dry-run`, which is when they are wanted.
- Reads see the last save, so these tools run `save-all flush` first — 0.3s, once.
- `Reader.verify()` cross-checks one block against RCON before a batch is trusted, because
  the chunk format changes between Minecraft versions and a stale parser returns plausible
  wrong blocks rather than failing.
- `deploy.sh` built its `chmod` list from hand-maintained names, and `mctrace` was missing
  from it — it had been deploying non-executable. One derived list now drives both the copy
  and the modes, and it skips directories: a `__pycache__` left by running the tools
  locally is a directory, and `scp` aborts the entire transfer on one.
- The `mcdeploy` alias hardcoded `~/mc-computer` and broke wherever the repo actually sits.
  It now derives the repo from the path this file was sourced from, in bash and zsh.

## 0.6.0 — Minecraft 26.2 (NeoForge)

- `mctrace` follows a connected run of pipe, cable, rail or conduit from one block and
  reports its size, extent and ends. `--replace` converts exactly the run, which a region
  fill cannot do around a snaking pipe. Tracing 68 blocks of pipe by hand previously took
  several minutes of probing per question.
- Force-loading a chunk does not make it readable at once. Probing or filling immediately
  reports every block as absent, so `mcfill` could silently change nothing on cold chunks
  and a trace would stop early. `mcfill`, `mctp` and `mctrace` now wait for the chunk.
- The RCON client waited 150ms after every reply in case it was split. Only a reply at the
  packet ceiling can be continued, so the wait is now conditional. A trace fell from 47 to
  10 seconds; every tool benefits.
- New `assistant` persona: a capable first-party helper.

## 0.5.0 — Minecraft 26.2 (NeoForge)

- Personality moved out of the system prompt into `/opt/mcbot/personas/*.md`. A voice is
  now a file, swappable with `mcpersona`, and the base prompt carries only capability and
  behaviour. Ships with computer, plain and librarian.
- `PLAYERS_CAN_CHANGE_PERSONA` decides whether anyone may switch or only the admin;
  defaults to true.
- `/etc/mcbot/config` replaces the limits file, which is still read if present. Deploying
  adds keys a new version needs and leaves existing values alone.
- Deploying never overwrites an existing persona file.

## 0.4.2 — Minecraft 26.2 (NeoForge)

- Kelp, sugar cane, bamboo and cactus convert top-down, one layer at a time. /fill
  works upward from the low corner, so converting a strand from underneath broke
  everything above it: a single sponge left stranded and the rest drifted away.
- Trees convert leaves before logs via `mcfill --trees`, since natural leaves decay
  once no log remains near them.
- `mcfill` validates the block and filter before slicing, and stops after three
  consecutive failures. An invented mod block id previously ground through 129 slices
  over eight minutes, changing nothing and blocking every other request.
- Background commands are forbidden. A backgrounded command outlives its turn, so its
  output landed in the next player's turn and was reported to the wrong person.

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

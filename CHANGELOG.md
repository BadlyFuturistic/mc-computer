# Changelog

Versions are `0.x` while the interface is still moving. Each entry records the
Minecraft version it was developed and tested against, because several dependencies —
NBT syntax, log line formats, datapack layout — change between Minecraft versions and
fail *silently* rather than erroring.

## 0.23.0 — Minecraft 26.2 (NeoForge)

**The personas are rewritten as voice specifications, and policy has moved out of them.**

- `assistant.md` carried policy, not voice: be honest about what half worked, ask one
  short question when ambiguity would change the outcome, check rather than guess. The
  base prompt already says all three, and the other three personas never did. So the
  active persona quietly decided how strongly the assistant was told to be honest, and
  switching to `plain` dropped emphasis nobody meant to drop. The voice files now carry
  only how a reply sounds; what the assistant will and will not do lives in one place.
- Every persona was an adjective stack — "calm, precise, impersonal", "patient and
  precise", "warm but efficient". Adjectives name a register without supplying one, so
  all four resolved to the same mildly flavoured default and the feature bought little.
  Each file now sets sentence length, lexicon, syntax, certainty, and a list of what the
  voice never says paired with what it does instead, then shows six to ten sample
  exchanges written in Minecraft chat and inside the 190-character budget.
- Each voice now has one habit that makes it identifiable in a single line: the computer
  gives the number, the assistant names the wrinkle the player has not thought of, the
  librarian adds exactly one adjacent fact, and `plain` adds nothing at all.
- `plain.md` said "You have no persona", which is not a thing a model can be. Left
  unspecified it falls back to its default manner — eager, hedging, rounding the reply
  off — which is a persona, and a chatty one. The file now names those habits and says
  what to do instead.
- Every persona states a floor: however terse or however warm, the reply still says which
  part worked, which did not, and what is standing in the world now. A voice that reads
  well and loses the outcome is the failure this guards against.
- `mcpersona` now offers only the files that carry `name:` frontmatter, which the README
  has required of a persona since personas existed. A voice can therefore keep a
  supporting file beside it — the reference lines it was tuned against — without that
  file being listed as a voice and switched to by someone who then gets no persona at
  all. Deploying still copies every `.md` in the directory, which is what carries the
  supporting file to the host.
- `deploy.sh` never overwrites a persona that differs from the deployed copy, so these
  land only with `./client/deploy.sh --personas`.
## 0.22.0 — Minecraft 26.2 (NeoForge)

**The assistant looks before it overwrites, and escalating a hard call is no longer
discouraged for exactly the calls worth escalating.**

- `<judgment>` gains a rule to survey an area before an edit overwrites it, and to stop
  and ask when anything in it was built rather than grown. The ask-once rule above it was
  inert without this: a fence the assistant never looked at is a fence it cannot ask
  about. Found by the scenario suite, which paved 60 blocks through a fence and two
  chests and reported a clean success.
- `<hard_problems>` no longer ends with "judgement only, anything settled with a tool
  settle yourself". That excluded the case where escalation pays best — an edit about to
  overwrite ground nobody has looked at is settleable with a tool, so the old rule sent
  it straight past `mcthink`. Escalation is now framed by what being wrong costs: a
  rebuild rather than a retry.
- `mcthink`'s own instructions said it could check waystones, RCON and backpacks, and
  never mentioned `mcblock`. The stronger model had world-reading tools and was not told
  so. It now names `mcblock` and `mcblock check` first, and points at `ls /opt/mc` rather
  than implying the list is complete.
- Scenario 04 gained a coherent fake world. It answered every coordinate with the same
  block, including 0 0 0, so a run that probed the reader correctly stopped believing it
  and paved anyway — the harness looked like a prompt failure and was not one.

## 0.21.0 — Minecraft 26.2 (NeoForge)

**A write now reads its own work back, and there is a test suite.**

- New `mcblock check <box>`: counts by block id, the surface level of every column,
  columns that are empty or hollow underneath, and any block id present in the box but
  absent from the terrain around it. JSON by default because the caller is usually
  another tool, `--text` to read it. Read-only, and it flushes first.
- The "foreign block" test derives its comparison from the world rather than from a list
  of natural blocks. A maintained list is wrong for the next modded block the server
  gains, and wrong quietly. The cost is that a rare natural block reads as foreign, so
  the field is a signal and not a verdict.
- `mcfill`, `mcshape`, `mcpave`, `mcrepave`, `mcbranch` and `mcbore` survey their box
  before writing, flush, survey it again, and refuse to report a success the world does
  not support. RCON counts commands it accepted, not blocks that ended up as asked:
  `mcrepave` cloned a hillside into a bored tunnel, 1190 blocks, and reported every one
  as a success. `mcrepave` and `mcpave` check the kinds they laid, `mcbore` checks the
  tunnel is actually clear, and the rest check the block they promised went up.
- The undermined-column count reports the run of passable blocks *directly* under a
  surface, not every gap in the column. Counting every gap called 1,547 of 1,681 columns
  undermined over ordinary cave country around home base, and a number that fires on
  everything says nothing. The same box now reports 72, and spot-checking one found a
  copper grate standing over two blocks of water.
- A check that cannot read the world says so and lets the write stand. Refusing every
  write because the checker is blind would be worse than the problem, and the note goes
  to the operator either way, so "not checked" never reads as "checked and fine".
- Snow and grass are ignored by the kind check. Weather arrives between the write and the
  read, and a check that fails on weather gets switched off.
- First tests in this repository: 89 of them, over `builder`, `roads`, `region` and
  `verify`. `python3 -m unittest discover -s tests`, standard library only, no fixtures
  and no world. They pin the incidents the rules came from — the merge losing no cells,
  the forceload staying under the 256-chunk cap, a road one level too low reading as
  ground, sandstone not falling.

## 0.20.1 — Minecraft 26.2 (NeoForge)

- `mccost` reports a single past day: `mccost yesterday` and `mccost 2026-08-09` join
  `mccost today`. All three build a date and select the log lines that start with it,
  so they can never disagree about what a day is.
- An argument that is neither `today`, `yesterday` nor a real date is now a usage
  error. A typo previously fell through to the live tail, which looks like a day with
  no turns in it and waits forever.
- A valid date with no turns says so. The summary line only ever printed when the
  count was above zero, so an empty day returned in silence and read as a broken
  command.

## 0.20.0 — Minecraft 26.2 (NeoForge)

**New `mcbranch`: a road that turns off an existing one at a right angle, with the markings
handled where they meet.**

- The carriageway is cloned from the parent, a row at a time, so a branch is made of the
  same surface as the road it leaves.
- The marking facings come from a junction that already exists in the world. A painted
  marking carries a facing that cannot be reasoned about — on this world's east-west road
  the north kerb faces west and the south kerb faces east, so the two sides of one
  carriageway point opposite ways — and a branch needs facings that appear nowhere on its
  parent. Cloning them from the north-south segment of the junction beside home base keeps
  the one rule here that has never been safely broken: copy block state, never rebuild it.
  `--from` names a different junction to learn from.
- It clears the parent's kerb line across the mouth, so the two roads join instead of one
  being painted straight through the other.
- Verified in the world rather than from the tool's report: a 60-block branch off the road
  at x -4184 has side lines facing south and north on its two kerbs against west and east
  on the parent, and centre dashes every 5.

**The road tonight's test damaged is repaired.** 1,241 of 2,538 columns had no carriageway
and none of the 2,538 had markings.

- All 2,538 columns now carry full carriageway and markings, confirmed by reading the
  region files rather than by trusting the tools that wrote them. The dashed centre keeps
  its phase the whole way, 2,538 blocks from the marked road it was copied from.
- One column had been "repaired" earlier by a run that laid five slices across the road
  instead of along it, leaving grass where the asphalt belonged. That is the orientation
  bug, and it is why the count is verified from the world.

**Prompt.** `<tunnels>` gains `mcbranch`, says that mcpave now marks what it paves, and adds
two rules from tonight: give a bore the marking level and never the carriageway, and run a
dry run with the same options as the real command. A dry run without `--line` refuses loose
material that the real run accepts, so the pair read as the tool contradicting itself.

## 0.19.0 — Minecraft 26.2 (NeoForge)

**A 2000-block extension laid 225 slices of 2001, ten bores then cut 700 blocks of asphalt
away, and the repave that followed cloned the stone from under the road across the road.**
Three tools, three bugs, one shape: each answered a question about the road from its
arguments instead of from the road.

- New `roads.py`. Which way a road runs and whether a thing is carriageway were worked out
  separately in `mcpave` and `mcrepave`, and the two disagreed. They now come from one
  place, measured off the road itself.
- `builder.load_boxes` splits a force-load across as many commands as the chunk cap needs.
  `forceload add` refuses more than 256 chunks and loads none of them when it refuses; one
  command for a 2000-block road asked for 645, so nothing was loaded and 1776 slices went
  into chunks that were not there. `builder.write` had the same latent bug, so any long
  `mcfill` would have hit it.
- `mcpave` paves in windows of 256 slices, keeping the slice it copies from loaded across
  all of them, so peak chunk load stays bounded on a run of any length.
- `mcpave` now lays markings, by calling `mcrepave` over what it paved. An extension is not
  finished until it is drivable, and leaving the markings to a later request produced 2,538
  blocks of blank asphalt. `--no-repave` opts out.
- `mcrepave` took the road's direction from the shape of the strip it was given: the long
  side is the road. On a one-block bore the strip is 1 along and 5 across, so it decided the
  road ran across itself and sampled the tunnel walls for road. Direction now comes from the
  road.
- `mcrepave` called the commonest solid block under the strip the road surface, with no test
  that it was road. One level too low that is whatever the road was built on. It now checks
  the level is carriageway — solid across and stopping at its edges — and says so plainly
  when it is not.
- `mcbore` refuses a `--floor` that sits on the carriageway. The tunnel floor is the marking
  level; given the carriageway itself a bore cuts the road away. A player's feet gave the
  right level all along, which is why only the explicit-coordinate form ever got this wrong.

## 0.18.2 — Minecraft 26.2 (NeoForge)

**Asked for 2000 blocks of road across open water, mcpave laid 538 and sealed every one
of them under three layers of stone.** The fill over the new road was on by default, on
the reasoning that paving exists to let a tunnel go further. Paving mostly does not.
Nothing bored afterwards and nothing was going to, so the result was half a road, buried.

- `--height` now defaults to 0. The volume over the new road is left alone unless asked
  for, and `--height 3` restores the old behaviour for the road-then-bore sequence.
  `--no-fill` is still accepted, so commands written against the old default still run.
- The volume is still scanned on every run. A run that leaves it open reports how many
  blocks of water and air it left, and that a bore following will read them as open ground
  and stop at the crossing. The reasoning that justified the old default was sound; it was
  the default that was wrong, so the tool now says the thing instead of doing it.
- The prompt paragraph added in 0.18.1 repeated that reasoning and told the assistant the
  solid fill was correct and not overreach. It said so for the case where a bore follows,
  which is the rarer one. It now says to add `--height` only when boring, and not to put
  it on a road a player will drive on.
- Removed the 7,409 stone blocks over the road at y 63–65, x -4225..-3687. Natural bare
  stone runs 5–8% of that height band here and the strip was 92%, so a stone-only replace
  took the fill and left the hillside soil. The carriageway under it is intact.

## 0.18.1 — Minecraft 26.2 (NeoForge)

**Asked to extend a road, the assistant said three times that it had no tool which lays
road. `mcpave` had shipped in 0.16.0 and was installed on the host at the time.** It was
never written into the prompt, so it was never a tool the assistant had. The same omission
was caught in `README.md` one version earlier and fixed there only; the tool table a human
reads and the brief the assistant reads went out of step separately.

- The prompt's `<tunnels>` section now carries `mcpave`, next to `mcbore` and `mcrepave`,
  and states the order the three run in: road first, then bore, then repave. A bore stops
  where the carriageway stops, so paving is what lets a tunnel go further, and that is the
  reason the tool exists.
- New `<no_tool_for_it>` section. The refusal was not only a missing entry — every fallback
  was closed by a different rule. `<structures>` discourages freehand fills for anything
  bigger than a shed, `<hard_problems>` delegates judgement rather than work, and `<fable>`
  forbids suggesting Fable, which is what actually built this road the night before. No rule
  said what to do when all of them apply at once, so the assistant refused instead of
  laying road with `mcfill`, which it could have done. The new section says a missing tool
  is not a missing capability, that a road or wall or causeway is one slice repeated along a
  line, and that a refusal has to give a reason a player can act on.
- It also says to check what was actually run when a player says a job was done before. Told
  it had built the road the previous night, the assistant answered that there was no record.
  It had looked at `mcnote history --days 2`, which rolls a day up to `77 request(s) … (+74
  more)` and hid the build inside the count. A summary that omits something is not evidence
  it did not happen.

## 0.18.0 — Minecraft 26.2 (NeoForge)

**In one hour the assistant told players that biodiesel, magic wood and a car did not exist
on this server. All three did.** It guessed `car:biodiesel_bucket`, one underscore from the
real `car:bio_diesel_bucket`, and read the resulting `Unknown item` as proof the item was
absent rather than proof the guess was wrong. Nothing on the host could tell it otherwise:
there was no way to ask what an id actually is. The player gave the buckets to himself with
`/give` and asked again, and got the same denial.

- New `mcitem`: the real id for an item or block a player named. It reads the `en_us.json`
  lang file inside every installed mod, which maps an id to the display name a player would
  actually say, so "bio diesel bucket" resolves to `car:bio_diesel_bucket`. Spacing is
  normalised away, because the word that started the incident was "biodiesel" and it has to
  match "Bio Diesel Bucket".
- The whole index — 18,788 ids across 180 namespaces — is rebuilt on every run, in about a
  third of a second. There is no cache to go stale after a mod change, and none to write:
  the daemon's only writable path is `/var/lib/mcbot`, which the admin cannot read, so a
  cached index would have needed a sudoers entry to work for both.
- `mcitem check <id>` confirms one id against the live server, using a selector that matches
  no player so the probe parses the id and gives it to nobody. This settles the two things
  the lang index cannot: vanilla ids, which ship in the client jar and are not installed
  here, and whether something with a display name can be given at all — `car:bio_diesel` is
  a fluid block with no item form.
- Searching for a common word matches hundreds of ids, so results are ranked in tiers with
  the exact display name first, and the total is printed above the rows. A bare substring
  test buries the answer: "car" is inside "keycards" and "scarecrow".
- The prompt gains an `<item_ids>` section, and `<structures>` now says that `mcbuild list`
  is the structure catalog alone. The car was refused on the strength of that list, which
  knows nothing about items.
- `mcpave` and `mcrepave` were missing from the tool table in `README.md`. They shipped in
  0.16.0.

## 0.17.0 — Minecraft 26.2 (NeoForge)

**The prompt told the assistant that its own reply text reached nobody, that the server
rejected a message over 256 characters, and — in a sentence cut off mid-clause by an old
edit — left `<role>` open across the whole speaking section.** None of the three were true
of the code they described. The assistant was being briefed against a system that had moved
on, and the rules it needed most were the ones stated three times in three places.

- `minecraft-computer.md` is restructured into operating rules followed by a tool
  reference, ordered the way a turn needs them rather than the order they were written in.
  Every rule survives; nothing about how the world is edited changed. Silence had three
  homes, length two, and "do not narrate" two — each now has one.
- The claim that a reply reaching only the log meant silence for the player was wrong: the
  daemon relays it. The rule now says what the fallback costs — it arrives after the turn
  ends, cut short, and always to everyone — which is the actual reason to run `compsay`.
- The 256-character limit does not exist. `compsay` splits long text on word boundaries, so
  a long reply is never rejected; it just arrives as a wall of chat.
- The progress rules contradicted each other. "Acknowledge first" and "do not post 'working
  on it' between tool calls" were both true and neither said why. They are now one section
  that divides the work: the assistant covers the first fifteen seconds with one line and
  names the job with `mcdoing`, and the automatic updates take it from there. Without
  `mcdoing` those updates say "searching for that block", which is what a player who asked
  for a tunnel used to be told.
- A player who repeats a request already in progress is now told it is still running.
  Repeating interrupts the turn, so the previous behaviour was to start the job again while
  the first attempt was still going.
- The admin's name and the local lore are substituted into the sections that govern them
  rather than appended after everything else. The name used to sit 25k characters after
  `<authority>`, which pointed forward at "the note appended below". The daemon refuses to
  start if the prompt has no `{{ADMIN}}` slot, and warns if lore exists with nowhere to go.
- Turn prompts put the long material first and the instruction last. The rolled-up history
  used to arrive after the instruction. The closing line now covers held messages as well:
  "do nothing at all" sat directly beneath a memory block saying "act on these now", and on
  a turn where nobody addressed the assistant the message it was holding could go undeliv-
  ered.
- `[no response]` is matched after stripping whitespace, case and a trailing full stop. An
  exact comparison meant one stray character pushed a deliberate non-reply to every player.
- Effort raised from `low` to `medium`. Low scopes work to exactly what was asked, which is
  the wrong trade for edits where being wrong means undoing them. `MCBOT_EFFORT` still
  overrides; check `mchealth` reports medium after deploying.

## 0.16.0 — Minecraft 26.2 (NeoForge)

**A bore following a road ran 73 blocks out the far end of it, because it was looking for
solid rock and a hill does not stop where the carriageway does.** It left lined, lit tunnel
with nothing to drive on, and the repave afterwards could only report that most of the
strip was not road. Boring where there is no road at all is a thing worth having; boring
past the end of one is not.

- `mcbore` now stops where the carriageway stops when it is following a road. The road
  surface is the row under the tunnel floor, so this costs one read per step. It says where
  the road ran out and that paving further is what lets it bore further. `--no-align` and
  explicit coordinates are unchanged and still bore through whatever is in the way.
- New `mcpave`: carries a carriageway on from the end of a road by cloning an intact slice
  along, so the surface comes from road that is already correct rather than from a block
  named by hand. It takes the same `<y> <x1> <z1> <x2> <z2>` strip as `mcrepave`, one level
  down, and leaves markings to `mcrepave`.
- `mcpave` also makes the volume over the new road solid, which is not obvious but is what
  makes a crossing borable. Water and air read as passable, so a bore scanning ahead counts
  them as open ground and decides it is through — four such steps end the scan. Filling
  them first turns a flooded crossing into ordinary hillside, which `mcbore` already lines
  before it cuts, and the lining is what keeps the water out.
- Telling road from ground took two tests, and the dry run caught the first attempt using
  only one. Solid is not road: asked to extend the road west, `mcpave` first offered to
  clone the rock face at the tunnel mouth, then a stone band that happened to stop five
  blocks past the strip. A slice counts as carriageway only if it stops at its edges within
  two blocks *and* repeats identically for sixteen slices along. Ground fails one or the
  other; loosen either and it passes.
- The west road now runs from x=-3399 to the coast at x=-3686: 288 blocks of new
  carriageway, 195 of new tunnel lined and lit, four water crossings sealed, and the last
  19 blocks in open cutting to the shore. Centre-line dashes hold a five-block spacing over
  the whole 450-block route with no break at any join.

## 0.15.1 — Minecraft 26.2 (NeoForge)

**`mcrepave` filled a fresh tunnel with the hillside it had just been bored through, and
reported all 1190 blocks as a success.** The only test for "is this intact road?" was
whether a block was present at all, and an absent chunk was the only thing that failed it.
Aimed just past the mouth of a tunnel that had stopped at its 160-block search limit inside
a hill, it read stone, coal ore and dirt, called them road markings, and cloned them across
the floor of the tunnel. The road surface underneath was never touched — the damage was one
layer of rock lying on top of an intact carriageway — but the tunnel read as solid again.

- `mcrepave` now reads what the road is paved with from the row under the damaged strip,
  the one row boring does not touch, and a position counts as road only if it stands on
  that surface. Both ends of every copy are held to it: nothing is read from a place that
  is not road, and nothing is written to one. A sample stops where the carriageway stops.
- It refuses, non-zero, when no intact road can be found either side, rather than copying
  whatever happens to be there. Verified against both cases: no surface under the strip at
  all, and a surface with nothing intact beyond either end.
- The road axis comes from the strip instead of being assumed to be x. Sampling always ran
  along x, so a tunnel bored north to south would have read its own walls; it now samples
  along whichever way the strip is long, and says which it chose.
- Fixed the source coordinate when copying from the far side, which pointed back into the
  damage instead of away from it. Unreachable before, because the old presence test never
  rejected the near side.
- Counting no longer treats a no-op as a failure. Minecraft calls setting a block to what
  it already is a failure, so a clean run over bare carriageway reported "363 of 825" — a
  number that reads as damage. Cloned, cleared and already-right are now counted separately.
- `mcbore --repave` reports a failed repave instead of printing `bored N blocks` and
  exiting zero, and no longer discards mcrepave's per-column warnings when it printed
  anything at all on stdout. That is what let this run back to the player as finished work.

## 0.15.0 — Minecraft 26.2 (NeoForge)

**A tunnel was bored a block north of the road, because it was centred on the player rather
than the road.** Nobody stands exactly in the middle of a lane, so one wall ended up in the
carriageway and the markings ran against it. Worse, a player keeps moving after asking: a
dry run seconds later put the same tunnel five blocks away, across open ground.

- `mcbore` now treats the player's position as a hint about *where they mean* and finds the
  road from it. The surface underfoot is a run a few blocks wide and much longer than it is
  wide, which gives both the centre line and the direction it travels.
- The player's gaze only chooses which end of the road to head for; the axis comes from the
  road, so a glance sideways can no longer send a tunnel across it.
- It refuses if there is no road or corridor near them, instead of boring at their feet.
- Verified across the full road width: seeds at z=239 through 243 all resolve to centre 241.

## 0.14.0 — Minecraft 26.2 (NeoForge)

**Road markings kept coming back wrong, three separate ways, because their facing was being
reasoned about instead of copied.** Placed by name alone they take the default rotation and
sit across the road. Given a facing by hand they come out right on one edge and mirrored on
the other, since the two edges of a road face opposite ways. Each round cost the player
telling the assistant it was still wrong and watching it probe block states by hand.

- New `mcrepave`: for every column across a damaged strip it finds the intact surface just
  beyond it and clones it in, so the block state comes from a block that is already
  correct — facing, mirroring and all. Nothing decides what a block should look like.
- The repeat along the road is matched too. Each column is sampled for its period, so an
  unbroken edge line repeats every block and a dashed centre line every fifth, and the copy
  is taken from the matching phase — dashes line up across the join rather than restarting.
- Surface litter is ignored when reading the period. Snow drifting onto a road made a
  five-block dash pattern measure as twenty-nine, which put the markings back in the wrong
  places.
- `mcbore --repave` runs it after boring. The tunnel floor is exactly where markings live,
  so every bore through a road removes them.

## 0.13.0 — Minecraft 26.2 (NeoForge)

**Boring a tunnel under a desert filled it with sand and left a hole through to the
surface.** Sand and gravel are held up by the block beneath them and nothing else, and
`mcbore` cleared the tunnel first and lined it afterwards — so between those two steps
nothing was holding the roof up. Gravel had already come down onto a finished road this way.

- The lining is now placed **before** the tunnel is hollowed out, so the ceiling is already
  carrying whatever sits on it. The fix is an ordering one; no extra work is done.
- `mcbore` refuses when loose material is overhead and nothing has been given to hold it,
  and says what to pass. `--support <block>` caps the ceiling without lining the walls.
  Checked before `--dry-run` returns, which is when it is wanted.
- `mcfill` and `mcshape` warn when clearing a region would drop sand or gravel into it.
  They do not refuse, and stay silent when placing solid blocks, which supports it anyway.
- `region.falls()` decides what falls. Matched by exact name: "sandstone" contains "sand"
  and does not fall, and a substring test would brace solid rock while sand poured through.

Measured on the tunnel that prompted this: 72 blocks of sand sit in the ceiling layer alone,
with 140 more above it.

## 0.12.0 — Minecraft 26.2 (NeoForge)

**Teleporting resolves the destination itself.** `mctp` took coordinates only, so the
caller had to work out where "the surface" or "where Lucas is" actually was. Asked to put a
player on the surface above them, the assistant guessed a height and teleported to find
out — four times, throwing the player from y=320 to y=63 to discover the ground.

- `--surface`, `--to <player>`, `--place "<name>"`, `--up <n>`, `--down <n>`. Each resolves
  at the moment of use, so a player's position cannot be stale by the time it is used.
- `--dry-run` reports the landing spot without moving anyone.
- **A rider is moved with their vehicle.** Teleporting a player dismounts them and strands
  the vehicle where it was. The vehicle is tagged through `on vehicle`, moved, and remounted.
- The column search reads the world files instead of firing ~97 RCON probes per call, and
  generates the chunk first when the destination has never been visited.
- Documented, in the tool and the prompt: **`~` does not work over RCON.** It resolves
  against the world spawn, not the player, so `tp <player> ~ ~1 ~` sends them to spawn.

## 0.11.1 — Minecraft 26.2 (NeoForge)

**`mcbore` destroyed the road it was tunnelling for, and sealed both ends of the tunnel.**
The lining was built by filling a box one block larger than the tunnel on every side and
then hollowing it out. Growing it on *every* side was wrong in two directions at once:

- The row below the tunnel is the road surface. It was filled with stone bricks and then
  "restored" by filling that row with air, which deleted 19 blocks of road outright.
- The two faces along the direction of travel are the mouths. Filling them walled the
  tunnel off at both ends — the opposite of boring through something.

The lining is now built from the wall and ceiling faces explicitly. It never includes the
end faces, and never includes the floor unless `--floor-too` is given. Checked against the
exact tunnel that failed: the lining spans x -1370..-1354 against an interior of
-1370..-1354, reaches neither mouth, and never touches the road row.

## 0.11.0 — Minecraft 26.2 (NeoForge)

**An unreadable config was indistinguishable from a config that agreed with every
default.** `/etc/mcbot/config` was root-owned with no access for the service account, so
the daemon read none of it, swallowed the error and ran on built-in defaults. The admin
had set `PLAYERS_CAN_CHANGE_PERSONA=false`; it had no effect, and nothing said so.

- `config.py` returns the failure instead of discarding it. `problem()` reports what went
  wrong and how to fix it, and `truthy()` now fails **closed** — every boolean setting here
  grants a permission, so a file that cannot be read must not be able to hand out a
  permission the admin withheld.
- `mcpersona` surfaces the reason, so a refusal reads as a fixable permission problem
  rather than an inexplicable no.
- `mchealth` checks whether **mcbot** can read the config, not whether the caller can —
  the tool normally runs as the admin, who has their own access, so opening the file
  proves nothing. It reads the permissions directly and accounts for the ACL mask, since
  a file's group bits *are* its mask and a named-user entry can be listed while granting
  nothing. Verified against all five cases, including that mask trap.
- README: dropped a version number in the header that had been stale since 0.2, and added
  `mcpersona` to the tool table.

## 0.10.0 — Minecraft 26.2 (NeoForge)

**Shapes, and marking a build out in the world instead of reading coordinates aloud.**

- New `mcshape`: box, sphere, ellipsoid, cylinder, dome, bowl, cone, pyramid, torus, disc,
  line, wall and ramp. `--hollow` with `--thickness` works on all of them.
- New `mcmark`: gold block marks a corner, emerald the centre, redstone a second
  measurement. `mcshape --from-markers <player>` builds from them and clears them
  afterwards so they are never left inside the build. Sweeping for markers is only
  practical because blocks are read from the region files — a 128-block box costs
  hundredths of a second, so no selection wand or click handling is needed.
- New `builder.py` merges the computed blocks back into as few fills as possible: runs
  along x, rectangles across z, then boxes up y. A 22,470-block cylinder becomes 19 fills
  and a cuboid becomes one. Merging is verified lossless against the original cell set.
- Hollowing is erosion — a block is shell if something beside it is not in the shape — so
  it means the same for a torus as for a box and cannot disagree with the solid form.
- Measured: a hollow radius-12 sphere is 1,550 blocks in 446 fills, built in 3.5s.

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

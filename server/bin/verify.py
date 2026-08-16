"""verify.py — read a box back off disk and say what is really in it.

Every writing tool reports the number RCON handed it. RCON counts the commands it ran,
not the blocks that ended up as intended, and the two come apart exactly when it matters.
`mcrepave` cloned a hillside into a tunnel, 1190 blocks, and reported every one as a
success. The count was true. The road was still wrong, and a player found it.

So this module answers two different questions, and both read the world rather than the
report:

    report(reader, box)     what is in this box: counts, surfaces, voids, and any block
                            that does not appear in the terrain around it
    confirm(before, after,  did the write that just ran put the block it promised where
            block, count)   it promised

A tool that writes takes a snapshot() first, writes, flushes, snapshots again, and
refuses to claim success if confirm() disagrees. That costs two surveys and one flush
per write, which is cheap next to the price of finding the damage in game a week later.

Nothing here writes. Every read comes from the region files, so the caller flushes first;
`snapshot` deliberately does not flush on its own, because one flush covers any number of
reads after it and a per-call flush would make a write cost three.
"""
import region

# A control ring this far outside the box, at the same levels, is what "foreign" is
# measured against. Eight blocks is wider than most player builds overhang their
# footprint and narrow enough that the ring is still the same terrain and biome.
CONTROL_MARGIN = 8

# Columns are listed individually up to this many, then summarised. A 32x32 footprint of
# them is already a few thousand numbers, and the caller is usually a language model
# paying for every one. Totals are always reported, so an omitted list is never a
# truncated answer — see the note fields, and the level histogram that covers every
# column however big the box is.
MAX_COLUMNS = 1024


def short(name: str | None) -> str | None:
    """A block id with its namespace and its block state stripped.

    `minecraft:oak_log[axis=x]` and `oak_log` are the same block for counting purposes,
    and a tool is as likely to be handed one form as the other.
    """
    if not name:
        return None
    return name.split("[", 1)[0].split(":", 1)[-1]


# ---------------------------------------------------------------- snapshots

def snapshot(reader, box) -> dict[str, int]:
    """Count every block id in a box. The caller flushes first."""
    return reader.survey(box)


def gained(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    """Ids that went up, and by how much."""
    return {name: after[name] - before.get(name, 0)
            for name in after if after[name] > before.get(name, 0)}


def lost(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    """Ids that went down, and by how much."""
    return {name: before[name] - after.get(name, 0)
            for name in before if before[name] > after.get(name, 0)}


def confirm(before: dict[str, int], after: dict[str, int], block: str,
            claimed: int) -> str | None:
    """Why the world disagrees with a write that reported success, or None if it agrees.

    The claim under test is the one every writing tool makes: "I placed `claimed` blocks
    of `block` here". Three ways that turns out to be false, all of them seen:

      * nothing moved — the fill went into chunks that were not loaded yet, or the
        coordinates missed, and RCON still answered cheerfully;
      * something moved, but not this block — a clone copied whatever was at the source,
        which is how a hillside ended up in a tunnel;
      * far less moved than was claimed.

    The count is not required to match exactly. Filling a box that already held some of
    the target block changes fewer blocks than it reports, and a fill of air over air
    legitimately moves nothing. So the test is directional: if the tool says it placed
    blocks, that id has to have gone up, and it has to have gone up by a believable
    share of the claim.
    """
    if claimed <= 0:
        return None

    want = short(block)
    up = {short(k): v for k, v in gained(before, after).items()}
    actual = up.get(want, 0)

    if actual == 0:
        moved = ", ".join(f"{k} +{v:,}" for k, v in sorted(up.items(),
                                                           key=lambda kv: -kv[1])[:4])
        return (f"{claimed:,} block(s) of {want} were reported, and the box holds no "
                f"more {want} than before the write"
                + (f" (what did change: {moved})" if moved else
                   " (nothing in the box changed at all)"))

    # A fill over ground that already held the target block legitimately places fewer
    # blocks than the box holds, so only a large shortfall is evidence of a failure.
    if actual * 2 < claimed:
        return (f"{claimed:,} block(s) of {want} were reported and the box gained "
                f"only {actual:,}")
    return None


class Watch:
    """Before-and-after over one box, so a writing tool can check its own work.

        watch = verify.Watch(dimension, box)      # surveys the box as it is now
        changed = ...write...
        problem = watch.check(block, changed)     # flushes, surveys again, compares
        if problem:
            raise ValueError(problem)             # do not report a success

    The flush in check() is not optional and there is no way to turn it off. Reading the
    files without one returns the state before the write, which makes every write look
    like a failure — and a tool that cries wolf gets its check removed.

    When the box cannot be read at all — an ungenerated region, a box past the survey
    limit, RCON down — `note` says so and check() returns None. An unreadable world is
    not evidence that a write failed, and refusing every write because the checker is
    blind would be worse than the problem. The note goes to the operator either way, so
    "not checked" never reads as "checked and fine".
    """

    def __init__(self, dimension: str, box):
        self.dimension = dimension
        self.box = region._ordered(box)
        self.reader = None
        self.before = None
        self._after = None
        self.note = None
        try:
            self.reader = region.Reader(dimension)
            self.reader.flush()
            self.before = snapshot(self.reader, self.box)
        except Exception as e:                      # noqa: BLE001 — see below
            # Deliberately broad. This is a check on the side of a write that is going
            # to happen anyway, and no failure to read the world should stop the write
            # or crash the tool. The reason is kept and reported.
            self.reader = None
            self.note = f"could not read the box before the write ({e})"

    def after(self) -> dict[str, int] | None:
        """The box as it stands now. Flushed once and kept, so two checks cost one read."""
        if self.reader is None or self.before is None:
            return None
        if self._after is None:
            try:
                self.reader.flush()
                self._after = snapshot(self.reader, self.box)
            except Exception as e:                  # noqa: BLE001 — as above
                self.note = f"could not read the box back after the write ({e})"
                return None
        return self._after

    def check(self, block: str, claimed: int) -> str | None:
        """The write said it placed `claimed` of `block`. Does the world agree?"""
        after = self.after()
        return None if after is None else confirm(self.before, after, block, claimed)

    def unexpected(self, allowed) -> str | None:
        """Solid blocks left in the box that are none of the kinds the tool meant to place.

        For a write whose result is a set of known kinds rather than one block — a
        repave lays whichever markings the road already uses. It is the direct test for
        the failure that made this module necessary: a clone that ran from the wrong
        source leaves the source's terrain sitting where markings should be.

        Passable blocks are ignored on purpose. Snow falls on a road between the write
        and the read and reads as a stray block; grass grows back. Neither is evidence
        that the clone went wrong, and a check that fails on weather gets switched off.
        """
        after = self.after()
        if after is None:
            return None
        ok = {short(name) for name in allowed}
        strays = {name: count for name, count in after.items()
                  if short(name) not in ok and not region.passable(name)}
        if not strays:
            return None
        listed = ", ".join(f"{name} x{count:,}"
                           for name, count in sorted(strays.items(),
                                                     key=lambda kv: -kv[1])[:5])
        return (f"the box holds solid blocks that are none of the kinds this was meant "
                f"to place ({listed}); expected only "
                + ", ".join(sorted(ok)))


# ---------------------------------------------------------------- surveying a box

def _columns(reader, box):
    """For every column in the box: (x, z, surface y, unsupported blocks under it).

    Surface is the highest block that would stop someone walking. The second number is
    the run of passable blocks directly beneath it, which is what a road resting on
    nothing looks like from above.

    Directly beneath, not anywhere beneath. Counting every air block in the column
    reported 1,547 of 1,681 columns as undermined over ordinary cave country, and a
    number that fires on everything says nothing. What a tool needs to know after it
    lays a surface is whether that surface is standing on something.
    """
    x1, y1, z1, x2, y2, z2 = region._ordered(box)
    for x in range(x1, x2 + 1):
        for z in range(z1, z2 + 1):
            surface = None
            hollow = 0
            for y in range(y2, y1 - 1, -1):
                solid = not region.passable(reader.block(x, y, z))
                if surface is None:
                    if solid:
                        surface = y
                    continue
                if solid:
                    break               # the surface is standing on this
                hollow += 1
            yield x, z, surface, hollow


def _control_boxes(box, margin: int):
    """The four slabs of terrain flanking a box, at the same levels.

    A ring rather than a bigger box: the point is to sample what the surroundings are
    made of without including the box itself in the comparison.
    """
    x1, y1, z1, x2, y2, z2 = region._ordered(box)
    return [
        (x1 - margin, y1, z1 - margin, x1 - 1, y2, z2 + margin),
        (x2 + 1, y1, z1 - margin, x2 + margin, y2, z2 + margin),
        (x1, y1, z1 - margin, x2, y2, z1 - 1),
        (x1, y1, z2 + 1, x2, y2, z2 + margin),
    ]


def foreign(reader, box, counts: dict[str, int], margin: int = CONTROL_MARGIN):
    """Block ids in the box that the terrain around it does not use.

    There is no list of "natural blocks" here on purpose. Any such list is wrong for the
    next modded block added to the server, and wrong quietly — it would wave a player's
    build through. The surrounding terrain already knows what belongs at these levels in
    this biome, so the question is asked of the world instead: survey a ring outside the
    box at the same y-range, and report what appears inside and not outside.

    This is a signal, not a verdict. A genuinely rare natural block reads as foreign.
    Returns (ids, note); ids is None when there is no generated terrain to compare
    against, because "everything is foreign" is a wrong answer rather than a loud one.
    """
    control: dict[str, int] = {}
    for ring in _control_boxes(box, margin):
        for name, count in reader.survey(ring).items():
            control[name] = control.get(name, 0) + count

    if not control:
        return None, ("no generated terrain around this box, so there is nothing to "
                      "compare against")

    known = {short(name) for name in control}
    odd = {name: count for name, count in counts.items() if short(name) not in known}
    return odd, None


def report(reader, box, margin: int = CONTROL_MARGIN,
           max_columns: int = MAX_COLUMNS) -> dict:
    """Everything this module can say about a box, as plain data.

    Read-only. The caller flushes first, so the answer describes the last save.

    Entities are not in here. Minecarts, boats and item frames live in the world's
    separate entities/ region files, which this reader does not decode, so a box that
    reports clean may still have a minecart parked in it. Saying so in the schema beats
    implying a check that does not happen.
    """
    x1, y1, z1, x2, y2, z2 = region._ordered(box)
    counts = snapshot(reader, (x1, y1, z1, x2, y2, z2))

    levels: dict[int, int] = {}
    empty, undermined, listed = [], [], []
    total_columns = 0
    for x, z, surface, holes in _columns(reader, (x1, y1, z1, x2, y2, z2)):
        total_columns += 1
        if surface is None:
            empty.append([x, z])
        else:
            levels[surface] = levels.get(surface, 0) + 1
            if holes:
                undermined.append([x, z, surface, holes])
        if total_columns <= max_columns:
            listed.append([x, z, surface])

    odd, odd_note = foreign(reader, (x1, y1, z1, x2, y2, z2), counts, margin)

    out = {
        "dimension": reader.dimension,
        "box": [x1, y1, z1, x2, y2, z2],
        "volume": (x2 - x1 + 1) * (y2 - y1 + 1) * (z2 - z1 + 1),
        "blocks": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "distinct_ids": len(counts),
        "surface": {
            "columns": total_columns,
            "levels": {str(y): n for y, n in sorted(levels.items())},
            "min": min(levels) if levels else None,
            "max": max(levels) if levels else None,
        },
        "voids": {
            "empty_columns": len(empty),
            "empty": empty[:max_columns],
            "undermined_columns": len(undermined),
            "undermined": undermined[:max_columns],
        },
        "foreign": odd,
        "entities": "not read: this reader decodes blocks only",
    }
    if odd_note:
        out["foreign_note"] = odd_note
    out["columns"] = listed if total_columns <= max_columns else None
    if total_columns > max_columns:
        out["columns_note"] = (f"{total_columns:,} columns, more than the {max_columns:,} "
                               f"listed one by one; the surface summary above covers all "
                               f"of them. Raise --max-columns to list them.")
    return out

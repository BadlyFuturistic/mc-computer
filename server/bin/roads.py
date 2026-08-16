"""roads — what a carriageway is, and which way it runs.

Three tools ask the same two questions about a road and answered them three different
ways. Every wrong answer showed up in the world as damage a player had to report.

  Which way does it run?  mcrepave took it from the shape of the strip it was given:
  the long side is the road. That holds for a strip of damage a hundred blocks long and
  fails on the short ones. A bore of a single block hands it a strip 1 along and 5
  across, so it decided the road ran across itself, sampled the tunnel walls for road,
  and cloned those into the floor.

  Is this actually road?  mcrepave took the commonest solid block under the strip. Under
  a strip is only the carriageway if the level is right; one block lower it is whatever
  the road was built on. Asked to repave at the wrong level it found stone, called stone
  the road surface, and laid stone across the carriageway.

Both questions have the same answer: ask the road, not the arguments. A carriageway runs
a long way one way and stops dead at its edges the other, and that shape is visible from
any block of it.
"""
import region

REACH = 24            # how far across to look before calling a surface unbounded
SHOULDER = 2          # how far past a strip a carriageway may reach, in total
RUN = 16              # identical slices in a row before a surface counts as built
SIGHT = 64            # how far along to look when measuring which way a road runs


def at(t: int, across: int, along_x: bool) -> tuple[int, int]:
    """World x, z from a position along the road and one across it."""
    return (t, across) if along_x else (across, t)


def reach(reader, y, x, z, dx, dz, kinds, limit=SIGHT) -> int:
    """How far the same kind of surface carries on in one direction."""
    n = 0
    for i in range(1, limit + 1):
        if reader.block(x + dx * i, y, z + dz * i) not in kinds:
            break
        n += 1
    return n


def direction(reader, y, x, z, kinds=None) -> bool:
    """Whether the road under this spot runs along x, measured from the road itself.

    A carriageway is long one way and a handful of blocks the other, so the two runs
    are never close. Taking this from the shape of a strip instead is what put a
    one-block bore's repave across the road rather than along it.
    """
    if kinds is None:
        name = reader.block(x, y, z)
        if name is None or region.passable(name):
            return True
        kinds = {name}
    x_run = reach(reader, y, x, z, 1, 0, kinds) + reach(reader, y, x, z, -1, 0, kinds)
    z_run = reach(reader, y, x, z, 0, 1, kinds) + reach(reader, y, x, z, 0, -1, kinds)
    return x_run >= z_run


def slice_names(reader, y, t, acrosses, along_x):
    """The blocks across the road at `t`, or None if any of them is passable.

    A road is continuous across its width. One passable spot means the edge of the
    carriageway, a hole, or open ground that merely happens to sit beside it, and
    copying any of those along would carry the flaw the whole way.
    """
    names = []
    for across in acrosses:
        x, z = at(t, across, along_x)
        name = reader.block(x, y, z)
        if region.passable(name):
            return None
        names.append(name)
    return names


def spreads_across(reader, y, t, acrosses, along_x, kinds) -> bool:
    """Whether this surface carries on sideways, which a carriageway does not."""
    extra = 0
    for step in (-1, 1):
        edge = (acrosses[0] - 1) if step < 0 else (acrosses[-1] + 1)
        for i in range(REACH):
            x, z = at(t, edge + step * i, along_x)
            if reader.block(x, y, z) not in kinds:
                break
            extra += 1
    return extra > SHOULDER


def bounded_slice(reader, y, t, acrosses, along_x):
    """The slice at `t` if it is solid all the way across and stops at its edges.

    Half of what separates road from ground, and the half that answers "is this level
    the carriageway?". The row under a road spreads sideways without end; the road
    itself stops dead at exactly its own width. That is enough to catch a repave aimed
    one level too low, and unlike the repeat test it still holds on a road with damage
    every few blocks, which is the state a repave is called on to fix.
    """
    names = slice_names(reader, y, t, acrosses, along_x)
    if not names:
        return None
    if spreads_across(reader, y, t, acrosses, along_x, set(names)):
        return None
    return names


def road_slice(reader, y, t, away, acrosses, along_x):
    """The slice at `t` if it is finished carriageway, else None.

    Solid ground is not road, and this is the whole difficulty. A hillside, a beach and
    a field are every bit as solid and continuous as a carriageway. A version of this
    test that asked only for solid, asked to carry a road on from the mouth of a tunnel,
    took the rock face in front of it for road and offered to clone stone, dirt and sand
    the whole way to the coast.

    Two things separate them, and one alone is not enough. A road stops dead at its
    edges: the carriageway at the end of one is bounded on both sides at exactly its own
    width. Natural ground does not, though it is patchier than it looks — a band of stone
    happened to run five blocks past a strip and no further, which a generous tolerance
    waved through. So the width has to match almost exactly, not roughly. A road is also
    built, so the same slice repeats along its length far beyond anything natural ground
    holds for.

    Ground has to fail both tests to be taken for road. Loosen either one and it does.
    """
    names = bounded_slice(reader, y, t, acrosses, along_x)
    if not names:
        return None
    for i in range(1, RUN + 1):
        if slice_names(reader, y, t + away * i, acrosses, along_x) != names:
            return None
    return names


def carriageway_near(reader, y, lo, hi, acrosses, along_x, reach=SIGHT) -> bool:
    """Whether the row at this level is carriageway anywhere around a strip.

    A repave is called on damage, so the blocks immediately beside it are often damaged
    too. Looking only at the two blocks flanking the strip made this refuse on a road
    that was merely pitted; looking along until road turns up answers the question that
    matters, which is whether this level is the road at all.
    """
    for end, away in ((lo - 1, -1), (hi + 1, +1)):
        for i in range(reach):
            if bounded_slice(reader, y, end + away * i, acrosses, along_x):
                return True
    return False

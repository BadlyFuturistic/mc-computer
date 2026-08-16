"""builder.py — turn a set of blocks into as few /fill commands as possible.

A shape is computed as a set of cells, which is easy to reason about and easy to get
right. Writing it back is the expensive half: a radius-20 sphere is about 33,000 blocks,
and one setblock each is roughly twenty minutes of round trips.

Almost every shape is mostly slabs, so the cells are merged back into boxes before
anything is sent: runs along x, then rectangles across z, then boxes up y. A solid
cylinder collapses to a handful of fills, a sphere to a few hundred, a cuboid to one.

Hollowing is done by erosion rather than per-shape arithmetic — a cell is shell if it
is in the shape and something beside it is not. That is the same three lines for a
sphere, a cone or a pyramid, and it cannot disagree with the solid form.
"""
import time

MAX_BLOCKS_PER_FILL = 32768      # hard server limit
SETTLE = 0.6                     # seconds for force-loaded chunks to become writable
CHUNK_MARGIN = 2
FORCELOAD_CAP = 256              # chunks per `forceload add`, enforced by the server
FORCELOAD_SIDE = 15              # chunks per side of one piece: 225, inside the cap

NEIGHBOURS = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))


def shell(cells: set, thickness: int = 1) -> set:
    """The outer `thickness` layers of a set of cells.

    Erosion, repeated. Anything with a missing neighbour is on the surface; strip that
    layer and repeat to go deeper. Works for any shape, including ones with no tidy
    equation, and can never contradict the solid version of the same shape.
    """
    remaining = set(cells)
    surface = set()
    for _ in range(max(1, thickness)):
        layer = {c for c in remaining
                 if any((c[0] + d[0], c[1] + d[1], c[2] + d[2]) not in remaining
                        for d in NEIGHBOURS)}
        if not layer:
            break
        surface |= layer
        remaining -= layer
    return surface


def to_boxes(cells: set) -> list[tuple[int, int, int, int, int, int]]:
    """Merge cells into boxes: runs along x, rectangles across z, then boxes up y."""
    if not cells:
        return []

    # 1. Runs along x, per (y, z).
    rows: dict[tuple[int, int], list[int]] = {}
    for x, y, z in cells:
        rows.setdefault((y, z), []).append(x)
    runs = []                                  # (y, z, x1, x2)
    for (y, z), xs in rows.items():
        xs.sort()
        start = prev = xs[0]
        for x in xs[1:]:
            if x != prev + 1:
                runs.append((y, z, start, prev))
                start = x
            prev = x
        runs.append((y, z, start, prev))

    # 2. Runs with the same x-extent, on consecutive z, become rectangles.
    by_span: dict[tuple[int, int, int], list[int]] = {}
    for y, z, x1, x2 in runs:
        by_span.setdefault((y, x1, x2), []).append(z)
    rects = []                                 # (y, x1, x2, z1, z2)
    for (y, x1, x2), zs in by_span.items():
        zs.sort()
        start = prev = zs[0]
        for z in zs[1:]:
            if z != prev + 1:
                rects.append((y, x1, x2, start, prev))
                start = z
            prev = z
        rects.append((y, x1, x2, start, prev))

    # 3. Identical footprints on consecutive y become boxes.
    by_face: dict[tuple[int, int, int, int], list[int]] = {}
    for y, x1, x2, z1, z2 in rects:
        by_face.setdefault((x1, x2, z1, z2), []).append(y)
    boxes = []
    for (x1, x2, z1, z2), ys in by_face.items():
        ys.sort()
        start = prev = ys[0]
        for y in ys[1:]:
            if y != prev + 1:
                boxes.append((x1, start, z1, x2, prev, z2))
                start = y
            prev = y
        boxes.append((x1, start, z1, x2, prev, z2))
    return boxes


def split(box, cap: int = MAX_BLOCKS_PER_FILL):
    """Cut a box down until each piece is inside the server's fill limit."""
    x1, y1, z1, x2, y2, z2 = box
    wide, deep = x2 - x1 + 1, z2 - z1 + 1
    per_layer = wide * deep
    if per_layer > cap:
        # Even one layer is too big: split across z as well.
        step_z = max(1, cap // wide)
        for sz in range(z1, z2 + 1, step_z):
            yield from split((x1, y1, sz, x2, y2, min(sz + step_z - 1, z2)), cap)
        return
    step_y = max(1, cap // per_layer)
    for sy in range(y1, y2 + 1, step_y):
        yield (x1, sy, z1, x2, min(sy + step_y - 1, y2), z2)


def falling_above(reader, cells) -> set:
    """Sand and gravel resting directly on blocks that are about to be removed.

    Whatever is above the hole comes down with it, and keeps coming down: the column
    empties from the ground all the way to the surface, so a fill under a desert or a
    gravel bank damages the landscape above as well as burying what was dug out.
    """
    import region

    return {(x, y + 1, z) for (x, y, z) in cells
            if (x, y + 1, z) not in cells and region.falls(reader.block(x, y + 1, z))}


def falling_over_box(reader, box) -> set:
    """The same question for a solid box, without expanding it into cells."""
    import region

    x1, _, z1, x2, y2, z2 = box
    return {(x, y2 + 1, z)
            for x in range(x1, x2 + 1) for z in range(z1, z2 + 1)
            if region.falls(reader.block(x, y2 + 1, z))}


def bounds(cells):
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    zs = [c[2] for c in cells]
    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def load_boxes(x1, z1, x2, z2, side: int = FORCELOAD_SIDE):
    """A region split into pieces small enough for one `forceload add` each.

    The server refuses more than 256 chunks in one command and, refusing, loads none of
    them. A single command for a 2000-block road asked for 645, so nothing was loaded,
    the clones that followed went into chunks that were not there, and the tool reported
    1776 slices that "would not take the clone" without saying why.
    """
    out = []
    for cx in range(x1 >> 4, (x2 >> 4) + 1, side):
        ex = min(x2 >> 4, cx + side - 1)
        for cz in range(z1 >> 4, (z2 >> 4) + 1, side):
            ez = min(z2 >> 4, cz + side - 1)
            out.append((max(x1, cx << 4), max(z1, cz << 4),
                        min(x2, (ex << 4) + 15), min(z2, (ez << 4) + 15)))
    return out


def forceload(rcon, ctx: str, box, add: bool = True) -> None:
    """Load or release a region, in as many commands as the chunk cap needs."""
    verb = "add" if add else "remove"
    for x1, z1, x2, z2 in load_boxes(*box):
        rcon.command(f"{ctx}forceload {verb} {x1} {z1} {x2} {z2}")


def write(rcon, dimension: str, cells: set, block: str, replace: str | None = None,
          progress=None) -> int:
    """Force-load, fill, release. Returns the number of blocks actually changed."""
    if not cells:
        return 0
    ctx = f"execute in {dimension} run "
    x1, y1, z1, x2, y2, z2 = bounds(cells)
    load = (x1 - CHUNK_MARGIN * 16, z1 - CHUNK_MARGIN * 16,
            x2 + CHUNK_MARGIN * 16, z2 + CHUNK_MARGIN * 16)
    suffix = f" replace {replace}" if replace else ""

    pieces = [p for box in to_boxes(cells) for p in split(box)]
    changed = 0
    forceload(rcon, ctx, load, add=True)
    try:
        # A chunk force-loaded a moment ago is not there yet, and filling it silently
        # changes nothing.
        time.sleep(SETTLE)
        for i, (bx1, by1, bz1, bx2, by2, bz2) in enumerate(pieces, 1):
            out = rcon.command(f"{ctx}fill {bx1} {by1} {bz1} {bx2} {by2} {bz2} "
                               f"{block}{suffix}")
            if "Unknown block" in out or "Unknown tag" in out or "<--[HERE]" in out:
                raise ValueError(
                    f"unknown block or filter in: {block}{suffix}. `mcblock survey "
                    f"<box>` lists the ids that are really there.")
            if "Successfully filled" in out:
                changed += int("".join(c for c in out.split("filled")[1]
                                       if c.isdigit()) or 0)
            if progress and i % 25 == 0:
                progress(i, len(pieces), changed)
    finally:
        forceload(rcon, ctx, load, add=False)
    return changed
